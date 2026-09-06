import time
import uuid
from abc import ABC
from collections import OrderedDict

from ...config import Config
from ...helpers import run_with_timeout
from ...tools.executor import ToolExecutor
from ...tools.store import WebSearch
from ..agent import (
    EvidenceEvaluator,
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
    def __init__(self, name, session_id=None):
        self.session_id = session_id if session_id else uuid.uuid4()
        self.name = f"{name}_{self.session_id}"  # modify name to unique name for state
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
    def __init__(self, question, session_id=None):
        super().__init__(name="Investigation Agent", session_id=session_id)

        self.question = question
        self.question_analysis = None
        self.clarification = None
        self.tools = [WebSearch(session_id=self.session_id)]
        self.hypotheses = []
        self.research_plans = []
        self.research_tasks = []
        self.evidence = []
        self.evidence_evaluation = []
        self.evidence_impact = None
        self.contradictions = []
        self.events = []
        self.max_retries = 3

    def analyze_question(self):
        analyzer = QuestionAnalyzerAgent(
            self.question,
            max_retries=self.max_retries,
            session_id=self.session_id,
        )
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
            print(
                f"\nFollow-up question:\n{self.question_analysis.followup_question}\n"
            )
        else:
            missing = "\n".join(
                f"- {m}" for m in self.question_analysis.missing_information
            )
            print(
                f"\nThe question needs clarification. Missing information:\n{missing}\n"
            )
        answer = input("Please clarify (or press Enter to proceed as-is): ").strip()
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
            session_id=self.session_id,
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

    def generate_research_plan(self, evaluation=None):
        research_planner_agent = ResearchPlanner(
            input=self.question,
            hypothesis=self.hypotheses,
            evaluation=evaluation,
            max_retries=self.max_retries,
            session_id=self.session_id,
        )
        try:
            rp: ManyResearchPlannerAgSchema = research_planner_agent.run(True)
            if rp is None:
                self.set_state(
                    "ERROR", reason="Research planner agent returned no result."
                )
                return
            self.set_state("RESEARCH_PLAN_GENERATED")
            # plans are immutable: append new objectives, never replace existing ones
            self.research_plans.extend(self._assign_plan_ids(rp.plans))
        except Exception as e:
            self.set_state(
                "ERROR",
                reason=f"Error occurred while running research planner agent: {e}",
            )

    def generate_research_task(self, evaluation=None):
        # only open objectives get executed — closed plans (WEAKENED /
        # INVALIDATED / COMPLETED) are kept for history but not acted on
        active_plans = [
            p for p in self.research_plans if getattr(p, "status", "ACTIVE") == "ACTIVE"
        ]
        if not active_plans:
            self.set_state(
                "TASKS_SKIPPED", reason="No active research plans available."
            )
            return
        research_task_agent = ResearchTask(
            input=self.question,
            plans=active_plans,
            tools=self.tools,
            max_retries=self.max_retries,
            evaluation=evaluation,
            session_id=self.session_id,
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
                task_exec = ToolExecutor(
                    name=task.tool,
                    parameters=task.parameters,
                    session_id=self.session_id,
                )
                exec_result = task_exec.result
                if exec_result is None:
                    self.set_state(
                        f"TASK_FAILED Task {idx}/{total_tasks}",
                        reason=f"Task {task.tool} with ID {task.id} returned no result.",
                    )
                    continue
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
        failed = total_tasks - len(evidence)
        self.set_state(
            "ALL_TASKS_EXECUTED",
            reason=f"{failed}/{total_tasks} tasks failed."
            if failed
            else "All tasks succeeded.",
        )
        self.evidence = evidence  # since this is a evidence gathering process
        logger.info(f"Evidence gathered. Count: {len(self.evidence)}")

    def update_hypothesis(self):
        """Apply evidence-driven updates to plans and hypothesis confidence.

        Plans are immutable: evidence never rewrites a plan's objective, it
        only transitions its status. Strongest impact wins per plan:
        contradictory -> INVALIDATED, weakening -> WEAKENED, supporting -> COMPLETED.
        New objectives are created by generate_research_plan, not by mutating
        existing plans.

        Confidence is updated per hypothesis from each relevant evidence item:
        direction comes from the item's impact, magnitude is weighted by the
        priority of the plan that produced the evidence. Every update is
        recorded in the hypothesis' confidence_history and in self.events
        with the evaluator's impact_reasoning.
        """
        evaluations = self.evidence_evaluation.get("evaluations", [])
        # map each evidence item back to the plan its task executed
        task_to_plan = {t.id: t.plan_id for t in self.research_tasks}
        plan_by_id = {p.id: p for p in self.research_plans}

        # --- plan lifecycle transitions ---
        transitions = []
        for impact, new_status in (
            ("contradictory", "INVALIDATED"),
            ("weakening", "WEAKENED"),
            ("supporting", "COMPLETED"),
        ):
            for e in evaluations:
                if not e.get("evidence_relevant") or e.get("evidence_impact") != impact:
                    continue
                plan = plan_by_id.get(task_to_plan.get(e.get("evidence_id")))
                if plan is None or plan.status != "ACTIVE":
                    continue
                plan.status = new_status
                transitions.append(f"{plan.id} -> {new_status}")

        # --- per-hypothesis confidence updates ---
        updates = []
        for e in evaluations:
            impact = e.get("evidence_impact", "neutral")
            if not e.get("evidence_relevant") or impact == "neutral":
                continue
            plan = plan_by_id.get(task_to_plan.get(e.get("evidence_id")))
            if plan is None:
                continue
            weight = plan.priority  # higher-priority evidence moves confidence more
            for h in self.hypotheses:
                if str(h.id) not in plan.hypotheses_targeted:
                    continue
                old = h.confidence
                if impact == "supporting":
                    new = old + weight * (1 - old)
                elif impact == "weakening":
                    new = old - weight * old
                else:  # contradictory
                    new = old - 2 * weight * old
                h.confidence = round(min(1.0, max(0.0, new)), 3)
                h.confidence_history.append(h.confidence)
                updates.append(f"H{h.id}: {old} -> {h.confidence}")
                self.events.append(
                    {
                        "event": "confidence_update",
                        "hypothesis_id": h.id,
                        "evidence_id": e.get("evidence_id"),
                        "impact": impact,
                        "old_confidence": old,
                        "new_confidence": h.confidence,
                        "reasoning": e.get("impact_reasoning", ""),
                    }
                )

        self.set_state(
            "HYPOTHESIS_UPDATED",
            reason="Plan transitions: "
            + (", ".join(transitions) if transitions else "none")
            + " | Confidence updates: "
            + (", ".join(updates) if updates else "none"),
        )

    def _assign_plan_ids(self, plans):
        """Assign deterministic plan IDs (RP-001, RP-002, ...) continuing after
        the existing ones — IDs proposed by the LLM are ignored."""
        next_n = 1 + max(
            (
                int(p.id.split("-")[1])
                for p in self.research_plans
                if p.id.startswith("RP-") and p.id.split("-")[1].isdigit()
            ),
            default=0,
        )
        for plan in plans:
            plan.id = f"RP-{next_n:03d}"
            next_n += 1
        return plans

    def evaluate_evidence(self):
        # check evidence
        if self.evidence:
            ee = EvidenceEvaluator(
                input=self.question,
                clarification=self.clarification,
                hypothesis=self.hypotheses,
                plans=self.research_plans,
                tasks=self.research_tasks,
                evidence=self.evidence,
                max_retries=self.max_retries,
                session_id=self.session_id,
            )
            self.evidence_evaluation = ee.evaluation
        else:
            logger.error("Evidence is empty. Cannot be evaluated")
            raise AttributeError
        evaluations = self.evidence_evaluation.get("evaluations", [])
        relevant = [e for e in evaluations if e.get("evidence_relevant")]
        # relevance != impact: first check whether any evidence matters at all
        if not relevant:
            # no relevant evidence -> execution-level failure: new tasks with feedback
            return self.generate_research_task(evaluation=self.evidence_evaluation)
        # aggregate per-evidence impact over relevant items, strongest signal wins:
        # contradictory > weakening > supporting > neutral
        impacts = {e.get("evidence_impact", "neutral") for e in relevant}
        self.evidence_impact = next(
            (i for i in ("contradictory", "weakening", "supporting") if i in impacts),
            "neutral",
        )
        if self.evidence_impact == "supporting":
            return self.update_hypothesis()
        if self.evidence_impact == "weakening":
            self.update_hypothesis()
            # feed the weakness into the next research round
            return self.generate_research_task(evaluation=self.evidence_evaluation)
        if self.evidence_impact == "contradictory":
            self.update_hypothesis()
            # investigate the alternative: objective changed -> new plan
            return self.generate_research_plan(evaluation=self.evidence_evaluation)
        # neutral / insufficient -> more evidence needed, same objective
        return self.generate_research_task(evaluation=self.evidence_evaluation)

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
                            self.evaluate_evidence,
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
    # input_text = "Google is the greatest company on earth"
    session_id = time.time()
    input_text = "Morning are great for productive technical work. For junor developers to complete the coding tasks on their list."
    state = InvestigationState(
        question=input_text,
        session_id=session_id,
    )
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
