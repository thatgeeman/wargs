from datetime import datetime

from pydantic import BaseModel

from ...config import Config
from .schemas import (
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
- decide whether the question can be investigated as-is

Status rules:
- NEEDS_CLARIFICATION only when missing information would materially change the
  direction of the investigation. Do not be pedantic: gaps that research can
  resolve on its own are NOT a reason to ask the user.
- CLEAR when the question is specific enough to investigate meaningfully as-is.

Follow-up question rules:
- only formulate one when the status is NEEDS_CLARIFICATION; leave it empty
  otherwise
- ask ONE concise, natural-language question that resolves the most critical
  gaps — combine related gaps instead of interrogating the user with a list
  of separate questions
- phrase it so the user can answer in one or two sentences
  (e.g. "By 'greatest', do you mean revenue, market cap, or something else —
  and over what time period?")

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
    def __init__(self, question, hypothesis: ManyHypothesesAgSchema = []):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.question = question
        self.hypothesis = self.get_formatted_hypothesis(hypothesis)
        self.evidence = self.get_formatted_evidence(hypothesis)
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


class ResearchTaskAgPrompt(PromptClass):
    def __init__(self, question, plans=None, tools=None):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.question = question
        self.context = self.get_formatted_context(plans)
        self.tools = self.get_formatted_tools(tools)
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

Parameters vs constraints:
- parameters = the content of the tool call, matching the tool's signature
  (e.g. query, topic)
- constraints = execution limits for the executor to enforce (e.g. max_results)

If a plan cannot be executed with the available tools, skip it rather than forcing
an unsuitable tool call.

Return only the requested structured output.
"""
        self.user_prompt = f"""
INVESTIGATION QUESTION
{self.question}


RESEARCH PLANS
{self.context}


AVAILABLE TOOLS
{self.tools}

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
            name = getattr(t, "name", str(t))
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
