import uuid
from abc import ABC
from collections import OrderedDict

from ...config import Config
from ...helpers import run_with_timeout
from ...tools.executor import ToolExecutor
from ...tools.store import WebSearch
from ..agent import (
    HypothesisAgent,
    ManyHypothesesAgSchema,
    ManyResearchPlannerAgSchema,
    ManyResearchTaskAgSchema,
    QuestionAnalysisAgSchema,
    QuestionAnalyzerAgent,
    ResearchPlanner,
    ResearchTask,
    ResearchTaskAgSchema,
)

cfg = Config()
logger = cfg.get_logger("InvestigatorLogger")


class BaseState(ABC):
    def __init__(self, name):
        self.id = str(uuid.uuid4())
        self.name = f"{name} ({self.id})"  # modify name to unique name for state
        self.state = "INIT"
        self.current_step = 1
        self.max_steps = 10  # Default max steps, can be adjusted as needed
        self.timeout_perstep_s = 300
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
        self.question_analysis = None
        self.clarification = None
        self.tools = [WebSearch()]
        self.hypotheses = []
        self.research_plans = []
        self.research_tasks = []
        self.evidence = []
        self.contradictions = []
        self.events = []
        self.max_retries = 3

    def analyze_question(self):
        analyzer = QuestionAnalyzerAgent(self.question, max_retries=self.max_retries)
        try:
            qa: QuestionAnalysisAgSchema = analyzer.run(True)
            if qa is None:
                self.set_state("ERROR", reason="Question analyzer returned no result.")
                return
            self.set_state("QUESTION_ANALYZED")
            self.question_analysis = qa
        except Exception as e:
            self.set_state(
                "ERROR",
                reason=f"Error occurred while running question analyzer agent: {e}",
            )

    def clarify_question(self):
        if self.question_analysis is None:
            self.set_state(
                "CLARIFICATION_SKIPPED", reason="No question analysis available."
            )
            return
        if self.question_analysis.investigation_status != "NEEDS_CLARIFICATION":
            self.set_state("CLARIFICATION_NOT_NEEDED")
            return
        if self.question_analysis.followup_question:
            print(f"\nFollow-up question:\n{self.question_analysis.followup_question}\n")
        else:
            missing = "\n".join(
                f"- {m}" for m in self.question_analysis.missing_information
            )
            print(
                f"\nThe question needs clarification. Missing information:\n{missing}\n"
            )
        answer = input(
            "Please clarify (or press Enter to proceed as-is): "
        ).strip()
        if answer:
            self.clarification = answer
            self.set_state("CLARIFICATION_RECEIVED")
        else:
            self.set_state("CLARIFICATION_SKIPPED", reason="User provided none.")

    def generate_hypotheses(self):
        hypothesis_agent = HypothesisAgent(
            self.question,
            analysis=self.question_analysis,
            clarification=self.clarification,
            max_retries=self.max_retries,
        )
        try:
            ha: ManyHypothesesAgSchema = hypothesis_agent.run(True)
            if ha is None:
                self.set_state("ERROR", reason="Hypothesis agent returned no result.")
                return
            self.set_state("HYPOTHESIS_GENERATED")
            self.hypotheses = ha.hypotheses
        except Exception as e:
            self.set_state(
                "ERROR",
                reason=f"Error occurred while running hypothesis agent: {e}",
            )

    def generate_research_plan(self):
        research_planner_agent = ResearchPlanner(
            input=self.question,
            hypothesis=self.hypotheses,
            max_retries=self.max_retries,
        )
        try:
            rp: ManyResearchPlannerAgSchema = research_planner_agent.run(True)
            if rp is None:
                self.set_state(
                    "ERROR", reason="Research planner agent returned no result."
                )
                return
            self.set_state("RESEARCH_PLAN_GENERATED")
            self.research_plans = rp.plans
        except Exception as e:
            self.set_state(
                "ERROR",
                reason=f"Error occurred while running research planner agent: {e}",
            )

    def generate_research_task(self):
        if not self.research_plans:
            self.set_state("TASKS_SKIPPED", reason="No research plans available.")
            return
        research_task_agent = ResearchTask(
            input=self.question, plans=self.research_plans, tools=self.tools, max_retries=self.max_retries
        )
        try:
            rt: ManyResearchTaskAgSchema = research_task_agent.run(True)
            if rt is None:
                self.set_state(
                    "ERROR", reason="Research task agent returned no result."
                )
                return
            self.set_state("TASKS_GENERATED")
            self.research_tasks = rt.tasks
        except Exception as e:
            self.set_state(
                "ERROR",
                reason=f"Error occurred while running research task agent: {e}",
            )

    def execute_research_task(self):
        evidence = []
        tasks = self.research_tasks
        total_tasks = len(tasks)
        if total_tasks < 1:
            logger.info(f"No tasks defined in research tasks: {self.research_plans}")
            return
        for idx, task in enumerate(tasks, start=1):
            try:
                task_exec = ToolExecutor(name=task.tool, parameters=task.parameters)
                exec_result = task_exec.result
                task_updated: ResearchTaskAgSchema = task.model_dump()
                task_updated["result"] = exec_result
                evidence.append(task_updated)

                self.set_state(
                    f"TASK_EXECUTED Task {idx}/{total_tasks}",
                    reason=f"Task {task.tool} with ID {task.id}.",
                )
            except Exception as e:
                self.set_state(
                    "ERROR",
                    reason=f"Error occurred while running research task agent: {e}, Task {idx}/{total_tasks}",
                )
        self.set_state("ALL_TASKS_EXECUTED")
        self.evidence = evidence  # since this is a evidence gathering process
        logger.info(f"Evidence gathered. Count: {len(self.evidence)}")

    def run_order(self):
        if self.state == "INIT" or self.current_step <= self.max_steps:
            steps = OrderedDict(
                [
                    (f"step_{self.current_step + i}", func)
                    for i, func in enumerate(
                        [
                            self.analyze_question,
                            self.clarify_question,
                            self.generate_hypotheses,
                            self.generate_research_plan,
                            self.generate_research_task,
                            self.execute_research_task,
                        ],
                        start=1,
                    )
                ]
            )
            # destructive loop
            while steps:
                step_id, step_func = steps.popitem(last=False)
                try:
                    run_with_timeout(
                        step_func, self.timeout_perstep_s, max_retries=self.max_retries
                    )
                except TimeoutError:
                    logger.error(
                        f"Investigation timed out @ {step_id}: {self.get_name(step_func)}"
                    )
                self.current_step += 1
        else:
            logger.info(
                f"STOPPING: {self.state}, steps: {self.current_step}/{self.max_steps}"
            )
            return

            if self.current_step > self.max_steps:
                self.set_state(
                    "MAX_STEPS_REACHED", reason="Reached maximum allowed steps."
                )


if __name__ == "__main__":
    # input_text = "Why is Infineon doing worse than NVIDIA?"
    input_text = "Google is the greatest company on earth"
    state = InvestigationState(question=input_text)
    state.run_order()
    print("\n\n---------------------------------------------------------------")
    logger.info(
        f"""
        Question:\n{input_text}\n\n
        Hypothesis:\n{state.hypotheses}\n\n
        Plans:\n{state.research_plans}\n\n
        Tasks:\n{state.research_tasks}\n\n
        Evidence:\n{state.evidence}
        """
    )
