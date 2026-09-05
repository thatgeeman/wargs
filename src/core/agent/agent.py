import json
import uuid
from abc import ABC

from pydantic import BaseModel

from ...config import Config
from ..model import Model
from .prompts import (
    HypothesisAgPrompt,
    QuestionAnalyzerAgPrompt,
    ResearchPlannerAgPrompt,
    ResearchTaskAgPrompt,
    RetrySchemaAgPrompt,
)
from .schemas import (
    ManyHypothesesAgSchema,
    ManyResearchPlannerAgSchema,
    ManyResearchTaskAgSchema,
    QuestionAnalysisAgSchema,
)

cfg = Config()
logger = cfg.get_logger("AgentLogger")


class Agent(ABC):
    def __init__(self, name, input, output_schema, tools: list = [], max_retries=1):
        self.name = name
        self.input = input
        self.output_schema: BaseModel = output_schema
        self.tools = tools
        self.model = None
        self.config = Config()
        self.traces = []
        self.session_id = uuid.uuid4()
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
        return {
            "type": "json_schema",
            "json_schema": {
                "name": self.name,
                "schema": self.output_schema.model_json_schema(),
                "strict": True,
            },
        }

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

    def done(self):
        self.state_transition("DONE")
        self.save_trace()
        logger.info(f"{self.name} has completed its run and saved the trace.")

    def _trigger_run(self, **kwargs):
        logger.info(f"Running {self.name} with input: {self.input}")
        to_json = kwargs.get("to_json", False)
        try:
            self.model = Model(system_prompt=self.prompts.system_prompt)
            response = self.model.call(
                self.prompts.user_prompt, output_schema=self.get_json_schema()
            )
            choice = response.choices[0]
            # Store the choice as a dictionary in the trace for later analysis
            self.store_trace(choice.model_dump())
            self.state_transition("GENERATION")
            msg = choice.message.content.strip()
            return (
                msg if not to_json else validate_schema_and_fix(msg, self.output_schema)
            )
        except Exception as e:
            logger.error(f"Error occurred while triggering run for {self.name}: {e}")
            self.state_transition("ERROR")
            return None

    def run(self, to_json=False):
        for attempt in range(1, self.max_retries + 1):
            msg = self._trigger_run(to_json=to_json)
            if msg:
                logger.info(
                    f"{self.name} succeeded (attempt={attempt}/max_retries={self.max_retries})"
                )
                return msg
            if attempt < self.max_retries:
                logger.info(
                    f"Retrying {self.name} (attempt={attempt}/max_retries={self.max_retries})"
                )
        logger.error(f"{self.name} failed after {self.max_retries} attempt(s).")
        return None

    def run_once(self, to_json=False):
        try:
            result = self.run(to_json=to_json)
            self.done()
            return result
        except Exception as e:
            logger.error(f"Error occurred while running {self.name}: {e}")
            self.state_transition("ERROR")
            return None


def validate_schema_and_fix(jsons_msg, schema: BaseModel, max_retries=3):
    error_logs = []
    parsed = None
    # try parsing json
    try:
        parsed = json.loads(jsons_msg)
    except Exception as e:
        error_logs.append(e)

    # validate json schema with the model
    if parsed is not None:
        try:
            return schema.model_validate(parsed)
        except Exception as e:
            error_logs.append(e)

    # initial parse/validation failed, ask the retry agent to repair the output
    agent = RetrySchemaAgent(
        input=jsons_msg,
        output_schema=schema,
        error_logs=error_logs,
        max_retries=max_retries,
    )
    return agent.run_once(True)


class RetrySchemaAgent(Agent):
    def __init__(
        self,
        input: str,
        output_schema: BaseModel,
        max_retries=3,
        error_logs: str | list[str] = "",
    ):
        self.instance_id = uuid.uuid4()
        self.name = "RetrySchemaAgent_" + str(self.instance_id)
        self.output_schema = output_schema
        self.prompts = RetrySchemaAgPrompt(input, output_schema, error_logs=error_logs)
        super().__init__(self.name, input, self.output_schema, max_retries=max_retries)


class QuestionAnalyzerAgent(Agent):
    def __init__(self, input, max_retries=1):
        self.instance_id = uuid.uuid4()
        self.name = "QuestionAnalyzerAgent_" + str(self.instance_id)
        self.prompts = QuestionAnalyzerAgPrompt(input)
        self.output_schema = QuestionAnalysisAgSchema()
        super().__init__(self.name, input, self.output_schema, max_retries=max_retries)


class HypothesisAgent(Agent):
    def __init__(self, input, analysis=None, clarification=None, max_retries=1):
        self.instance_id = uuid.uuid4()
        self.name = "HypothesisAgent_" + str(self.instance_id)
        self.prompts = HypothesisAgPrompt(
            input, analysis=analysis, clarification=clarification
        )
        self.output_schema = ManyHypothesesAgSchema()
        super().__init__(self.name, input, self.output_schema, max_retries=max_retries)


class ResearchPlanner(Agent):
    def __init__(self, input: str, hypothesis: ManyHypothesesAgSchema = [], max_retries=1):
        self.instance_id = uuid.uuid4()
        self.name = "ResearchPlannerAgent_" + str(self.instance_id)
        self.hypothesis = hypothesis
        self.prompts = ResearchPlannerAgPrompt(question=input, hypothesis=hypothesis)
        self.output_schema = ManyResearchPlannerAgSchema()
        super().__init__(self.name, input, self.output_schema, max_retries=max_retries)


class ResearchTask(Agent):
    def __init__(
        self, input: str, plans: list = [], tools: list = [], max_retries=1
    ):
        self.instance_id = uuid.uuid4()
        self.name = "ResearchTaskAgent_" + str(self.instance_id)
        self.tools = tools
        self.prompts = ResearchTaskAgPrompt(
            question=input, plans=plans, tools=tools
        )
        self.output_schema = ManyResearchTaskAgSchema()
        super().__init__(self.name, input, self.output_schema, self.tools, max_retries=max_retries)


if __name__ == "__main__":
    input_text = "Why is gaza and israel in conflict?"
    agent = HypothesisAgent(input=input_text)
    result = agent.run()
    print(result)
    agent.done()
