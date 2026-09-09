import json
import random
import time
import uuid
from abc import ABC

from pydantic import BaseModel

from ...config import Config
from ..model import Model
from .prompts import (
    ContradictionAgPrompt,
    DecisionAgPrompt,
    EvidenceEvaluatorAgPrompt,
    HypothesisAgPrompt,
    QuestionAnalyzerAgPrompt,
    ResearchPlannerAgPrompt,
    ResearchTaskAgPrompt,
    RetrySchemaAgPrompt,
)
from .schemas import (
    ContradictionAgSchema,
    DecisionAgSchema,
    EvidenceEvaluationAgSchema,
    ManyHypothesesAgSchema,
    ManyResearchPlannerAgSchema,
    ManyResearchTaskAgSchema,
    QuestionAnalysisAgSchema,
)

cfg = Config()
logger = cfg.get_logger("AgentLogger")


class Agent(ABC):
    def __init__(
        self,
        name,
        input,
        output_schema,
        tools: list = [],
        max_retries=1,
        session_id=None,
    ):
        self.name = name
        self.input = input
        self.output_schema: BaseModel = output_schema
        self.tools = tools
        self.model = None
        self.config = Config()
        self.traces = []
        self.session_id = session_id if session_id else uuid.uuid4()
        self.trace_file = (
            self.config.config_dir / f"trace_{self.session_id}" / f"{self.name}.json"
        )
        self.max_retries = max_retries
        self.state = "INIT"

    def state_transition(self, new_state):
        logger.info(
            f"Transitioning {self.name} from state '{self.state}' to '{new_state}'"
        )
        self.state = new_state

    def get_json_schema(self):
        try:
            assert isinstance(self.output_schema, BaseModel), (
                "output_schema must be a Pydantic BaseModel"
            )
        except AssertionError as e:
            logger.error(e)
        schema = self.output_schema.model_json_schema()
        self._strip_content_schema(schema)
        self._strip_harness_only_fields(schema)
        self._require_all_fields(schema)
        return {
            "type": "json_schema",
            "json_schema": {
                "name": self.name,
                "schema": schema,
                "strict": True,
            },
        }

    @staticmethod
    def _strip_harness_only_fields(node):
        """Remove fields marked harness-only (json_schema_extra harness_only)
        from the wire schema: the LLM never sees fields it must not fill
        (e.g. result). The fields stay on the Python model for the harness."""
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict):
                for key in [
                    k
                    for k, v in props.items()
                    if isinstance(v, dict) and v.get("harness_only")
                ]:
                    del props[key]
                    if (
                        isinstance(node.get("required"), list)
                        and key in node["required"]
                    ):
                        node["required"].remove(key)
            for value in node.values():
                Agent._strip_harness_only_fields(value)
        elif isinstance(node, list):
            for value in node:
                Agent._strip_harness_only_fields(value)

    @staticmethod
    def _require_all_fields(node):
        """Declare all properties required in the wire schema. With
        all-optional fields, '{}' is schema-valid and constrained decoders can
        emit it as the minimal object; requiring every field makes empty
        responses impossible for grammar-constrained backends. Python-side
        defaults (and validation) are unaffected — this only shapes what the
        model must produce."""
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict) and props:
                node["required"] = list(props.keys())
            for value in node.values():
                Agent._require_all_fields(value)
        elif isinstance(node, list):
            for value in node:
                Agent._require_all_fields(value)

    @staticmethod
    def _strip_content_schema(node):
        """Remove contentSchema/contentMediaType metadata (emitted by
        Json[...] fields): strict endpoints reject both. Pydantic still
        validates the string's content at parse time."""
        if isinstance(node, dict):
            node.pop("contentSchema", None)
            node.pop("contentMediaType", None)
            for value in node.values():
                Agent._strip_content_schema(value)
        elif isinstance(node, list):
            for value in node:
                Agent._strip_content_schema(value)

    def store_trace(self, trace_data: dict):
        if not isinstance(trace_data, dict):
            logger.error(
                f"Instance trace data must be a dictionary. Received type: {type(trace_data)}"
            )
            return
        self.traces.append(trace_data)

    def save_trace(self):
        import os

        save_mode = "w"  # write mode by default
        os.makedirs(os.path.dirname(self.trace_file), exist_ok=True)
        if os.path.exists(self.trace_file):
            save_mode = "a"  # Append if trace file exists
            logger.warning(f"Trace file path is non existent for agent {self.name}.")
        if len(self.traces) == 0:
            logger.warning(f"No trace data to save for agent {self.name}.")
            return
        logger.debug(
            f"Saving trace for {self.name} to {self.trace_file} with mode '{save_mode}'"
        )
        with open(self.trace_file, save_mode) as f:
            json.dump(self.traces, f, indent=4)
            logger.info(f"Trace for {self.name} saved to {self.trace_file}")

    def done(self):
        self.state_transition("DONE")
        self.save_trace()
        logger.info(f"{self.name} has completed its run and saved the trace.")

    def _trigger_run(self, **kwargs):
        logger.info(f"Running {self.name} with input: {self.input}")
        to_json = kwargs.get("to_json", False)
        attempt = kwargs.get("attempt", 1)
        extra_response = {}  # may never be assigned by model.call if it raises
        try:
            # first attempt stays deterministic (temperature=0); retries get
            # increasing randomness so a failed generation isn't repeated
            # verbatim — at temperature=0 every retry would be identical.
            model_kwargs = {"temperature": min(0.3 * (attempt - 1), 0.9)}
            if getattr(self, "_max_tokens_override", None):
                # set by a previous truncated attempt (finish_reason='length')
                model_kwargs["max_tokens"] = self._max_tokens_override
            self.model = Model(
                system_prompt=self.prompts.system_prompt, **model_kwargs
            )
            response, extra_response = self.model.call(
                self.prompts.user_prompt, output_schema=self.get_json_schema()
            )
            if not response:
                return response, extra_response
            # check choices
            choice = response.choices[0]
            # Store the choice as a dictionary in the trace for later analysis
            self.store_trace(choice.model_dump())
            self.state_transition("GENERATION")
            if choice.finish_reason == "length":
                # Truncated by max_tokens — content is missing, so the schema
                # fixer cannot repair it. Treat as a failed attempt and
                # regenerate from scratch with a doubled token budget (at
                # temperature=0 an identical retry would truncate the same way).
                self._max_tokens_override = min(self.model.max_tokens * 2, 32768)
                logger.warning(
                    f"{self.name}: response truncated (finish_reason='length', "
                    f"max_tokens={self.model.max_tokens}). Retrying generation "
                    f"with max_tokens={self._max_tokens_override}."
                )
                return None, extra_response
            msg = choice.message.content.strip()
            msg = (
                msg
                if not to_json
                else validate_schema_and_fix(
                    msg, self.output_schema, session_id=self.session_id
                )
            )
            return (msg, extra_response)
        except Exception as e:
            logger.error(f"Error occurred while triggering run for {self.name}: {e}")
            self.state_transition("ERROR")
            return None, extra_response

    def run(self, to_json=False):
        extra_response = {}
        for attempt in range(1, self.max_retries + 1):
            msg, extra_response = self._trigger_run(to_json=to_json, attempt=attempt)
            if msg:
                logger.info(
                    f"{self.name} succeeded (attempt={attempt}/max_retries={self.max_retries})"
                )
                self.done()
                return msg
            if attempt < self.max_retries:
                # if retry_after in extra response, then use that
                # retry with full jitter otherwise
                delay = min(30, 2 ** (attempt - 1))  # 1s, 2s, 4s… capped at 30s
                sleep = (
                    extra_response.get("retry_after")
                    if extra_response.get("retry_after", None)
                    else random.uniform(0.1, delay)  # jitter
                )
                logger.info(
                    f"Retrying {self.name} after {sleep}s (attempt={attempt} max_retries={self.max_retries})"
                )
                time.sleep(sleep)
        logger.error(f"{self.name} failed after {self.max_retries} attempt(s).")
        # save the trace on failure too — the raw responses of failed attempts
        # are exactly what's needed for debugging
        self.state_transition("FAILED")
        self.save_trace()
        return None

    def run_once(self, to_json=False):
        try:
            result = self.run(to_json=to_json)
            if result is not None:
                # run() already handles failure (FAILED state + trace saved);
                # only mark DONE on success
                self.done()
            return result
        except Exception as e:
            logger.error(f"Error occurred while running {self.name}: {e}")
            self.state_transition("ERROR")
            return None


