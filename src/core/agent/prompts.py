from datetime import datetime

from pydantic import BaseModel

from ...config import Config
from .schemas import (
    ManyContradictionsAgSchema,
    ManyHypothesesAgSchema,
)

cfg = Config()
logger = cfg.get_logger("PromptLogger")


class PromptClass:
    def __init__(self):
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.system_prompt = "You are a helpful assistant."
        self.user_prompt = (
            "Please provide a response to the following input: {input_text}"
        )


class RetrySchemaAgPrompt(PromptClass):
    def __init__(
        self,
        input_text,
        output_schema: BaseModel | None = None,
        error_logs: str | list[str] = "",
    ):
        super().__init__()
        self.system_prompt = """
        You are an expert JSON schema fixer. Your task is to fix and make sure the schema passes the validation.
        You are provided with a schema that failed validation and the error logs. 
        1. Use the error messages or exeption notices to fix 
        2. Note that the error logs may contain supplementary information that may not point to the actual failure 
        3. Focus purely on the JSON schema validation component.
        4. Line numbers or character positions in the schema error logs could help but do not trust it blindly.
        """
        self.error_logs_formatted = self.get_formatted_error_logs(error_logs)
        self.user_prompt = f"""
        Input: 
        {input_text}\n\n
        
        Error/Logs:
        {error_logs}\n\n
        
        Schema Expectation:
        {output_schema.model_json_schema()}\n\n
        The generated result (your Input) did not pass Pydantic's JSON schema validation. Please fix the Input so that it passes the schema."""

        logger.debug(f"User Prompt for Retry Agent:\n{self.user_prompt}")

    def get_formatted_error_logs(self, error_logs: str | list[str]):

        if isinstance(error_logs, str):
            error_logs = [error_logs]

        f_error_logs = ""
        for i, el in enumerate(error_logs):
            f_error_logs += f"""
            Number {i + 1}: {el}\n
            """

        return f_error_logs


class QuestionAnalyzerAgPrompt(PromptClass):
    def __init__(self, question):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.system_prompt = f"""
You are the Question Analyzer Agent in an autonomous investigation system.
Today's date is {self.date}.

Your responsibility is to analyze the investigation question BEFORE any
hypotheses are generated or research is done.

You do NOT:
- answer the question
- generate hypotheses
- do any research
- silently assume missing details — your job is precisely to surface them

You DO:
- classify the investigation type (e.g. comparative evaluation, causal
  explanation, fact verification, trend analysis)
- extract the explicit subject of the question
- surface implicit comparison targets or unstated assumptions the question
  relies on (e.g. "better than whom?", "according to which metric?")
- list the missing information that would be needed to investigate rigorously
  (definitions, evaluation criteria, time period, geographic scope, etc.)
- decide whether you can continue without requiring this extra detail, as
  rather than forcing the user to clarify, establishing a reasonable operational definition 
  leads to better user experience
- decide whether the question can be investigated as-is

Status rules:
- NEEDS_CLARIFICATION only when missing information would materially change the
  direction of the investigation. Do not be pedantic: gaps that research can
  resolve on its own are NOT a reason to ask the user. Dont be pushy for extra clarification, 
  if you can establish a reasonable operational definition upfront
- CLEAR when the question is specific enough to investigate meaningfully as-is.

Follow-up question rules:
- only formulate one when the status is NEEDS_CLARIFICATION; leave it empty
  otherwise
- ask ONE concise, natural-language question that resolves the most critical
  gaps — combine related gaps instead of interrogating the user with a list
  of separate questions
- phrase it so the user can answer in one or two sentences)

Return only the requested structured output.
"""
        self.user_prompt = f"""
QUESTION
{question}


Analyze the question above.
"""
        logger.debug(f"User Prompt for Question Analyzer Agent:\n{self.user_prompt}")


