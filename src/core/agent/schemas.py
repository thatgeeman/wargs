from typing import Literal

from pydantic import BaseModel, Field


class QuestionAnalysisAgSchema(BaseModel):
    investigation_type: str = Field(
        default="",
        description="The kind of investigation the question requires (e.g. comparative evaluation, causal explanation, fact verification, trend analysis)",
    )
    explicit_subject: str = Field(
        default="", description="The subject explicitly named in the question"
    )
    implicit_comparison: str = Field(
        default="",
        description="Implicit comparison targets or assumptions the question relies on without stating them (e.g. 'other companies'). Empty if none.",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Missing information needed to investigate rigorously (e.g. definitions, evaluation criteria, time period, geographic scope)",
    )
    investigation_status: Literal["CLEAR", "NEEDS_CLARIFICATION"] = Field(
        default="CLEAR",
        description="CLEAR if the question can be investigated as-is; NEEDS_CLARIFICATION if missing information would materially change the investigation",
    )
    followup_question: str = Field(
        default="",
        description="A single concise follow-up question asking the user for the most critical missing information. Only filled when investigation_status is NEEDS_CLARIFICATION; empty otherwise.",
    )


class HypothesisAgSchema(BaseModel):
    id: int = Field(..., ge=1, description="Integer ID to identify this hypothesis")
    hypothesis: str = Field(
        ..., description="A single hypothesis that could explain the phenomenon"
    )
    confidence: float = Field(
        ..., description="Prior confidence before verifying the statement", ge=0, le=1
    )
    supporting_predictions: list[str] = Field(
        default_factory=list,
        description="Knowledge (expectations) that would support the hypothesis",
    )
    weakening_predictions: list[str] = Field(
        default_factory=list,
        description="Knowledge (expectations) that would weaken the hypothesis",
    )


class ManyHypothesesAgSchema(BaseModel):
    hypotheses: list[HypothesisAgSchema] = Field(
        default_factory=list,
        description="A list of hypotheses that could explain the phenomenon",
    )


class ToolSchema(BaseModel):
    name: str = Field(..., description="Name of the tool")
    parameters: dict = Field(
        default_factory=dict,
        description="All parameters that should be passed to the tool, based on the tool signature",
    )


class ResearchPlannerAgSchema(BaseModel):
    id: str = Field(
        ...,
        description="Unique identifier for this plan, formatted as 'RP-001', 'RP-002', ...",
    )
    plan: str = Field(
        ...,
        description="What exactly should we investigate and the objective of this plan.",
    )
    rationale: str = Field(..., description="Rationale for chosing this action")
    hypotheses_targeted: list[str] = Field(
        default_factory=list,
        description="Which of the hypotheses are targetted by this action (Use hypothesis IDs: [1, 2])",
    )
    supporting_result: str = Field(
        ...,
        description="What kind of evidence, if discovered, would make us more confident that this hypothesis is correct?",
    )
    weakening_result: str = Field(
        ...,
        description="What kind of evidence, if discovered, would make us less confident that this hypothesis is correct?",
    )
    priority: float = Field(..., ge=0, le=1)


class ManyResearchPlannerAgSchema(BaseModel):
    plans: list[ResearchPlannerAgSchema] = Field(
        default_factory=list, description="List of research plans to deep dive into."
    )


class ResearchTaskAgSchema(BaseModel):
    id: str = Field(
        ...,
        description="Unique identifier for this task execution (e.g. 'RT-001', 'RT-002')",
    )
    plan_id: str = Field(
        ..., description="ID of the research plan this task executes (e.g. 'RP-001')"
    )
    tool: str = Field(
        ..., description="Name of the tool to call. Must be one of the available tools."
    )
    parameters: dict = Field(
        default_factory=dict,
        description="Exact parameter values for the tool call, matching the tool's signature",
    )
    result: dict = Field(
        default={},
        description="Result after executing this task. Not to be filled by an LLM.",
    )


class ManyResearchTaskAgSchema(BaseModel):
    tasks: list[ResearchTaskAgSchema] = Field(
        default_factory=list,
        description="""A list of tool-use tasks that execute the research plans. The research task is an executable decomposition of research plans. 
        Each tool use needs a full task definition (ie, a single Research Plan/RP ID per research tool/task is required)""",
    )