def validate_schema_and_fix(
    jsons_msg, schema: BaseModel, max_retries=3, session_id=None
):
    error_logs = []
    parsed = None
    # try parsing json
    try:
        parsed = json.loads(jsons_msg)
    except Exception as e:
        error_logs.append(f"{__name__}: {e}")

    # validate json schema with the model
    if parsed is not None:
        try:
            validated = schema.model_validate(parsed)
            if not validated.model_fields_set - {"reasoning"}:
                # Empty object '{}' or reasoning-only: validates only because
                # every field has a default (pydantic does not validate
                # defaults), but contains no payload content. Schema-fixing
                # would have to invent content — treat as a failed generation
                # so the agent retries from scratch instead.
                logger.warning(
                    "Model returned no payload (empty object or reasoning only). "
                    "Treating as failed generation."
                )
                return None
            return validated
        except Exception as e:
            error_logs.append(e)

    # initial parse/validation failed, ask the retry agent to repair the output
    agent = RetrySchemaAgent(
        input=jsons_msg,
        output_schema=schema,
        error_logs=error_logs,
        max_retries=max_retries,
        session_id=session_id,
    )
    return agent.run_once(True)


class RetrySchemaAgent(Agent):
    def __init__(
        self,
        input: str,
        output_schema: BaseModel,
        max_retries=3,
        error_logs: str | list[str] = "",
        session_id=None,
    ):
        self.instance_id = uuid.uuid4()
        self.name = "RetrySchemaAgent_" + str(self.instance_id)
        self.output_schema = output_schema
        self.prompts = RetrySchemaAgPrompt(input, output_schema, error_logs=error_logs)
        super().__init__(
            self.name,
            input,
            self.output_schema,
            max_retries=max_retries,
            session_id=session_id,
        )