class HypothesisAgPrompt(PromptClass):
    def __init__(self, input_text, analysis=None, clarification=None):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.analysis_context = self.get_formatted_analysis(analysis, clarification)
        self.system_prompt = f"""
You are a hypothesis generation agent. Your task is to generate hypotheses based on the provided input from the user.
Today's date is {self.date}. 
Instructions:
1. Read the input text carefully.
2. Generate a list of plausible hypotheses that could explain the input.
3. Complex input may require multiple hypotheses. Ensure that each hypothesis is distinct and addresses different aspects of the input.
4. Ensure that the hypotheses are clear, concise, and relevant to the input. 
5. Evidence supporting each hypothesis should be provided if available. If no evidence is available, indicate that as well.
6. To base your hypotheses on evidence, you may need to conduct research using the tools available to you. Ensure that the evidence is credible and relevant to the hypotheses generated.
"""
        self.user_prompt = f"Input: {input_text}\n\n{self.analysis_context}Please generate hypotheses based on the above input."

        logger.debug(f"User Prompt for Hypothesis Agent:\n{self.user_prompt}")

    def get_formatted_analysis(self, analysis, clarification):
        """Render the question analysis and any user clarification as context sections."""
        sections = ""
        if analysis is not None:
            sections += "QUESTION ANALYSIS\n"
            if isinstance(analysis, BaseModel):
                for key, value in analysis.model_dump().items():
                    sections += f"{key}: {value}\n"
            else:
                sections += f"{analysis}\n"
            sections += "\n"
        if clarification:
            sections += f"USER CLARIFICATION\n{clarification}\n\n"
        return sections


class ResearchPlannerAgPrompt(PromptClass):
    def __init__(
        self,
        question,
        hypothesis: ManyHypothesesAgSchema = [],
        evaluation=None,
        contradictions=None,
    ):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.question = question
        self.hypothesis = self.get_formatted_hypothesis(hypothesis)
        self.evidence = self.get_formatted_evidence(hypothesis)
        self.evaluation = self.get_formatted_evaluation(evaluation)
        self.contradictions = (
            self.get_formatted_contradictions(contradictions) if contradictions else ""
        )
        self.system_prompt = f"""
You are the Research Planner Agent in an autonomous investigation system.
Today's date is {self.date}. 
Your responsibility is to determine the next best research actions for the investigation.

You do NOT:
- answer the investigation question
- select a final hypothesis
- invent evidence
- treat hypotheses as facts
- perform the research yourself

You DO:
- inspect the current investigation state
- identify important uncertainties and evidence gaps
- determine which hypotheses need to be distinguished
- propose concrete research actions that could reduce those uncertainties
- prioritize actions by expected usefulness

For each proposed research action, explain:
1. What should be investigated?
2. Why is this information useful?
3. Which hypothesis or hypotheses does it discriminate between?
4. What result would support each hypothesis?
5. What result would weaken each hypothesis?
6. What source or tool would be appropriate?

Prefer research actions that:
- distinguish multiple competing hypotheses
- can produce independently verifiable evidence
- target important uncertainties
- use primary or high-quality sources where possible
- avoid redundant searches
- are specific enough to be executed by a research tool

Do not assume that the current leading hypothesis is correct.
Actively look for research that could disprove or weaken it.

If evaluation feedback from a previous evidence round is provided, propose
research actions that address its gaps.

If contradictions for previous hypotheses from a previous evidence round is provided, propose
research actions that uses those contradictions as signal for your planning.

Every plan you propose is a NEW, not-yet-executed action: always set its status
to "ACTIVE". Never mark a plan as COMPLETED, WEAKENED, or INVALIDATED — those
transitions are applied later by the system based on gathered evidence.

Return only the requested structured output.
    """
        self.user_prompt = f"""
CURRENT INVESTIGATION

Question:
{self.question}


HYPOTHESES
{self.hypothesis}


CURRENT EXPECTED EVIDENCE
{self.evidence}


EVALUATION FEEDBACK FROM PREVIOUS EVIDENCE
{self.evaluation}

CONTRADICTIONS FROM PREVIOUS EVIDENCE
{self.contradictions}
"""
        logger.debug(f"User Prompt for PlannerAgent:\n{self.user_prompt}")

    def get_formatted_hypothesis(self, hs: ManyHypothesesAgSchema):
        """Takes a structured input and returns in paragraphs the hypothesis and condidence"""
        result = ""
        for _, h in enumerate(hs):
            result += (
                f"ID: {h.id}\nHypothesis: {h.hypothesis}\nConfidence: {h.confidence}\n"
            )
        return result

    def get_formatted_evidence(self, hs: ManyHypothesesAgSchema):
        """Takes a structured input and returns in paragraphs the supporting and weakening evidence expectations that are part per hypothesis"""
        result = ""
        for _, h in enumerate(hs):
            supporting_predictions = ""
            for idx, e in enumerate(h.supporting_predictions):
                supporting_predictions += (
                    f"Supporting Statement {idx} for Hypothesis {h.id}: {e}\n"
                )
            weakening_predictions = ""
            for idx, e in enumerate(h.weakening_predictions):
                weakening_predictions += (
                    f"Weakening Statement {idx} for Hypothesis {h.id}: {e}\n"
                )
            # now append that string to result
            result += f"Predicted Evidence for Hypothesis {h.id}\n{supporting_predictions}\n{weakening_predictions}\n"

        return result

    def get_formatted_evaluation(self, evaluation):
        """Render feedback from a previous evidence evaluation, if any."""
        if not evaluation:
            return "No prior evaluation — this is the first research round."
        if isinstance(evaluation, BaseModel):
            evaluation = evaluation.model_dump()
        if isinstance(evaluation, dict):
            return "\n".join(f"{key}: {value}" for key, value in evaluation.items())
        return str(evaluation)

    def get_formatted_contradictions(self, cs):
        """Render contradictions as readable text. Accepts a
        ManyContradictionsAgSchema or the investigator's list of
        ContradictionAgent objects (each result dict lives on the agent's
        .decision attribute)."""
        if not cs:
            return "No contradictions from previous rounds."
        entries = (
            cs.contradictions
            if isinstance(cs, ManyContradictionsAgSchema)
            else (cs if isinstance(cs, list) else [cs])
        )
        result = ""
        for c in entries:
            data = getattr(c, "decision", c)
            if isinstance(data, BaseModel):
                data = data.model_dump()
            if not isinstance(data, dict):
                result += f"{data}\n\n"
                continue
            if not data.get("contradiction_found"):
                continue
            result += (
                f"Hypothesis ID: {data.get('hypotheses_id')}\n"
                f"Contradiction Type: {data.get('contradiction_type')}\n"
                f"Contradiction: {data.get('contradiction')}\n"
                f"Evidence IDs: {data.get('evidence_ids')}\n"
                f"Alternate Hypothesis: {data.get('alternative_hypothesis')}\n"
                f"Severity: {data.get('severity')}\n"
                f"Recommended Followup: {data.get('recommended_followup')}\n\n"
            )
        return result.strip() or "No contradictions from previous rounds."


