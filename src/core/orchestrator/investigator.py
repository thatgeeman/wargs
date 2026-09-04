import uuid
from abc import ABC
from collections import OrderedDict

from ...config import Config
from ...helpers import run_with_timeout
from ...tools.store import WebSearch
from ..agent import (
    HypothesisAgent,
    ManyHypothesesAgSchema,
    ManyResearchPlannerAgSchema,
    ManyResearchTaskAgSchema,
    ResearchPlanner,
    ResearchTask,
)

cfg = Config()
logger = cfg.get_logger("InvestigatorLogger")


class BaseState(ABC):
    def __init__(self, name):
        self.id = str(uuid.uuid4())
        self.name = f"{name} ({self.id})"  # modify name to unique name for state
        self.state = "INIT"
        self.current_step = 0
        self.max_steps = 10  # Default max steps, can be adjusted as needed
        self.timeout_perstep_s = 60
        self.tools = None
        logger.info(f"{self.name}: Initialized")

    def log(self, state, reason=""):
        logger.info(f"{self.name}: {state}. {reason}")

    def set_state(self, state, **kwargs):
        self.state = state
        self.log(self.state, **kwargs)

    def get_name(self, f):
        return f.__name__


class InvestigationState(BaseState):
    def __init__(self, question):
        super().__init__(name="Investigation Agent")
        self.question = question
        self.tools = [WebSearch()]
        self.hypotheses = []
        self.research_plans = []
        self.evidence = []
        self.contradictions = []
        self.events = []

    def generate_hypotheses(self):
        hypothesis_agent = HypothesisAgent(self.question)
        try:
            ha: ManyHypothesesAgSchema = hypothesis_agent.run(True)
            self.set_state("HYPOTHESIS_GENERATED")
            self.hypotheses = ha.hypotheses
        except Exception as e:
            self.set_state(
                "ERROR",
                reason=f"Error occurred while running research planner agent: {e}",
            )
        self.current_step += 1

    def generate_research_plan(self):
        research_planner_agent = ResearchPlanner(
            input=self.question,
            hypothesis=self.hypotheses,
        )
        try:
            rp: ManyResearchPlannerAgSchema = research_planner_agent.run(True)
            self.set_state("HYPOTHESIS_GENERATED")
            self.research_plans = rp.plans
        except Exception as e:
            self.set_state(
                "ERROR",
                reason=f"Error occurred while running research planner agent: {e}",
            )
        self.current_step += 1

    def generate_research_task(self):
        research_task_agent = ResearchTask(
            input=self.question, hypothesis=self.hypotheses, tools=self.tools
        )
        try:
            rt: ManyResearchTaskAgSchema = research_task_agent.run(True)
            self.set_state("TASKS_GENERATED")
            self.research_tasks = rt.tasks
        except Exception as e:
            self.set_state(
                "ERROR",
                reason=f"Error occurred while running research task agent: {e}",
            )
        self.current_step += 1

    def run_order(self):
        if self.state == "INIT" or self.current_step < self.max_steps:
            self.set_state(
                "MAX_STEPS_REACHED", reason="Reached the maximum number of steps."
            )
            steps = OrderedDict(
                [
                    (f"step_{i}", func)
                    for i, func in enumerate(
                        [
                            self.generate_hypotheses,
                            self.generate_research_plan,
                            self.generate_research_task,
                        ]
                    )
                ]
            )
            # destructive loop
            while steps:
                step_id, step_func = steps.popitem(last=False)
                try:
                    run_with_timeout(step_func, self.timeout_perstep_s)
                except TimeoutError:
                    logger.error(
                        f"Investigation timed out @ {step_id}: {self.get_name(step_func)}"
                    )
        else:
            logger.info(
                f"STOPPING: {self.state}, steps: {self.current_step}/{self.max_steps}"
            )
            return


if __name__ == "__main__":
    input_text = "Why is Infineon doing worse than NVIDIA?"
    state = InvestigationState(question=input_text)
    state.run_order()
    print("\n\n---------------------------------------------------------------")
    logger.info(
        f"""
        Question:\n{input_text}\n\n
        Hypothesis:\n{state.hypotheses}\n\n
        Actions:\n{state.research_plans}\n\n
        Tasks:\n{state.research_tasks}
        """
    )
