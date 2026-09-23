# Wargs: Architectural Reference

This document describes the architecture **as implemented** in `src/`.
Ideas that are designed but not yet built live in
[docs/aspirations.md](docs/aspirations.md).

## 1. Purpose

**Wargs is an autonomous, hypothesis-driven investigation engine.**

Given a question about a real-world phenomenon, it:

1. generates competing hypotheses,
2. identifies what evidence would distinguish them,
3. autonomously researches the highest-value evidence,
4. updates the hypotheses,
5. actively searches for contradictory evidence,
6. repeats until the evidence is sufficient,
7. produces an uncertainty-aware conclusion.

The central idea is:

> **Wargs does not optimize for producing a confident answer. It optimizes for finding explanations that survive attempts to disprove them.**

---

# 2. High-level architecture

```text
                              USER
                               │
                               │ question
                               ▼
                    ┌──────────────────────┐
                    │  InvestigationState  │
                    │  (orchestrator)      │
                    │                      │
                    │ state machine /      │
                    │ budgets / retries /  │
                    │ trace dumps          │
                    └──────────┬───────────┘
                               │
           ┌───────────────────┼────────────────────────┐
           │                   │                        │
           ▼                   ▼                        ▼
   ┌───────────────┐   ┌───────────────┐       ┌────────────────┐
   │  Hypothesis   │   │   Research    │       │ Contradiction  │
   │    Agent      │   │Planner / Task │       │     Agent      │
   └───────────────┘   └───────┬───────┘       └────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │    ToolExecutor      │
                    │  WebSearch (Tavily)  │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  EvidenceEvaluator   │
                    │ relevance + per-     │
                    │ hypothesis impact    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Harness-owned update │
                    │ plan status +        │
                    │ confidence update    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │    DecisionAgent     │
                    │ CHALLENGE /          │
                    │ REFINE_PLAN /        │
                    │ REASSESS / FINISH    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │     ReportAgent      │
                    │ sections + verdicts  │
                    │ (harness renders     │
                    │  report.md)          │
                    └──────────────────────┘
```

---

# 3. Architectural boundaries

The most important design principle is to separate **probabilistic reasoning** from **deterministic control**.

```text
            PROBABILISTIC LAYER (agents, src/core/agent/)
    ──────────────────────────────────

    QuestionAnalyzerAgent
    HypothesisAgent
    ResearchPlanner
    ResearchTask (agent)
    EvidenceEvaluator
    DecisionAgent
    ContradictionAgent
    ReportAgent
    RetrySchemaAgent (repairs invalid structured output)

                 │
                 ▼

            STRUCTURED DATA (pydantic schemas, src/core/agent/schemas.py)
    ──────────────────────────────────

    Hypotheses
    ResearchPlans
    ResearchTasks
    Evidence evaluations
    Contradictions
    Decision
    Report
    InvestigationState

                 │
                 ▼

            DETERMINISTIC LAYER (harness)
    ──────────────────────────────────

    InvestigationState (orchestrator)
    ToolExecutor / registered tools
    Schema validation + repair
    Plan ID assignment + plan status transitions
    Confidence updates
    Retries / timeouts / budgets
    Report rendering
    Trace persistence
```

### Rule

> **Agents propose. The harness controls.**

Agents never mutate global investigation state directly and never execute
tools. The harness assigns plan IDs, owns plan status transitions, applies
confidence updates, and renders the final report.

---

# 4. InvestigationState

`InvestigationState` (`src/core/orchestrator/investigator.py`) is the central
object representing one investigation. It **is** the orchestrator: a state
machine that runs a fixed bootstrap sequence and then hands off to the
decision loop.

```text
InvestigationState
│
├── question
├── question_analysis        # QuestionAnalysisAgSchema
├── clarification            # optional user answer
│
├── hypotheses[]             # HypothesisAgSchema (confidence, confidence_history)
├── research_plans[]         # ResearchPlannerAgSchema, immutable objectives
├── research_tasks[]         # ResearchTaskAgSchema for the current round
│
├── evidence[]               # task dicts with harness-attached results
├── evidence_evaluation      # EvidenceEvaluationAgSchema as dict
├── evidence_impact          # round-level histogram of impacts
├── contradictions[]         # ContradictionAgent instances
│
├── decision / next_action   # DecisionAgSchema output
├── events[]                 # confidence_update / force_finish events
│
├── report / report_path     # ReportAgSchema + written report.md
│
└── harness controls
    ├── max_steps (budget), max_retries, timeout_perstep_s
    ├── neutral_streak / max_neutral_streak / force_finish
    └── _decision_made / _decision_exec (resume bookkeeping)
```

State is dumped to JSON (`dump_trace()`) under the session trace directory
after the bootstrap steps and around every decision, so a crashed run can be
resumed (see §13).

---

# 5. Hypothesis Agent

### Responsibility