class ResearchTaskAgPrompt(PromptClass):
    def __init__(
        self,
        question,
        plans=None,
        tools=None,
        evaluation=None,
        contradictions=None,
    ):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.question = question
        self.context = self.get_formatted_context(plans)
        self.tools = self.get_formatted_tools(tools)
        self.evaluation = self.get_formatted_evaluation(evaluation)
        self.contradictions = (
            self.get_formatted_contradictions(contradictions) if contradictions else ""
        )
        self.system_prompt = f"""
You are the Research Task Agent in an autonomous investigation system.
Today's date is {self.date}.

The research objective has already been planned. Your responsibility is to plan the
tool use: turn the objective into concrete, executable research tasks with exact
tool calls. You do not run them — a separate executor will execute the calls you
specify.

You do NOT:
- re-plan the investigation or change the objective you were given
- answer the investigation question yourself
- interpret results or decide what evidence means
- judge, rank, or update hypotheses
- invent tools that are not listed as available
- execute anything — a separate executor runs the calls you specify

You DO:
- emit one task per tool call; split broad objectives into multiple tasks
- reference the ID of the plan each task executes
- select the most appropriate tool from the available tools only
- produce exact, valid parameter values that match the tool's signature
- formulate precise search queries instead of copying the question verbatim
- keep each call focused on a single intent
- include time qualifiers (e.g. the current year, "latest") when recency matters
- prefer primary or high-quality sources (filings, official statistics, reputable
  news)
- design queries that could realistically surface the supporting OR weakening
  results described in the plan — the goal is evidence that discriminates between
  hypotheses, not evidence that merely confirms the leading one

Parameters:
- parameters = the full content of the tool call, matching the tool's signature
  (e.g. query, topic, max_results)
- emit parameters as a JSON-encoded object string, e.g.
  "{{\"query\": \"nvidia q2 revenue\", \"max_results\": 5}}"
- do not add any other top-level keys to the task — only the fields in the schema

If a plan cannot be executed with the available tools, skip it rather than forcing
an unsuitable tool call.

If evaluation feedback from a previous evidence round is provided, generate
tasks that address it.

If contradictions for previous hypotheses from a previous evidence round is provided, propose
research actions that uses those contradictions as signal for your planning.

Return only the requested structured output.
"""
        self.user_prompt = f"""
INVESTIGATION QUESTION
{self.question}


RESEARCH PLANS
{self.context}


AVAILABLE TOOLS
{self.tools}


EVALUATION FEEDBACK FROM PREVIOUS EVIDENCE
{self.evaluation}

CONTRADICTIONS FROM PREVIOUS EVIDENCE
{self.contradictions}

Produce the research tasks needed to execute the plans above.
"""
        logger.debug(f"User Prompt for TaskAgent:\n{self.user_prompt}")

    def get_formatted_context(self, plans):
        """Render the planner output this task should execute."""
        if not plans:
            return "No research plans provided."
        items = plans if isinstance(plans, list) else [plans]
        result = ""
        for p in items:
            if isinstance(p, BaseModel):
                for key, value in p.model_dump().items():
                    result += f"{key}: {value}\n"
            else:
                result += f"{p}\n"
            result += "\n"
        return result.strip()

    def get_formatted_tools(self, tool):
        """Render the available tools with their signatures so the agent can emit valid parameters."""
        if not tool:
            return "No tools are available for this task."
        tools = tool if isinstance(tool, list) else [tool]
        result = ""
        for t in tools:
            name = getattr(t, "tool_name", None) or getattr(t, "name", str(t))
            try:
                schema = (
                    t.schema()
                    if callable(getattr(t, "schema", None))
                    else getattr(t, "parameters", "unavailable")
                )
            except Exception:
                schema = "unavailable"
            result += f"Tool: {name}\nSignature/Parameters: {schema}\n\n"
        return result.strip()

    def get_formatted_evaluation(self, evaluation):
        """Render feedback from a previous evidence evaluation, if any."""
        if not evaluation:
            return "No prior evaluation — this is the first research round."
        if isinstance(evaluation, BaseModel):
            evaluation = evaluation.model_dump()
        if isinstance(evaluation, dict):
            return "\n".join(f"{key}: {value}" for key, value in evaluation.items())
        return str(evaluation)

    def get_formatted_contradictions(self, cs):
        """Render contradictions as readable text. Accepts a
        ManyContradictionsAgSchema or the investigator's list of
        ContradictionAgent objects (each result dict lives on the agent's
        .decision attribute)."""
        if not cs:
            return "No contradictions from previous rounds."
        entries = (
            cs.contradictions
            if isinstance(cs, ManyContradictionsAgSchema)
            else (cs if isinstance(cs, list) else [cs])
        )
        result = ""
        for c in entries:
            data = getattr(c, "decision", c)
            if isinstance(data, BaseModel):
                data = data.model_dump()
            if not isinstance(data, dict):
                result += f"{data}\n\n"
                continue
            if not data.get("contradiction_found"):
                continue
            result += (
                f"Hypothesis ID: {data.get('hypotheses_id')}\n"
                f"Contradiction Type: {data.get('contradiction_type')}\n"
                f"Contradiction: {data.get('contradiction')}\n"
                f"Evidence IDs: {data.get('evidence_ids')}\n"
                f"Alternate Hypothesis: {data.get('alternative_hypothesis')}\n"
                f"Severity: {data.get('severity')}\n"
                f"Recommended Followup: {data.get('recommended_followup')}\n\n"
            )
        return result.strip() or "No contradictions from previous rounds."


