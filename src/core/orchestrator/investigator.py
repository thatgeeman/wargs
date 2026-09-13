import json
import os
import uuid
from abc import ABC
from collections import OrderedDict

from ...config import Config
from ...helpers import WargsEncoder, run_with_timeout
from ...tools.executor import ToolExecutor
from ...tools.store import REGISTERED_TOOLS, WebSearch
from ..agent import (
    ContradictionAgent,
    DecisionAgent,
    EvidenceEvaluator,
    HypothesisAgent,
    HypothesisAgSchema,
    ManyHypothesesAgSchema,
    ManyResearchPlannerAgSchema,
    ManyResearchTaskAgSchema,
    QuestionAnalysisAgSchema,
    QuestionAnalyzerAgent,
    ReportAgent,
    ResearchPlanner,
    ResearchPlannerAgSchema,
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
        self.config = Config()
        self.trace_file = (
            self.config.config_dir / f"trace_{self.session_id}" / f"{self.name}.json"
        )
        # mirror all log output into this run's session dir (run.log)
        Config.init_session_logging(self.session_id)
        logger.info(f"{self.name}: Initialized")

    def log(self, state, reason=""):
        logger.info(f"{self.name}: {state}. {reason}")

    def set_state(self, state, **kwargs):
        self.state = state
        self.log(self.state, **kwargs)

    def get_name(self, f):
        return f.__name__

    def to_json(self):
        data = self.__dict__
        return json.dumps(data, cls=WargsEncoder, indent=4)

    @classmethod
    def from_json(cls, json_str: str):
        data = json.loads(json_str)
        return cls(**data)

    @classmethod
    def from_path(cls, path: str):
        with open(path, "r") as f:
            json_str = f.read()
        return cls.from_json(json_str)

    def dump_trace(self):
        path = self.trace_file
        traces = self.to_json()  # already a JSON string
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # overwrite state
        with open(path, "w") as f:
            f.write(traces)
        logger.info(f"Trace for {self.name} saved to {self.trace_file}")
        return True


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
        self._decision_made = False
        self._decision_exec = False

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
        # only open objectives get executed; closed plans (WEAKENED /
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

    @staticmethod
    def _targeted_impacts(evaluation, plan):
        """Impact labels of an evidence item, restricted to the hypotheses
        the plan targets. Falls back to all of the item's impacts when the
        plan lists no usable targets."""
        targets = set()
        for t in plan.hypotheses_targeted:
            try:
                targets.add(int(t))
            except (TypeError, ValueError):
                continue
        return [
            hi.get("impact", "neutral")
            for hi in evaluation.get("hypothesis_impacts", [])
            if not targets or hi.get("hypothesis_id") in targets
        ]

    def update_hypothesis(self):
        """Apply evidence-driven updates to plans and hypothesis confidence.

        Plans are immutable: evidence never rewrites a plan's objective, it
        only transitions its status. Strongest targeted impact wins per plan:
        contradictory -> INVALIDATED, weakening -> WEAKENED, supporting ->
        COMPLETED, computed only over the hypotheses the plan targets, so
        evidence hitting a non-targeted hypothesis never transitions the plan.
        New objectives are created by generate_research_plan, not by mutating
        existing plans.

        Confidence is updated per hypothesis from each relevant evidence item's
        hypothesis_impacts: direction comes from the per-hypothesis impact the
        evaluator assigned, magnitude is weighted by the priority of the plan
        that produced the evidence. Hypotheses the evaluator did not list are
        left untouched, since an item-level impact never bleeds onto hypotheses it
        does not address. Every update is recorded in the hypothesis'
        confidence_history and in self.events with the evaluator's reasoning.
        """
        evaluations = self.evidence_evaluation.get("evaluations", [])
        # map each evidence item back to the plan its task executed
        task_to_plan = {t.id: t.plan_id for t in self.research_tasks}
        plan_by_id = {p.id: p for p in self.research_plans}

        # --- plan lifecycle transitions ---
        # per-item impact is computed against the plan's targeted hypotheses
        # only (see _targeted_impacts); strongest targeted impact wins
        transitions = []
        for impact, new_status in (
            ("contradictory", "INVALIDATED"),
            ("weakening", "WEAKENED"),
            ("supporting", "COMPLETED"),
        ):
            for e in evaluations:
                if not e.get("evidence_relevant"):
                    continue
                plan = plan_by_id.get(task_to_plan.get(e.get("evidence_id")))
                if plan is None or plan.status != "ACTIVE":
                    continue
                if impact not in self._targeted_impacts(e, plan):
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
        the existing ones. IDs proposed by the LLM are ignored. Status is also
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
        # round-level aggregate: histogram over the per-hypothesis impacts of
        # all relevant items. Mixed-direction rounds (supports H1 while
        # weakening H2) stay visible instead of collapsing to a single label.
        self.evidence_impact = {
            label: sum(
                1
                for e in relevant
                for hi in e.get("hypothesis_impacts", [])
                if hi.get("impact", "neutral") == label
            )
            for label in ("supporting", "weakening", "contradictory", "neutral")
        }
        logger.info(f"Evidence impact this round: {self.evidence_impact}")
        has_signal = any(
            self.evidence_impact[label]
            for label in ("supporting", "weakening", "contradictory")
        )
        # stagnation tracking: rounds with no relevant evidence or only neutral
        # impact count toward the force-finish cap; any real signal resets it
        if not has_signal:
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
                    reason=f"{self.neutral_streak} consecutive neutral evidence rounds, further research shows diminishing returns.",
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
        # note: _decision_made/_decision_exec bookkeeping and the trace dump
        # are owned by agent_loop (single place for the flag state machine)

    def generate_contradictions(self, feedback):
        # contradictions are newly generated on every generate as it depends on the hypothesis and plan
        # note: this is a list of ContradictionAgent objects; each result
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
            logger.info(f"Contradiction for {h_id} prepared: {c.decision}")

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
                # no counterevidence to chase, so skip straight to the next
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

        # hypothesis discussions, including rejected ones, with the
        # harness-owned final confidence shown next to the agent's verdict
        for entry in report.hypotheses:
            h = hypothesis_by_id.get(entry.hypothesis_id)
            if h is None:
                logger.warning(
                    f"Report discusses unknown hypothesis id {entry.hypothesis_id}, skipping."
                )
                continue
            discussed.add(entry.hypothesis_id)
            lines += [
                f"### H{h.id}: {h.hypothesis}",
                "",
                f"*Final confidence: {h.confidence}, verdict: {entry.verdict}*",
                "",
                entry.discussion,
                "",
            ]
        # safety net: hypotheses the agent failed to discuss are still listed
        for h in self.hypotheses:
            if h.id not in discussed:
                lines += [
                    f"### H{h.id}: {h.hypothesis}",
                    "",
                    f"*Final confidence: {h.confidence}, verdict: not discussed by report agent*",
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
            header = f"- **[{e.get('id')}]**: `{e.get('tool')}`"
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
            # if decision already made, dont run again
            if not self._decision_made:
                self.decision_agent()
                # flags + dump live here (not in decision_agent) so the dumped
                # trace always records the pending-decision state: a crash
                # before execution then resumes by executing it
                self._decision_made = True
                self._decision_exec = False  # reset
                self.dump_trace()

            # decide what to do based on next action made by decision agent
            if self.next_action is None:
                self.set_state("ERROR", reason="Decision agent returned no decision.")
                break
            if self.next_action == "FINISH":
                self.set_state(
                    "AGENT_DONE", reason="Decision agent finished the investigation."
                )
                break

            # if already decided what to do, but not executed (usually in resume) then execute,
            if not self._decision_exec:
                self.execute_decision()
                # bookkeeping lives here (not in execute_decision) so every
                # return path, including early returns like CHALLENGE with no
                # contradiction, marks the decision as consumed and forces a
                # fresh decision on the next iteration
                self._decision_exec = True
                self._decision_made = False
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

            # save traces
            self.dump_trace()
            # handoff to the agentic loop with no retries: a timed-out loop must
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
            # save traces
            self.dump_trace()

        else:
            logger.info(
                f"STOPPING: {self.state}, steps: {self.current_step}/{self.max_steps}"
            )
            return

            if self.current_step > self.max_steps:
                self.set_state(
                    "MAX_STEPS_REACHED", reason="Reached maximum allowed steps."
                )


class ResumeInvestigationState(InvestigationState):
    def __init__(self, question, session_id, budget=10, trace_file=None):

        BaseState.__init__(
            self,
            name="Investigation Agent Resume",
            session_id=session_id,
            budget=budget,
        )

        self.question = question
        self._load_partial_results(trace_file)

    @classmethod
    def resume(cls, path, budget=10):
        state = cls.from_path(path=path)
        state.max_steps = budget
        return state

    @classmethod
    def from_json(cls, json_str: str):
        data = json.loads(json_str)
        try:
            question = data.get("question")
            session_id = data.get("session_id")
            trace_file = data.get("trace_file")
        except Exception as e:
            logger.info(f"Exception while reconstructing class: {e}")
            raise

        return cls(question=question, session_id=session_id, trace_file=trace_file)

    def _load_partial_results(self, trace_file):
        with open(trace_file, "r") as f:
            json_str = f.read()
            data = json.loads(json_str)

        # restore typed collections as pydantic models because downstream code
        # uses attribute access/mutation (h.confidence, plan.status, task.model_dump())
        self.hypotheses = [
            HypothesisAgSchema.model_validate(h) for h in data.get("hypotheses") or []
        ]
        self.research_plans = [
            ResearchPlannerAgSchema.model_validate(p)
            for p in data.get("research_plans") or []
        ]
        # parameters is Json[dict]: dumped traces hold a dict, so re-encode it
        self.research_tasks = [
            ResearchTaskAgSchema.model_validate(
                {
                    **t,
                    "parameters": json.dumps(t["parameters"])
                    if isinstance(t.get("parameters"), dict)
                    else t.get("parameters"),
                }
            )
            for t in data.get("research_tasks") or []
        ]
        # rebuild live tool instances from the trace's serialized tool entries.
        # Only the stable tool_name is carried over; each tool is a fresh
        # instance (new id, new trace file) under this session
        tool_names = dict.fromkeys(
            t.get("tool_name")
            for t in data.get("tools") or []
            if isinstance(t, dict) and t.get("tool_name")
        )
        self.tools = []
        for tool_name in tool_names:
            tool_cls = REGISTERED_TOOLS.get(tool_name)
            if tool_cls is None:
                logger.warning(
                    f"Trace references unregistered tool {tool_name}, skipping. "
                    f"Available: {list(REGISTERED_TOOLS)}"
                )
                continue
            self.tools.append(tool_cls(session_id=self.session_id))
            logger.info(f"Tool loaded from trace: {tool_name}")
        # state that tracks the agent loop
        self._decision_made = data.get("_decision_made", False)
        self._decision_exec = data.get("_decision_exec", False)
        # plain-data attributes are only consumed via .get()/dict-safe formatters
        #
        self.question_analysis = data.get("question_analysis")
        self.clarification = data.get("clarification")
        self.evidence = data.get("evidence") or []
        self.evidence_evaluation = data.get("evidence_evaluation") or {}
        self.evidence_impact = data.get("evidence_impact")
        self.contradictions = data.get("contradictions") or []
        self.events = data.get("events") or []
        self.decision = data.get("decision") or {}
        self.next_action = data.get("next_action")
        self.force_finish = data.get("force_finish") or False
        # defaults InvestigationState.__init__ would normally set: restore
        # from the trace where available, else mirror the fresh-init values
        self.max_retries = data.get("max_retries", 3)
        self.neutral_streak = data.get("neutral_streak", 0)
        self.max_neutral_streak = data.get("max_neutral_streak", 2)
        self.report = data.get("report")
        self.report_path = data.get("report_path")

    def run_resume_order(self):
        self.current_step = 1  # reset the current step parameter
        if self.state != "INIT" or self.current_step <= self.max_steps:
            self.dump_trace()
            # handoff to the agentic loop
            try:
                run_with_timeout(
                    self.agent_loop,
                    self.timeout_perstep_s * 10,
                    max_retries=1,
                    max_steps=self.max_steps,
                )
            except TimeoutError:
                logger.error("Agent loop timed out.")
            # save traces
            self.dump_trace()

        else:
            logger.info(
                f"STOPPING: {self.state}, steps: {self.current_step}/{self.max_steps}"
            )
            return

            if self.current_step > self.max_steps:
                self.set_state(
                    "MAX_STEPS_REACHED", reason="Reached maximum allowed steps."
                )
