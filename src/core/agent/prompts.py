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


class HypothesisAgPrompt(PromptClass):
    def __init__(self, input_text):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
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
        self.user_prompt = f"Input: {input_text}\n\nPlease generate hypotheses based on the above input."


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


KNOWN GAPS
(Your task to identify)
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
                    f"Supporting Statement {idx} for Hypothesis {h.id}: {e}"
                )
            weakening_predictions = ""
            for idx, e in enumerate(h.weakening_predictions):
                weakening_predictions += (
                    f"Weakening Statement {idx} for Hypothesis {h.id}: {e}"
                )
            # now append that string to result
            result += f"Predicted Evidence for Hypothesis {h.id}\n{supporting_predictions}\n{weakening_predictions}\n"

        return result


class ResearchTaskAgPrompt(PromptClass):
    def __init__(self, question, hypothesis=None, tools=None):
        super().__init__()
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.question = question
        self.context = self.get_formatted_context(hypothesis)
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


RESEARCH PLANS AND HYPOTHESES
{self.context}


AVAILABLE TOOLS
{self.tools}

Produce the research tasks needed to execute the plans above.
"""
        logger.debug(f"User Prompt for TaskAgent:\n{self.user_prompt}")

    def get_formatted_context(self, hypothesis):
        """Render the hypotheses / planner output this task should serve."""
        if not hypothesis:
            return "No hypotheses or plan provided."
        items = hypothesis if isinstance(hypothesis, list) else [hypothesis]
        result = ""
        for h in items:
            if isinstance(h, BaseModel):
                for key, value in h.model_dump().items():
                    result += f"{key}: {value}\n"
            else:
                result += f"{h}\n"
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