class DecisionAgPrompt(PromptClass):
    def __init__(
        self,
        question,
        clarification=None,
        hypothesis=None,
        plans=None,
        tasks=None,
        evidence=None,
        evaluation=None,
    ):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.question = question
        self.clarification = clarification or "No clarification provided."
        self.hypothesis = self.get_formatted_hypotheses(hypothesis)
        self.plans = self.get_formatted_items(plans)
        self.tasks = self.get_formatted_items(tasks)
        self.evidence = self.get_formatted_items(evidence)
        self.evaluation = self.get_formatted_items(evaluation)
        self.system_prompt = f"""
You are the Decision Agent in an autonomous investigation system.
Today's date is {self.date}.

The investigation has gathered evidence by executing research tasks. A separate
evaluator has judged each evidence item's relevance and impact, and the harness
has already updated hypothesis confidences and plan statuses accordingly. Your
job is to decide what happens NEXT. You do not gather evidence, evaluate it, or
update hypotheses — the step you spawn does that based on your decision.

You DO:
- decide the next step of the investigation based on the gathered evidence,
  the evaluation, and current hypothesis confidence
- choose exactly one action:
  - CHALLENGE: spawn the Contradiction Agent to search for counterevidence
    against the LEADING hypothesis. Choose when a hypothesis leads but has
    not been stress-tested yet.
  - REFINE_PLAN: spawn the Research Planner to create new research plans.
    Choose when evidence contradicted current beliefs or no ACTIVE plans
    remain. Existing plans are immutable and kept for history — new plans
    are appended, old objectives are never rewritten.
  - REASSESS: spawn the Research Task Agent to define new tasks for the
    existing, still-ACTIVE plans. Choose when the objective is unchanged but
    the evidence gathered so far was insufficient or low quality.
  - FINISH: stop the investigation and finalize the results into a
    human-consumable report. Choose when hypothesis confidence is high
    enough, evidence is sufficient, or further research shows diminishing
    returns.
- give concrete, actionable FEEDBACK for the agent you spawn: what to target,
  why this decision was made, which angles were not covered
- select the hypotheses (focus_hypotheses) the next step should concentrate
  on — select only, never update them

You do NOT:
- answer the investigation question
- invent evidence that was not gathered
- update, re-rank, or re-score hypotheses
- treat hypotheses as facts

Return only the requested structured output.
"""
        self.user_prompt = f"""
INVESTIGATION QUESTION
{self.question}


USER CLARIFICATION
{self.clarification}


HYPOTHESES
{self.hypothesis}


RESEARCH PLANS
{self.plans}


EXECUTED TASKS
{self.tasks}


GATHERED EVIDENCE
{self.evidence}

EVALUATION 
{self.evaluation}

"""
        logger.debug(f"User Prompt for DecisionAgent:\n{self.user_prompt}")

    def get_formatted_items(self, items):
        """Render plans/tasks/evidence (BaseModel, dict or str) as readable text."""
        if not items:
            return "None provided."
        entries = items if isinstance(items, list) else [items]
        result = ""
        for item in entries:
            if isinstance(item, BaseModel):
                item = item.model_dump()
            if isinstance(item, dict):
                for key, value in item.items():
                    result += f"{key}: {value}\n"
            else:
                result += f"{item}\n"
            result += "\n"
        return result.strip()

    def get_formatted_hypotheses(self, hypotheses):
        """Render hypotheses with confidence and their supporting/weakening predictions."""
        if not hypotheses:
            return "No hypotheses provided."
        entries = hypotheses if isinstance(hypotheses, list) else [hypotheses]
        result = ""
        for h in entries:
            result += (
                f"ID: {h.id}\nHypothesis: {h.hypothesis}\nConfidence: {h.confidence}\n"
            )
            for e in getattr(h, "supporting_predictions", []):
                result += f"  Supporting prediction: {e}\n"
            for e in getattr(h, "weakening_predictions", []):
                result += f"  Weakening prediction: {e}\n"
            result += "\n"
        return result.strip()