Generate competing explanations for the question, given the question
analysis and optional user clarification.

### Output (`HypothesisAgSchema`)

```text
Hypothesis
├── id (int, >= 1)
├── hypothesis (statement)
├── confidence (prior, 0..1)
├── confidence_history[]     # filled by the harness, not the agent
├── supporting_predictions[]
└── weakening_predictions[]
```

### Boundary

The Hypothesis Agent **doesn't research the claims**. It says:

> “What should be true if this explanation is correct?”

---

# 6. Research Planner & Research Task agents

### ResearchPlanner

Produces `ResearchPlan`s (`ResearchPlannerAgSchema`):

```text
ResearchPlan
├── id                       # harness-assigned: RP-001, RP-002, ...
├── plan (objective)
├── rationale
├── hypotheses_targeted[]    # hypothesis int IDs
├── supporting_result        # expected supporting evidence
├── weakening_result         # expected weakening evidence
├── priority (0..1)          # weights confidence updates
└── status                   # ACTIVE | WEAKENED | INVALIDATED | COMPLETED
```

A key principle:

> **Don't research everything. Research what can change the hypothesis ranking.**

### ResearchTask (agent)

Converts ACTIVE plans into concrete tool calls (`ResearchTaskAgSchema`):

```text
ResearchTask
├── id            # e.g. RT-001
├── plan_id       # the RP this task executes
├── tool          # must be a registered tool
├── parameters    # JSON-encoded tool arguments
└── result        # harness-only: attached after execution, never sent to the LLM
```

### Plan lifecycle (implemented)

`ResearchPlan`s are **immutable**: evidence never rewrites a plan's
objective, it only transitions its status. Plan IDs and initial status are
harness-owned (`_assign_plan_ids`); LLM-proposed IDs are ignored. Only
ACTIVE plans are executed. New objectives are appended as new plans
(RP-002, RP-003, ...), never mutated in place.

**Rule:**
**Change in execution → new task.**
**Change in research objective → new plan.**

---

# 7. ToolExecutor and tools

The planner/task agents never call tools. The harness executes each task
through `ToolExecutor` (`src/tools/executor.py`), which validates the tool
name against `REGISTERED_TOOLS`, runs it, and attaches the raw result to
the task record.

Currently registered tools:

| Tool        | Backend | Notes                                  |
| ----------- | ------- | -------------------------------------- |
| `WebSearch` | Tavily  | Returns web results, short answer, follow-up questions |

Tools self-register via `Tool.__init_subclass__` under a stable
`tool_name`, which is what survives in traces and lets resume rebuild live
tool instances.

The executor is deliberately dumb: it executes, captures results and
failures, and never interprets what results mean.

---

# 8. Evidence evaluation

`EvidenceEvaluator` evaluates **each evidence item independently**
(`SingleEvidenceEvaluationAgSchema`):

```text
Per evidence item:
├── evidence_id           # the task ID that produced it
├── evidence_relevant     # does it address the question/plans?
├── relevance_reasoning
├── hypothesis_impacts[]  # per-hypothesis: supporting | weakening |
│                         #   contradictory | neutral + reasoning
└── impact_reasoning
```

The evaluator distinguishes **relevance ≠ impact**. It decides whether
evidence matters and what it does to each hypothesis; it does **not**
perform the update.

The harness then aggregates a round-level histogram
(`state.evidence_impact`) over the per-hypothesis impacts of all relevant
items.

---

# 9. Harness-owned hypothesis update

`update_hypothesis()` (in `InvestigationState`) applies the evaluation
deterministically:

**Plan transitions** — strongest targeted impact wins per plan, computed
only over the hypotheses the plan targets:

```text
contradictory → INVALIDATED
weakening     → WEAKENED
supporting    → COMPLETED
```

**Confidence updates** — only hypotheses explicitly listed with a
non-neutral impact change; the magnitude is weighted by the originating
plan's priority:

```text
supporting:    c' = c + w·(1 − c)
weakening:     c' = c − w·c
contradictory: c' = c − 2·w·c
```

Every update is appended to the hypothesis's `confidence_history` and
logged in `state.events` with the evaluator's reasoning.

**Stagnation break** — rounds with no relevant or only-neutral evidence
increment `neutral_streak`; at `max_neutral_streak` (2) consecutive rounds
the harness sets `force_finish` and ends the loop instead of researching
forever.

---

# 10. Contradiction Agent

The ordinary research process asks:

> “What evidence can help explain this?”

The contradiction agent asks:

> **“What evidence would make our leading explanation wrong?”**

When the DecisionAgent chooses `CHALLENGE`, one `ContradictionAgent` runs
per focus hypothesis and produces (`ContradictionAgSchema`):

