from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, Json


class StrictSchema(BaseModel):
    # extra="forbid" makes pydantic emit "additionalProperties": false in the
    # JSON schema — required by strict structured-output endpoints — and also
    # rejects unexpected keys when validating model output.
    model_config = ConfigDict(extra="forbid")


class QuestionAnalysisAgSchema(StrictSchema):
    reasoning: str = Field(
        default="",
        description="Scratchpad: think step by step here FIRST — analyze the input, weigh options — before producing the structured output below. Keep it brief (a few sentences at most).",
    )
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


class HypothesisAgSchema(StrictSchema):
    id: int = Field(..., ge=1, description="Integer ID to identify this hypothesis")
    hypothesis: str = Field(
        ..., description="A single hypothesis that could explain the phenomenon"
    )
    confidence: float = Field(
        ...,
        description="Prior confidence before verifying the statement.",
        ge=0,
        le=1,
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


class ManyHypothesesAgSchema(StrictSchema):
    reasoning: str = Field(
        default="",
        description="Scratchpad: think step by step here FIRST — analyze the input, weigh options — before producing the structured output below. Keep it brief (a few sentences at most).",
    )
    hypotheses: list[HypothesisAgSchema] = Field(
        default_factory=list,
        min_length=1,
        description="A list of hypotheses that could explain the phenomenon",
    )


class ToolSchema(StrictSchema):
    name: str = Field(..., description="Name of the tool")
    parameters: dict = Field(
        default_factory=dict,
        description="All parameters that should be passed to the tool, based on the tool signature",
    )


class ResearchPlannerAgSchema(StrictSchema):
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


class ManyResearchPlannerAgSchema(StrictSchema):
    reasoning: str = Field(
        default="",
        description="Scratchpad: think step by step here FIRST — analyze the input, weigh options — before producing the structured output below. Keep it brief (a few sentences at most).",
    )
    plans: list[ResearchPlannerAgSchema] = Field(
        default_factory=list,
        min_length=1,
        description="List of research plans to deep dive into.",
    )


class ResearchTaskAgSchema(StrictSchema):
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
    parameters: Json[dict] = Field(
        default_factory=dict,
        description='Exact parameter values for the tool call, matching the tool\'s signature, encoded as a JSON object string (e.g. \'{"query": "nvidia revenue", "max_results": 5}\')',
    )
    result: dict = Field(
        default={},
        description="Result after executing this task. Populated by the harness, never sent to the LLM.",
        json_schema_extra={"harness_only": True},
    )


class ManyResearchTaskAgSchema(StrictSchema):
    reasoning: str = Field(
        default="",
        description="Scratchpad: think step by step here FIRST — analyze the input, weigh options — before producing the structured output below. Keep it brief (a few sentences at most).",
    )
    tasks: list[ResearchTaskAgSchema] = Field(
        default_factory=list,
        min_length=1,
        description="""A list of tool-use tasks that execute the research plans. The research task is an executable decomposition of research plans.
        Each tool use needs a full task definition (ie, a single Research Plan/RP ID per research tool/task is required)""",
    )


class HypothesisImpactAgSchema(StrictSchema):
    hypothesis_id: int = Field(
        ...,
        ge=1,
        description="ID of the hypothesis this evidence item affects",
    )
    impact: Literal["supporting", "weakening", "contradictory", "neutral"] = Field(
        default="neutral",
        description="What this evidence item does to THIS hypothesis specifically: supporting = strengthens it; weakening = reduces confidence in it; contradictory = directly conflicts with it; neutral = no confidence change",
    )
    reasoning: str = Field(
        default="",
        description="How this evidence item affects this specific hypothesis",
    )


class SingleEvidenceEvaluationAgSchema(StrictSchema):
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
    hypothesis_impacts: list[HypothesisImpactAgSchema] = Field(
        default_factory=list,
        description="One entry per hypothesis this evidence item actually affects. Only hypotheses with a genuine, evidence-backed impact may be listed — hypotheses not listed here get no confidence change. Empty if the evidence changes nothing.",
    )
    evidence_impact: Literal["supporting", "weakening", "contradictory", "neutral"] = (
        Field(
            default="neutral",
            description="Aggregate of hypothesis_impacts — the strongest impact among them (contradictory > weakening > supporting > neutral). supporting = strengthens at least one hypothesis; weakening = reduces confidence in at least one hypothesis; contradictory = directly conflicts with a hypothesis, an alternative must be investigated; neutral = relevant but insufficient to change confidence in any hypothesis",
        )
    )
    impact_reasoning: str = Field(
        default="",
        description="Summary of which hypotheses this evidence item affects, and how",
    )


class EvidenceEvaluationAgSchema(StrictSchema):
    reasoning: str = Field(
        default="",
        description="Scratchpad: think step by step here FIRST — analyze the input, weigh options — before producing the structured output below. Keep it brief (a few sentences at most).",
    )
    evaluations: list[SingleEvidenceEvaluationAgSchema] = Field(
        default_factory=list,
        min_length=1,
        description="One independent evaluation per evidence item provided",
    )
    feedback: str = Field(
        default="",
        description="Actionable feedback for the next iteration, aggregated across all evidence: what is still missing and what new plans or tasks should target",
    )


class DecisionAgSchema(StrictSchema):
    reasoning: str = Field(
        default="",
        description="Scratchpad: think step by step here FIRST — analyze the input, weigh options — before producing the structured output below. Keep it brief (a few sentences at most).",
    )
    decision: Literal["CHALLENGE", "REFINE_PLAN", "REASSESS", "FINISH"] = Field(
        default="FINISH",
        description="The next step of the investigation. CHALLENGE = stress-test the leading hypothesis; REFINE_PLAN = new research plans (objective changed); REASSESS = new tasks for existing ACTIVE plans; FINISH = stop and report. Defaults to FINISH as the safe fallback.",
    )
    feedback: str = Field(
        default="",
        description="Actionable input for the spawned agent: what to target, why, which angles were not covered",
    )
    focus_hypotheses: list[int] = Field(
        default_factory=list,
        description="IDs of the hypotheses the next step should concentrate on",
    )


class ContradictionAgSchema(StrictSchema):
    hypotheses_id: str = Field(
        default="",
        description="Which of the hypothesis is targetted by this action (Use one hypothesis ID: 1, 2, etc)",
    )
    contradiction_found: bool = Field(
        default=False, description="Whether a contradction was found."
    )
    contradiction_type: Literal[
        "NOT_APPLICABLE",
        "DIRECT_CONTRADICTION",
        "MISSING_EXPECTED_EVIDENCE",
        "ALTERNATIVE_EXPLANATION",
        "SOURCE_DEPENDENCE",
        "TEMPORAL_MISMATCH",
        "SCOPE_MISMATCH",
    ] = Field(
        default="NOT_APPLICABLE",
        description="When a contradiction was found, what type of contradiction is it?",
    )
    contradiction: str = Field(
        default="",
        description="The exact contradiction that could be used to reject the hypothesis. The strongest possible alternative explanation that would reduce confidence in the leading hypothesis.",
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="The reference to the specific evidence IDs that this hypothesis targets and now, contradicts.",
    )
    alternative_hypothesis: str = Field(
        default="",
        description="Alternative hypothesis that could be valid, that would strongly reject the provided hypothesis.",
    )
    severity: Literal[
        "LOW",
        "MEDIUM",
        "HIGH",
        "NOT_APPLICABLE",
    ] = Field(default="NOT_APPLICABLE", description="How strong is the contradiction")
    recommended_followup: str = Field(
        default="",
        description="""
        What evidence is further needed to support the contradiction or as a 
        general followup, what action should the agent take that would further the contradiction.
        """,
    )


class ManyContradictionsAgSchema(StrictSchema):
    contradictions: list[ContradictionAgSchema] = Field(
        default_factory=list,
        min_length=1,
        description="A collection of contradictions, gathered per hypothesis",
    )


class ReportHypothesisAgSchema(StrictSchema):
    hypothesis_id: int = Field(
        ...,
        ge=1,
        description="ID of the investigated hypothesis this entry discusses",
    )
    verdict: Literal["supported", "weakened", "rejected", "inconclusive"] = Field(
        ...,
        description="Final verdict for this hypothesis based on its final confidence and the evidence: supported = evidence strengthened it; weakened = evidence reduced confidence but did not kill it; rejected = contradicted/invalidated by evidence; inconclusive = evidence insufficient to decide",
    )
    discussion: str = Field(
        ...,
        description="Markdown discussion of this hypothesis and its verdict. Cite the evidence that backs the verdict inline using the evidence IDs, e.g. [RT-001].",
    )


class ReportAlternateHypothesisAgSchema(StrictSchema):
    statement: str = Field(
        ...,
        description="Statement of the alternative hypothesis that emerged during the investigation (typically from the contradiction step)",
    )
    replaces_hypothesis_id: int = Field(
        ...,
        ge=1,
        description="ID of the original hypothesis this alternative challenges or replaces",
    )
    discussion: str = Field(
        ...,
        description="Markdown discussion of why this alternative is plausible. Cite evidence inline using the evidence IDs, e.g. [RT-001].",
    )


class ReportAgSchema(StrictSchema):
    reasoning: str = Field(
        default="",
        description="Scratchpad: think step by step here FIRST — analyze the input, weigh options — before producing the structured output below. Keep it brief (a few sentences at most).",
    )
    title: str = Field(
        default="",
        description="Short thesis-style title for the investigation report",
    )
    abstract: str = Field(
        default="",
        description="Abstract of the report: the question, the approach, the main finding and the remaining uncertainty. At most ~150 words.",
    )
    introduction: str = Field(
        default="",
        description="Markdown introduction: context of the question, why it matters, and what the investigation set out to test — grounded in the gathered evidence. Cite evidence inline using the evidence IDs, e.g. [RT-001].",
    )
    hypotheses: list[ReportHypothesisAgSchema] = Field(
        default_factory=list,
        min_length=1,
        description="One discussion entry per investigated hypothesis, covering ALL of them — including the ones that were rejected",
    )
    alternate_hypotheses: list[ReportAlternateHypothesisAgSchema] = Field(
        default_factory=list,
        description="Alternative hypotheses that emerged from the contradiction step. Empty if none were raised.",
    )
    evidence: str = Field(
        default="",
        description="Markdown evidence section: what was actually found, organized by theme or hypothesis — not a raw dump. Every factual claim must carry an inline citation to an evidence ID, e.g. [RT-001].",
    )
    conclusion: str = Field(
        default="",
        description="Short markdown conclusion: the surviving explanation, the confidence in it, and what remains unresolved. At most ~100 words.",
    )