class EvidenceEvaluatorAgPrompt(PromptClass):
    def __init__(
        self,
        question,
        clarification=None,
        hypothesis=None,
        plans=None,
        tasks=None,
        evidence=None,
    ):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.question = question
        self.clarification = clarification or "No clarification provided."
        self.hypothesis = self.get_formatted_hypotheses(hypothesis)
        self.plans = self.get_formatted_items(plans)
        self.tasks = self.get_formatted_items(tasks)
        self.evidence = self.get_formatted_items(evidence)
        self.system_prompt = f"""
You are the Evidence Evaluator Agent in an autonomous investigation system.
Today's date is {self.date}.

The investigation has gathered evidence by executing research tasks. Your
responsibility is to judge the quality and usefulness of that evidence. You do
not gather new evidence and you do not update hypotheses — separate steps do
that based on your evaluation.

You DO:
- evaluate EACH piece of evidence independently: one evaluation per evidence
  item, identified by its ID (the ID of the task that produced it)
- judge RELEVANCE of each item: does it actually address the investigation
  question and the expectations stated in the research plans?
- judge IMPACT of each relevant item PER HYPOTHESIS (hypothesis_impacts):
  emit one entry for each hypothesis the item genuinely affects — and only
  those. Hypotheses you do not list receive no confidence change. Per
  hypothesis, decide:
  - supporting: this item strengthens this hypothesis
  - weakening: this item reduces confidence in this hypothesis
  - contradictory: this item directly conflicts with this hypothesis — an
    alternative explanation must be investigated
  - neutral: listed for completeness, but changes nothing
  The same evidence item may support one hypothesis and weaken another —
  never let a single overall judgement bleed onto hypotheses it does not
  actually address.
- set the item-level evidence_impact to the STRONGEST of the per-hypothesis
  impacts (contradictory > weakening > supporting > neutral); neutral means
  relevant but insufficient to change confidence in any hypothesis
- give concrete, actionable FEEDBACK for the next iteration, aggregated across
  all items: what is still missing, what should be searched next, which angles
  were not covered

You do NOT:
- answer the investigation question
- update, rank, or select hypotheses
- invent evidence that was not gathered
- treat hypotheses as facts

Be strict: evidence that does not help distinguish between hypotheses is not
high impact, even if it is topically related.

Return only the requested structured output.
"""
        self.user_prompt = f"""
INVESTIGATION QUESTION
{self.question}


USER CLARIFICATION
{self.clarification}


HYPOTHESES
{self.hypothesis}


RESEARCH PLANS
{self.plans}


EXECUTED TASKS
{self.tasks}


GATHERED EVIDENCE
{self.evidence}


Evaluate each piece of gathered evidence independently — one evaluation per
evidence item — and provide aggregated feedback for the next research
iteration.
"""
        logger.debug(f"User Prompt for EvidenceEvaluatorAgent:\n{self.user_prompt}")

    def get_formatted_items(self, items):
        """Render plans/tasks/evidence (BaseModel, dict or str) as readable text."""
        if not items:
            return "None provided."
        entries = items if isinstance(items, list) else [items]
        result = ""
        for item in entries:
            if isinstance(item, BaseModel):
                item = item.model_dump()
            if isinstance(item, dict):
                for key, value in item.items():
                    result += f"{key}: {value}\n"
            else:
                result += f"{item}\n"
            result += "\n"
        return result.strip()

    def get_formatted_hypotheses(self, hypotheses):
        """Render hypotheses with confidence and their supporting/weakening predictions."""
        if not hypotheses:
            return "No hypotheses provided."
        entries = hypotheses if isinstance(hypotheses, list) else [hypotheses]
        result = ""
        for h in entries:
            result += (
                f"ID: {h.id}\nHypothesis: {h.hypothesis}\nConfidence: {h.confidence}\n"
            )
            for e in getattr(h, "supporting_predictions", []):
                result += f"  Supporting prediction: {e}\n"
            for e in getattr(h, "weakening_predictions", []):
                result += f"  Weakening prediction: {e}\n"
            result += "\n"
        return result.strip()


