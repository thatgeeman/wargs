import uuid
from pydantic import BaseModel

from ..agent import HypothesisAgent, ManyHypothesesAgSchema, ManyResearchPlannerAgSchema, ResearchPlanner
from ...config import Config
from ...tools.store import WebSearch

cfg = Config()
logger = cfg.get_logger("InvestigatorLogger")

class InvestigationState:
    def __init__(self, question):
        self.id = str(uuid.uuid4())
        self.question = question
        self.state = "INIT"
        self.name = f"Investigation-{self.id}"
        self.hypotheses = []
        self.research_plans = []
        self.evidence = []
        self.contradictions = []
        self.events = []
        self.tools = [WebSearch()]
        self.current_step = 0
        self.max_steps = 10  # Default max steps, can be adjusted as needed
        logger.info(f"{self.name}: Initialized with question: {self.question}")

    def generate_hypotheses(self):
        # Placeholder for the main investigation logic
        if self.current_step >= self.max_steps:
            self.state = "COMPLETED"
            logger.info(f"{self.name}: Investigation {self.id} has reached the maximum number of steps.")
            return self.hypotheses
        hypothesis_agent = HypothesisAgent(self.question)
        try:
            ha: ManyHypothesesAgSchema = hypothesis_agent.run(True)
            self.state = 'HYPOTHESIS_GENERATED'
            self.hypotheses = ha.hypotheses
        except Exception as e:
            logger.error(f"{self.name}: Error occurred while running hypothesis agent: {e}")
            self.state = "ERROR"
        self.current_step += 1

    def research_planner(self):
        # Placeholder for the main investigation logic
        if self.current_step >= self.max_steps:
            self.state = "COMPLETED"
            logger.info(f"{self.name}: Investigation {self.id} has reached the maximum number of steps.")
            return self.research_plans
        research_planner_agent = ResearchPlanner(input=self.question, hypothesis=self.hypotheses, tools=self.tools)
        try:
            rp: ManyResearchPlannerAgSchema = research_planner_agent.run(True)
            self.state = 'RESEARCH_PLAN_GENERATED'
            self.research_plans = rp.actions
        except Exception as e:
            logger.error(f"{self.name}: Error occurred while running research planner agent: {e}")
            self.state = "ERROR"
        self.current_step += 1


    def run_order(self):
        if self.state == "INIT":
            self.generate_hypotheses()
            self.research_planner()


if __name__ == "__main__":
    input_text = "Why is Infineon doing worse than NVIDIA?"
    state = InvestigationState(question=input_text)
    state.run_order()
    print('\n\n---------------------------------------------------------------')
    logger.info(f"Question:\n{input_text}\n\nHypothesis:\n{state.hypotheses}\n\nActions:\n{state.research_plans}")
