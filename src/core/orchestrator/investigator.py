import time
import uuid
from abc import ABC
from collections import OrderedDict

from ...config import Config
from ...helpers import run_with_timeout
from ...tools.executor import ToolExecutor
from ...tools.store import WebSearch
from ..agent import (
    ContradictionAgent,
    DecisionAgent,
    EvidenceEvaluator,
    HypothesisAgent,
    ManyHypothesesAgSchema,
    ManyResearchPlannerAgSchema,
    ManyResearchTaskAgSchema,
    QuestionAnalysisAgSchema,
    QuestionAnalyzerAgent,
    ReportAgent,
    ResearchPlanner,
    ResearchTask,
    ResearchTaskAgSchema,
)

cfg = Config()
logger = cfg.get_logger("InvestigatorLogger")


class BaseState(ABC):
    def __init__(self, name, session_id=None, budget=10):
        self.session_id = session_id if session_id else uuid.uuid4()
        self.name = f"{name}_{self.session_id}"  # modify name to unique name for state
        self.state = "INIT"  # last state is AGENT_DONE
        self.current_step = 1
        self.max_steps = budget  # Default max steps, can be adjusted as needed
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
    def __init__(self, question, session_id=None, budget=10):
        super().__init__(
            name="Investigation Agent", session_id=session_id, budget=budget
        )

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
        self.decision = {}
        self.next_action = None
        self.max_retries = 3
        # harness-side stagnation break: consecutive evidence rounds that were
        # all-neutral (or had no relevant evidence at all). Reaching the cap
        # force-finishes the investigation instead of looping on REASSESS.
        self.neutral_streak = 0
        self.max_neutral_streak = 2
        self.force_finish = False
        self.report = None
        self.report_path = None

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

    def generate_research_plan(self, evaluation=None, contradictions=None):
        research_planner_agent = ResearchPlanner(
            input=self.question,
            hypothesis=self.hypotheses,
            evaluation=evaluation,
            contradictions=contradictions,
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

    def generate_research_task(self, evaluation=None, contradictions=None):
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
            contradictions=contradictions,
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

        Confidence is updated per hypothesis from each relevant evidence item's
        hypothesis_impacts: direction comes from the per-hypothesis impact the
        evaluator assigned, magnitude is weighted by the priority of the plan
        that produced the evidence. Hypotheses the evaluator did not list are
        left untouched — an item-level impact never bleeds onto hypotheses it
        does not address. Every update is recorded in the hypothesis'
        confidence_history and in self.events with the evaluator's reasoning.
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
        # driven by the evaluator's per-hypothesis impacts: only hypotheses
        # explicitly listed with a non-neutral impact are updated
        updates = []
        hypothesis_by_id = {h.id: h for h in self.hypotheses}
        for e in evaluations:
            if not e.get("evidence_relevant"):
                continue
            plan = plan_by_id.get(task_to_plan.get(e.get("evidence_id")))
            if plan is None:
                continue
            weight = plan.priority  # higher-priority evidence moves confidence more
            for hi in e.get("hypothesis_impacts", []):
                impact = hi.get("impact", "neutral")
                if impact == "neutral":
                    continue
                h = hypothesis_by_id.get(hi.get("hypothesis_id"))
                if h is None:
                    continue
                old = h.confidence
                if impact == "supporting":
                    new = old + weight * (1 - old)
                elif impact == "weakening":
                    new = old - weight * old
                else:  # contradictory
                    new = old - 2 * weight * old
                h.confidence = round(min(1.0, max(0.0, new)), 6)
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
                        "reasoning": hi.get("reasoning", ""),
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
        the existing ones — IDs proposed by the LLM are ignored. Status is also
        harness-owned: newly proposed plans always start as ACTIVE regardless of
        what the LLM emitted; only evidence may transition them."""
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
            plan.status = "ACTIVE"
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
            self.evidence_evaluation = ee.evaluation  # model_dump dict
            logger.info(
                f"Evaluation of Evidences gathered complete: {self.evidence_evaluation}"
            )
        else:
            logger.error("Evidence is empty. Cannot be evaluated")
            raise AttributeError
        evaluations = self.evidence_evaluation.get("evaluations", [])
        relevant = [e for e in evaluations if e.get("evidence_relevant")]
        # aggregate per-evidence impact over relevant items, strongest signal wins:
        # contradictory > weakening > supporting > neutral
        impacts = {e.get("evidence_impact", "neutral") for e in relevant}
        self.evidence_impact = (
            next(
                (
                    i
                    for i in ("contradictory", "weakening", "supporting")
                    if i in impacts
                ),
                "neutral",
            )
            if relevant
            else "neutral"
        )
        # stagnation tracking: rounds with no relevant evidence or only neutral
        # impact count toward the force-finish cap; any real signal resets it
        if self.evidence_impact == "neutral":
            self.neutral_streak += 1
            logger.info(
                f"Neutral evidence round {self.neutral_streak}/{self.max_neutral_streak}."
            )
            if self.neutral_streak >= self.max_neutral_streak:
                self.force_finish = True
                self.events.append(
                    {
                        "event": "force_finish",
                        "reason": f"{self.neutral_streak} consecutive neutral evidence rounds.",
                    }
                )
                self.log(
                    "FORCE_FINISH",
                    reason=f"{self.neutral_streak} consecutive neutral evidence rounds — further research shows diminishing returns.",
                )
        else:
            self.neutral_streak = 0
            # real signal -> apply plan transitions and confidence updates;
            # what happens next (new tasks, new plans, finish) is decided by
            # the decision agent, never inline here
            self.update_hypothesis()

    def decision_agent(self):
        da = DecisionAgent(
            input=self.question,
            clarification=self.clarification,
            hypothesis=self.hypotheses,
            plans=self.research_plans,
            tasks=self.research_tasks,
            evidence=self.evidence,
            evaluation=self.evidence_evaluation,
            max_retries=self.max_retries,
            session_id=self.session_id,
        )
        # DecisionAgent auto-runs on construction; .decision is already a dict
        self.decision = da.decision
        self.next_action = self.decision.get("decision")

    def generate_contradictions(self, feedback):
        # contradictions are newly generated on every generate as it depends on the hypothesis and plan
        # note: this is a list of ContradictionAgent objects — each result
        # dict (ContradictionAgSchema model_dump) lives on the agent's
        # .decision attribute
        self.contradictions = []
        # feedback is the DecisionAgent's decision dict (model_dump), not an object
        for h_id in feedback.get("focus_hypotheses", []):
            # also contract only those that were explicitly asked for, and challenged one at a time
            c = ContradictionAgent(
                input=self.question,
                clarification=self.clarification,
                hypothesis=self.hypotheses,
                hypothesis_id=h_id,
                plans=self.research_plans,
                tasks=self.research_tasks,
                evidence=self.evidence,
                evaluation=self.evidence_evaluation,
                max_retries=self.max_retries,
                session_id=self.session_id,
            )
            self.contradictions.append(c)
            logger.info(f"Contradiction for {h_id} prepared: {c}")

    def execute_decision(self):
        logger.info(f"DecisionAgent to execute: {self.decision}")
        feedback = self.decision  # carries feedback + focus_hypotheses
        if self.next_action == "REFINE_PLAN":
            self.generate_research_plan(
                evaluation=feedback,
                contradictions=self.contradictions,
            )
            self.generate_research_task(
                evaluation=feedback,
                contradictions=self.contradictions,
            )
        elif self.next_action == "REASSESS":
            self.generate_research_task(
                evaluation=feedback,
                contradictions=self.contradictions,
            )
        elif self.next_action == "CHALLENGE":
            self.generate_contradictions(feedback=feedback)
            found = [
                c
                for c in self.contradictions
                if getattr(c, "decision", {}).get("contradiction_found")
            ]
            if not found:
                # no counterevidence to chase — skip straight to the next
                # decision instead of re-executing the previous round's tasks
                self.set_state(
                    "CHALLENGE_NO_CONTRADICTION",
                    reason="Contradiction agent found no contradiction; no contradiction-driven research needed.",
                )
                return
            # contradictions are signal: turn their recommended follow-ups
            # into new plans and tasks so this round gathers NEW evidence
            # instead of re-executing the previous round's tasks
            self.generate_research_plan(
                evaluation=feedback,
                contradictions=self.contradictions,
            )
            self.generate_research_task(
                evaluation=feedback,
                contradictions=self.contradictions,
            )
        else:
            logger.warning(f"Unknown or missing action: {self.next_action}")
            return
        self.execute_research_task()
        self.evaluate_evidence()

    def generate_report(self):
        """Run the Report Agent on the final state and write the report.

        The agent only proposes the report sections (with inline evidence-ID
        citations); the harness owns the final markdown document: section
        order, per-hypothesis final confidences, and the References appendix
        that maps every citable evidence ID to the sources its tool call
        returned. The LLM never sees or invents URLs."""
        if not self.hypotheses:
            self.set_state(
                "REPORT_SKIPPED", reason="No hypotheses available for report."
            )
            return
        report_agent = ReportAgent(
            input=self.question,
            clarification=self.clarification,
            hypothesis=self.hypotheses,
            plans=self.research_plans,
            tasks=self.research_tasks,
            evidence=self.evidence,
            evaluation=self.evidence_evaluation,
            contradictions=self.contradictions,
            max_retries=self.max_retries,
            session_id=self.session_id,
        )
        try:
            report = report_agent.run(True)
            if report is None:
                self.set_state("ERROR", reason="Report agent returned no result.")
                return
            self.report = report
            self.report_path = self._write_report(report)
            self.set_state(
                "REPORT_GENERATED", reason=f"Report written to {self.report_path}"
            )
        except Exception as e:
            self.set_state(
                "ERROR",
                reason=f"Error occurred while running report agent: {e}",
            )

    def _write_report(self, report):
        from datetime import datetime

        hypothesis_by_id = {h.id: h for h in self.hypotheses}
        discussed = set()

        lines = [
            f"# {report.title}",
            "",
            f"**Question:** {self.question}  ",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d')}  ",
            f"**Session:** {self.session_id}",
            "",
            "## Abstract",
            "",
            report.abstract,
            "",
            "## 1. Introduction",
            "",
            report.introduction,
            "",
            "## 2. Hypotheses",
            "",
        ]

        # hypothesis discussions — including rejected ones — with the
        # harness-owned final confidence shown next to the agent's verdict
        for entry in report.hypotheses:
            h = hypothesis_by_id.get(entry.hypothesis_id)
            if h is None:
                logger.warning(
                    f"Report discusses unknown hypothesis id {entry.hypothesis_id} — skipping."
                )
                continue
            discussed.add(entry.hypothesis_id)
            lines += [
                f"### H{h.id} — {h.hypothesis}",
                "",
                f"*Final confidence: {h.confidence} — verdict: {entry.verdict}*",
                "",
                entry.discussion,
                "",
            ]
        # safety net: hypotheses the agent failed to discuss are still listed
        for h in self.hypotheses:
            if h.id not in discussed:
                lines += [
                    f"### H{h.id} — {h.hypothesis}",
                    "",
                    f"*Final confidence: {h.confidence} — verdict: not discussed by report agent*",
                    "",
                ]

        if report.alternate_hypotheses:
            lines += ["### Alternative hypotheses", ""]
            for alt in report.alternate_hypotheses:
                lines += [
                    f"**Alternative to H{alt.replaces_hypothesis_id}:** {alt.statement}",
                    "",
                    alt.discussion,
                    "",
                ]

        lines += [
            "## 3. Evidence",
            "",
            report.evidence,
            "",
            "## 4. Conclusion",
            "",
            report.conclusion,
            "",
            "## References",
            "",
            self._render_references(),
            "",
        ]

        report_dir = cfg.config_dir / f"trace_{self.session_id}"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / "report.md"
        path.write_text("\n".join(lines))
        return path

    def _render_references(self):
        """Map every citable evidence ID to the sources its tool call returned."""
        if not self.evidence:
            return "No evidence was gathered during this investigation."
        lines = []
        for e in self.evidence:
            params = e.get("parameters") or {}
            query = params.get("query") if isinstance(params, dict) else None
            header = f"- **[{e.get('id')}]** — `{e.get('tool')}`"
            if query:
                header += f' (query: "{query}")'
            lines.append(header)
            result = e.get("result") or {}
            if not isinstance(result, dict):
                continue
            for wr in result.get("web_results", []):
                title = wr.get("title") or "untitled"
                url = wr.get("url") or ""
                lines.append(f"  - [{title}]({url})" if url else f"  - {title}")
        return "\n".join(lines)

    def agent_loop(self, max_steps=None):
        max_steps = max_steps or self.max_steps  # replenish budget for agent loop
        for iteration in range(1, max_steps + 1):
            if self.force_finish:
                self.set_state(
                    "AGENT_DONE",
                    reason=f"Forced finish: {self.neutral_streak} consecutive neutral evidence rounds.",
                )
                break
            self.decision_agent()
            if self.next_action is None:
                self.set_state("ERROR", reason="Decision agent returned no decision.")
                break
            if self.next_action == "FINISH":
                self.set_state(
                    "AGENT_DONE", reason="Decision agent finished the investigation."
                )
                break
            self.execute_decision()
        else:
            self.set_state(
                "AGENT_DONE",
                reason=f"Max decision iterations reached ({max_steps}).",
            )
        logger.info("Prepare report now.")
        self.generate_report()

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

            # handoff to the agentic loop — no retries: a timed-out loop must
            # not be re-run from scratch
            try:
                run_with_timeout(
                    self.agent_loop,
                    self.timeout_perstep_s * 10,
                    max_retries=1,
                    max_steps=self.max_steps,  # the number of steps is replenished for agent loop
                )
            except TimeoutError:
                logger.error("Agent loop timed out.")

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
    # input_text = "Morning are great for productive technical work. For junor developers to complete the coding tasks on their list."
    # input_text = "Why is gaza and israel in conflict?"
    input_text = (
        "If an LLM/AI model solves a big math problem, who gets the credit for it?"
    )
    state = InvestigationState(
        question=input_text,
        session_id=session_id,
        budget=10,
    )
    state.run_order()
    print("\n\n---------------------------------------------------------------")
    logger.info(
        f"""
        Question:\n{input_text}\n\n
        Hypothesis:\n{state.hypotheses}\n\n
        Plans:\n{state.research_plans}\n\n
        Tasks:\n{state.research_tasks}\n\n
        Evidence:\n{state.evidence}\n\n
        Report:\n{state.report_path}
        """
    )