```text
├── contradiction_found (bool)
├── contradiction_type      # DIRECT_CONTRADICTION | MISSING_EXPECTED_EVIDENCE |
│                           # ALTERNATIVE_EXPLANATION | SOURCE_DEPENDENCE |
│                           # TEMPORAL_MISMATCH | SCOPE_MISMATCH
├── contradiction
├── evidence_ids[]          # evidence it contradicts
├── alternative_hypothesis
├── severity                # LOW | MEDIUM | HIGH
└── recommended_followup
```

If no contradiction is found, the loop moves straight to the next
decision. If one is found, its recommended follow-ups are turned into new
plans and tasks so the next round gathers **new** evidence instead of
re-executing the previous round's tasks.

---

# 11. The decision loop (implemented autonomy)

After the bootstrap sequence (analyze → clarify → hypothesize → plan →
task → execute → evaluate), `agent_loop()` runs up to `max_steps`
iterations:

```text
              ┌────────────────────┐
              │   DecisionAgent    │  sees: question, clarification, hypotheses,
              └─────────┬──────────┘        plans, tasks, evidence, evaluation
                        │
        ┌───────────────┼───────────────┬──────────────┐
        ▼               ▼               ▼              ▼
     FINISH        REFINE_PLAN       REASSESS       CHALLENGE
        │          new plans +       new tasks for   ContradictionAgent per
        │          new tasks         ACTIVE plans    focus hypothesis,
        │               │               │            then new plans + tasks
        │               └───────┬───────┘            (if contradictions found)
        │                       ▼
        │               execute tasks → evaluate evidence → update
        │                       │
        │                       └──→ next iteration
        ▼
   exit loop → ReportAgent
```

The loop also exits on `force_finish`, on max iterations, or on an empty
decision (error).

> **Autonomy means selecting the next useful investigation step.**

---

# 12. Structured output contract

All agents emit strict structured output (`StrictSchema`, pydantic
`extra="forbid"` + `json_schema` strict mode). The wire schema is
post-processed before sending:

* all properties are declared **required** (so grammar-constrained decoders
  can't emit `{}`),
* `harness_only` fields (e.g. task `result`) are stripped — the LLM never
  sees fields it must not fill,
* `contentSchema` metadata from `Json[...]` fields is stripped (strict
  endpoints reject it).

Reliability behavior in `Agent.run` / `Model.call`:

* first attempt at temperature 0; retries add increasing temperature and
  exponential backoff with jitter (honoring `retry_after`),
* responses truncated at `max_tokens` (`finish_reason="length"`) are
  retried with a doubled token budget,
* invalid JSON/schema output goes to `RetrySchemaAgent`, which repairs it
  against the validation errors; empty/reasoning-only payloads are treated
  as failed generations and retried from scratch,
* every attempt (success or failure) is traced with token usage.

---

# 13. Persistence, resume, and traces

Everything writes into a per-session trace directory
(`trace_<session_id>/`):

* per-agent and per-tool trace JSON (raw choices + token usage),
* `InvestigationState` dumps after bootstrap and around every decision,
* `report.md` at the end,
* mirrored `run.log`.

`ResumeInvestigationState.resume(path)` rebuilds a crashed investigation
from a state dump: typed collections are re-validated as pydantic models,
live tool instances are rebuilt from their stable `tool_name`s, and the
`_decision_made` / `_decision_exec` flags make resume pick up exactly
where the dump was taken (a pending decision is executed, not re-made).

---

# 14. Report generation

The ReportAgent only **proposes** the report (`ReportAgSchema`): title,
abstract, introduction, one verdict + discussion per hypothesis (including
rejected ones), alternative hypotheses, an evidence section, and a
conclusion — all citing evidence by task ID inline (`[RT-001]`).

The harness owns the final markdown document: section order, the final
confidence values next to each verdict, a safety net for hypotheses the
agent failed to discuss, and the References appendix mapping every citable
evidence ID to the URLs its tool call returned. **The LLM never sees or
invents URLs.**

---

# 15. Agent vs Orchestrator

```text
Agent asks:

"What do I think?"
"What evidence should we seek?"
"What should challenge this?"
"Is this evidence relevant, and to which hypothesis?"
"What do we do next?"

Orchestrator asks:

"Who runs next?"
"What state are we in?"
"Is this tool registered?"
"Did the output validate?"
"Which plans are still ACTIVE?"
"Do we continue, force-finish, or stop?"
```

---

# 16. CLI surface (current)

```text
$ uv run app.py -q "Why is Infineon doing worse than NVIDIA?"
```

* Runs the full investigation and writes `report.md` plus traces under the
  session directory.
* If the question needs clarification, the user is asked interactively
  (Enter to proceed as-is).
* Resume is available programmatically via
  `ResumeInvestigationState.resume(<trace path>)`.

---

# 17. The architecture in one sentence

> **Wargs is a stateful agent runtime in which constrained agents generate, investigate, challenge, and revise competing hypotheses, while a deterministic orchestrator controls state, tool execution, plan lifecycle, confidence updates, budgets, and the investigation lifecycle.**