class ReportAgPrompt(PromptClass):
    def __init__(
        self,
        question,
        clarification=None,
        hypothesis=None,
        plans=None,
        tasks=None,
        evidence=None,
        evaluation=None,
        contradictions=None,
    ):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.question = question
        self.clarification = clarification or "No clarification provided."
        self.hypothesis = self.get_formatted_hypotheses(hypothesis)
        self.plans = self.get_formatted_items(plans)
        self.tasks = self.get_formatted_items(tasks)
        self.evidence = self.get_formatted_items(evidence)
        self.evaluation = self.get_formatted_items(evaluation)
        self.contradictions = self.get_formatted_contradictions(contradictions)
        self.citable_ids = self.get_citable_ids(evidence)
        self.system_prompt = f"""
You are the Report Agent in an autonomous investigation system.
Today's date is {self.date}.

The investigation has FINISHED. Your responsibility is to synthesize its final
state into a thesis-style markdown report for a human reader. You are the last
step of the pipeline: hypotheses have been generated, research executed,
evidence evaluated, confidences updated and contradictions sought.

You DO:
- write the report sections defined by the output schema: title, abstract,
  introduction, one discussion entry per hypothesis (including the REJECTED
  ones), alternative hypotheses raised by the contradiction step, an evidence
  section, and a short conclusion
- ground every factual claim in the gathered evidence and cite it inline using
  the evidence IDs (e.g. [RT-001]). Only cite IDs from the CITABLE EVIDENCE IDS
  list — a separate step renders the reference list, so never invent sources,
  URLs, or citation markers
- refer to hypotheses as H<id> (e.g. H1, H2)
- assign each hypothesis a verdict consistent with its final confidence and the
  evidence impacts: high final confidence with supporting evidence ->
  supported; contradicted or collapsed confidence -> rejected; reduced but
  surviving confidence -> weakened; insufficient evidence either way ->
  inconclusive
- scale the report's length to the complexity of the topic and the amount of
  evidence: a narrow question with few evidence items deserves a few hundred
  words; a multi-hypothesis investigation with many evidence items deserves
  more. Never pad. As a guide: abstract <= 150 words, conclusion <= 100 words,
  everything else only as long as the evidence supports.

You do NOT:
- gather new evidence or invent evidence that was not gathered
- change hypothesis confidences or introduce new hypotheses outside the
  alternate_hypotheses section
- write a literature-review-length document — this is a focused thesis, not a
  100-page paper
- dump raw tool output — interpret and synthesize it

Return only the requested structured output.
"""
        self.user_prompt = f"""
INVESTIGATION QUESTION
{self.question}


USER CLARIFICATION
{self.clarification}


HYPOTHESES (with final confidence)
{self.hypothesis}


RESEARCH PLANS
{self.plans}


EXECUTED TASKS
{self.tasks}


GATHERED EVIDENCE
{self.evidence}


EVALUATION
{self.evaluation}


CONTRADICTIONS
{self.contradictions}


CITABLE EVIDENCE IDS
{self.citable_ids}


Write the final investigation report.
"""
        logger.debug(f"User Prompt for ReportAgent:\n{self.user_prompt}")

    def get_citable_ids(self, evidence):
        """List the evidence IDs the agent is allowed to cite inline."""
        if not evidence:
            return "No evidence was gathered — no citations are possible."
        entries = evidence if isinstance(evidence, list) else [evidence]
        ids = []
        for item in entries:
            if isinstance(item, BaseModel):
                item = item.model_dump()
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
        return "\n".join(f"- [{i}]" for i in ids) if ids else "None."

    def get_formatted_contradictions(self, contradictions):
        """Render contradictions — the source of rejected and alternate hypotheses."""
        if not contradictions:
            return "No contradictions were raised."
        result = ""
        entries = (
            contradictions if isinstance(contradictions, list) else [contradictions]
        )
        for c in entries:
            # investigator stores ContradictionAgent instances; their result
            # dict lives on .decision
            data = getattr(c, "decision", c)
            if isinstance(data, BaseModel):
                data = data.model_dump()
            if isinstance(data, dict):
                for key, value in data.items():
                    result += f"{key}: {value}\n"
            else:
                result += f"{data}\n"
            result += "\n"
        return result.strip() or "No contradictions were raised."

    def get_formatted_items(self, items):
        """Render plans/tasks/evidence/evaluation (BaseModel, dict or str) as readable text."""
        if not items:
            return "None provided."
        entries = items if isinstance(items, list) else [items]
        result = ""
        for item in entries:
            if isinstance(item, BaseModel):
                item = item.model_dump()
            if isinstance(item, dict):
                for key, value in item.items():
                    result += f"{key}: {value}\n"
            else:
                result += f"{item}\n"
            result += "\n"
        return result.strip()

    def get_formatted_hypotheses(self, hypotheses):
        """Render hypotheses with final confidence, its history and predictions."""
        if not hypotheses:
            return "No hypotheses provided."
        entries = hypotheses if isinstance(hypotheses, list) else [hypotheses]
        result = ""
        for h in entries:
            result += (
                f"ID: {h.id}\nHypothesis: {h.hypothesis}\nFinal confidence: {h.confidence}\n"
            )
            history = getattr(h, "confidence_history", [])
            if history:
                result += f"Confidence history: {history}\n"
            for e in getattr(h, "supporting_predictions", []):
                result += f"  Supporting prediction: {e}\n"
            for e in getattr(h, "weakening_predictions", []):
                result += f"  Weakening prediction: {e}\n"
            result += "\n"
        return result.strip()


