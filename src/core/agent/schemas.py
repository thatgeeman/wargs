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
    confidence_history: list[float] = Field(
        default_factory=list,
        description="Confidence values over time, updated by the harness as evidence arrives. Leave empty when generating.",
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
        min_length=1,
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
    status: Literal["ACTIVE", "WEAKENED", "INVALIDATED", "COMPLETED"] = Field(
        default="ACTIVE",
        description="Lifecycle status of the plan. Always 'ACTIVE' for newly proposed plans; transitions (WEAKENED / INVALIDATED / COMPLETED) are applied by the harness based on evidence, never by rewriting the plan's objective",
    )


class ManyResearchPlannerAgSchema(BaseModel):
    plans: list[ResearchPlannerAgSchema] = Field(
        default_factory=list,
        min_length=1,
        description="List of research plans to deep dive into.",
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
        min_length=1,
        description="""A list of tool-use tasks that execute the research plans. The research task is an executable decomposition of research plans.
        Each tool use needs a full task definition (ie, a single Research Plan/RP ID per research tool/task is required)""",
    )


class SingleEvidenceEvaluationAgSchema(BaseModel):
    evidence_id: str = Field(
        default="",
        description="ID of the evidence item being evaluated (the ID of the task that produced it, e.g. 'RT-001')",
    )
    evidence_relevant: bool = Field(
        default=False,
        description="True if this evidence item actually addresses the investigation question and the expectations stated in the research plans",
    )
    relevance_reasoning: str = Field(
        default="",
        description="Why this evidence item is or is not relevant to the question and plans",
    )
    evidence_impact: Literal["supporting", "weakening", "contradictory", "neutral"] = Field(
        default="neutral",
        description="What this evidence item does to current beliefs: supporting = strengthens at least one hypothesis; weakening = reduces confidence in at least one hypothesis; contradictory = directly conflicts with a hypothesis, an alternative must be investigated; neutral = relevant but insufficient to change confidence in any hypothesis",
    )
    impact_reasoning: str = Field(
        default="",
        description="Which hypotheses this evidence item affects, and how",
    )


class EvidenceEvaluationAgSchema(BaseModel):
    evaluations: list[SingleEvidenceEvaluationAgSchema] = Field(
        default_factory=list,
        min_length=1,
        description="One independent evaluation per evidence item provided",
    )
    feedback: str = Field(
        default="",
        description="Actionable feedback for the next iteration, aggregated across all evidence: what is still missing and what new plans or tasks should target",
    )