class QuestionAnalyzerAgent(Agent):
    def __init__(self, input, max_retries=1, session_id=None):
        self.instance_id = uuid.uuid4()
        self.name = "QuestionAnalyzerAgent_" + str(self.instance_id)
        self.prompts = QuestionAnalyzerAgPrompt(input)
        self.output_schema = QuestionAnalysisAgSchema()
        super().__init__(
            self.name,
            input,
            self.output_schema,
            max_retries=max_retries,
            session_id=session_id,
        )


class HypothesisAgent(Agent):
    def __init__(
        self, input, analysis=None, clarification=None, max_retries=1, session_id=None
    ):
        self.instance_id = uuid.uuid4()
        self.name = "HypothesisAgent_" + str(self.instance_id)
        self.prompts = HypothesisAgPrompt(
            input, analysis=analysis, clarification=clarification
        )
        self.output_schema = ManyHypothesesAgSchema()
        super().__init__(
            self.name,
            input,
            self.output_schema,
            max_retries=max_retries,
            session_id=session_id,
        )


class ResearchPlanner(Agent):
    def __init__(
        self,
        input: str,
        hypothesis: ManyHypothesesAgSchema = [],
        evaluation=None,
        contradictions=None,
        max_retries=1,
        session_id=None,
    ):
        self.instance_id = uuid.uuid4()
        self.name = "ResearchPlannerAgent_" + str(self.instance_id)
        self.hypothesis = hypothesis
        self.prompts = ResearchPlannerAgPrompt(
            question=input,
            hypothesis=hypothesis,
            evaluation=evaluation,
            contradictions=contradictions,
        )
        self.output_schema = ManyResearchPlannerAgSchema()
        super().__init__(
            self.name,
            input,
            self.output_schema,
            max_retries=max_retries,
            session_id=session_id,
        )


