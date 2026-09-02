from pydantic import BaseModel, Field 

class HypothesisAgSchema(BaseModel): 
    hypothesis: str = Field(..., description="A single hypothesis that could explain the phenomenon")
    confidence: float = Field(..., ge=0, le=1)
    evidence: list[str] = Field(default_factory=list, description="Evidences that supports the hypothesis")

class ManyHypothesesAgSchema(BaseModel):
    hypotheses: list[HypothesisAgSchema] = Field(default_factory=list, description="A list of hypotheses that could explain the phenomenon")

class ToolSchema(BaseModel):
    tool: str = Field(..., description="Name of the tool")
    parameters: dict = Field(default_factory=dict, description="All parameters that should be passed to the tool, based on the tool signature")

class ResearchPlannerAgSchema(BaseModel): 
    action: str = Field(..., description="What exactly should we investigate?")
    rationale: str = Field(..., description="Rationale for chosing this action")
    hypotheses_targeted: list[str] = Field(default_factory=list, description="Which of the hypotheses are targetted by this action (Can provide multiple - use short forms: [H1, H2])")
    supporting_result:  str = Field(..., description="What kind of evidence, if discovered, would make us more confident that this hypothesis is correct?")
    weakening_result: str = Field(..., description="What kind of evidence, if discovered, would make us less confident that this hypothesis is correct?")
    priority: float = Field(..., ge=0, le=1)
    preferred_source_type: list[str] = Field(default_factory=list, description="What kind of sources would be best suited for this reasearch (news, code, etc)")
    tool_schema: list[ToolSchema] = Field(default_factory=list, description="The exact tools and corresponding schemas to use to perform this action")

class ManyResearchPlannerAgSchema(BaseModel):
    actions: list[ResearchPlannerAgSchema] = Field(default_factory=list, description="A list of actions that is part of the research plan.")