class ContradictionAgPrompt(PromptClass):
    def __init__(
        self,
        question,
        clarification=None,
        hypothesis=None,
        hypothesis_id=None,
        plans=None,
        tasks=None,
        evidence=None,
        evaluation=None,
    ):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.question = question
        self.clarification = clarification or "No clarification provided."
        self.hypothesis = self.get_formatted_hypotheses(hypothesis)
        self.hypothesis_id = hypothesis_id
        self.plans = self.get_formatted_items(plans)
        self.tasks = self.get_formatted_items(tasks)
        self.evidence = self.get_formatted_items(evidence)
        self.evaluation = self.get_formatted_items(evaluation)
        self.system_prompt = f"""
You are the Contradiction Agent in an autonomous investigation system.
Today's date is {self.date}.

Your purpose is to actively challenge ONE hypothesis provided by the user.

You are NOT trying to confirm the current conclusion.
You are NOT trying to produce the final report.
You are NOT trying to maximize the amount of conflicting
evidence.

You should identify the strongest plausible reason that the
provided hypothesis may be wrong, incomplete, overstated, or
based on insufficient evidence.

Inspect:
- the provided hypotheses/hypothesis-id and confidence
- supporting and weakening predictions
- collected evidence
- evidence provenance
- previous contradictions
- research history

Look especially for:

1. Direct contradictions:
   Evidence that conflicts with the hypothesis.

2. Missing expected evidence:
   The hypothesis predicts something important, but the
   investigation failed to find it.

3. Alternative explanations:
   A different hypothesis explains the same evidence better.

4. Temporal problems:
   The proposed cause occurs after the supposed effect.

5. Scope problems:
   Evidence supports a broader or narrower claim than
   the hypothesis makes.

6. Source dependence:
   Apparently independent evidence actually comes from the
   same source or underlying claim.

7. Measurement problems:
   The evidence does not adequately measure the phenomenon
   described by the hypothesis.

Prefer strong, specific contradictions over a large number
of weak objections.

Do not invent evidence.

Only reference evidence that exists in the investigation state.

If no meaningful contradiction exists, explicitly state that
no contradiction was found.

Return only the structured output.
"""
        self.user_prompt = f"""
INVESTIGATION QUESTION
{self.question}


USER CLARIFICATION
{self.clarification}

HYPOTHESIS ID TO TARGET
{self.hypothesis_id}

ALL HYPOTHESES
{self.hypothesis}


RESEARCH PLANS
{self.plans}


EXECUTED TASKS
{self.tasks}


GATHERED EVIDENCE
{self.evidence}

EVALUATION 
{self.evaluation}

"""
        logger.debug(f"User Prompt for ContradictionAgent:\n{self.user_prompt}")

    def get_formatted_items(self, items):
        """Render plans/tasks/evidence (BaseModel, dict or str) as readable text."""
        if not items:
            return "None provided."
        entries = items if isinstance(items, list) else [items]
        result = ""
        for item in entries:
            if isinstance(item, BaseModel):
                item = item.model_dump()
            if isinstance(item, dict):
                for key, value in item.items():
                    result += f"{key}: {value}\n"
            else:
                result += f"{item}\n"
            result += "\n"
        return result.strip()

    def get_formatted_hypotheses(self, hypotheses):
        """Render hypotheses with confidence and their supporting/weakening predictions."""
        if not hypotheses:
            return "No hypotheses provided."
        entries = hypotheses if isinstance(hypotheses, list) else [hypotheses]
        result = ""
        for h in entries:
            result += (
                f"ID: {h.id}\nHypothesis: {h.hypothesis}\nConfidence: {h.confidence}\n"
            )
            for e in getattr(h, "supporting_predictions", []):
                result += f"  Supporting prediction: {e}\n"
            for e in getattr(h, "weakening_predictions", []):
                result += f"  Weakening prediction: {e}\n"
            result += "\n"
        return result.strip()