class ResearchTask(Agent):
    def __init__(
        self,
        input: str,
        plans: list = [],
        tools: list = [],
        evaluation=None,
        contradictions=None,
        max_retries=1,
        session_id=None,
    ):
        self.instance_id = uuid.uuid4()
        self.name = "ResearchTaskAgent_" + str(self.instance_id)
        self.tools = tools
        self.prompts = ResearchTaskAgPrompt(
            question=input,
            plans=plans,
            tools=tools,
            evaluation=evaluation,
            contradictions=contradictions,
        )
        self.output_schema = ManyResearchTaskAgSchema()
        super().__init__(
            self.name,
            input,
            self.output_schema,
            self.tools,
            max_retries=max_retries,
            session_id=session_id,
        )


class EvidenceEvaluator(Agent):
    def __init__(
        self,
        input: str,
        clarification=None,
        hypothesis=None,
        plans=None,
        tasks=None,
        evidence=None,
        max_retries=1,
        session_id=None,
    ):
        self.instance_id = uuid.uuid4()
        self.name = "EvidenceEvaluatorAgent_" + str(self.instance_id)
        self.prompts = EvidenceEvaluatorAgPrompt(
            question=input,
            clarification=clarification,
            hypothesis=hypothesis,
            plans=plans,
            tasks=tasks,
            evidence=evidence,
        )
        self.output_schema = EvidenceEvaluationAgSchema()
        super().__init__(
            self.name,
            input,
            self.output_schema,
            max_retries=max_retries,
            session_id=session_id,
        )
        # auto-run (executor-style): evaluation is available right after construction
        result = self.run(to_json=True)
        self.evaluation = result.model_dump() if result else {}


class DecisionAgent(Agent):
    def __init__(
        self,
        input: str,
        clarification=None,
        hypothesis=None,
        plans=None,
        tasks=None,
        evidence=None,
        evaluation=None,
        max_retries=1,
        session_id=None,
    ):
        self.instance_id = uuid.uuid4()
        self.name = "DecisionAgent_" + str(self.instance_id)
        self.prompts = DecisionAgPrompt(
            question=input,
            clarification=clarification,
            hypothesis=hypothesis,
            plans=plans,
            tasks=tasks,
            evidence=evidence,
            evaluation=evaluation,
        )
        self.output_schema = DecisionAgSchema()
        super().__init__(
            self.name,
            input,
            self.output_schema,
            max_retries=max_retries,
            session_id=session_id,
        )
        # auto-run (executor-style): evaluation is available right after construction
        result = self.run(to_json=True)
        self.decision = result.model_dump() if result else {}


class ContradictionAgent(Agent):
    def __init__(
        self,
        input: str,
        clarification=None,
        hypothesis=None,
        hypothesis_id=None,
        plans=None,
        tasks=None,
        evidence=None,
        evaluation=None,
        max_retries=1,
        session_id=None,
    ):
        self.instance_id = uuid.uuid4()
        self.name = "DecisionAgent_" + str(self.instance_id)
        self.prompts = ContradictionAgPrompt(
            question=input,
            clarification=clarification,
            hypothesis=hypothesis,
            hypothesis_id=hypothesis_id,
            plans=plans,
            tasks=tasks,
            evidence=evidence,
            evaluation=evaluation,
        )
        self.output_schema = ContradictionAgSchema()
        super().__init__(
            self.name,
            input,
            self.output_schema,
            max_retries=max_retries,
            session_id=session_id,
        )
        # auto-run (executor-style): evaluation is available right after construction
        result = self.run(to_json=True)
        self.decision = result.model_dump() if result else {}


if __name__ == "__main__":
    input_text = "Why is gaza and israel in conflict?"
    agent = HypothesisAgent(input=input_text)
    result = agent.run()
    print(result)
    agent.done()
