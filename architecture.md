# Wahrgus: Architectural Reference

## 1. Purpose

**Wahrgus is an autonomous, hypothesis-driven investigation engine.**

Given a question about a real-world phenomenon, it:

1. generates competing hypotheses,
2. identifies what evidence would distinguish them,
3. autonomously researches the highest-value evidence,
4. updates the hypotheses,
5. actively searches for contradictory evidence,
6. repeats until the evidence is sufficient,
7. produces an uncertainty-aware conclusion.

The central idea is:

> **Wahrgus does not optimize for producing a confident answer. It optimizes for finding explanations that survive attempts to disprove them.**

---

# 2. High-level architecture

```text
                              USER
                               │
                               │ question
                               ▼
                    ┌──────────────────────┐
                    │     ORCHESTRATOR     │
                    │                      │
                    │ workflow / state /   │
                    │ budgets / scheduling │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  INVESTIGATION STATE │
                    │                      │
                    │ question              │
                    │ hypotheses            │
                    │ evidence              │
                    │ contradictions        │
                    │ sources               │
                    │ timeline              │
                    │ history               │
                    └──────────┬───────────┘
                               │
           ┌───────────────────┼────────────────────┐
           │                   │                    │
           ▼                   ▼                    ▼
   ┌───────────────┐   ┌───────────────┐   ┌────────────────┐
   │  Hypothesis   │   │   Research    │   │ Contradiction  │
   │    Agent      │   │    Planner    │   │     Agent      │
   └───────────────┘   └───────┬───────┘   └────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   RESEARCH TASKS     │
                    │                      │
                    │ objective            │
                    │ hypotheses targeted  │
                    │ expected outcomes    │
                    │ tool calls           │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  RESEARCH EXECUTOR   │
                    │                      │
                    │ executes tools       │
                    │ returns raw results  │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ EVIDENCE /           │
                    │ PROVENANCE LAYER     │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ HYPOTHESIS UPDATER   │
                    │                      │
                    │ strengthen           │
                    │ weaken                │
                    │ reject                │
                    │ spawn                 │
                    └──────────┬───────────┘
                               │
                               ▼
                         STOP DECISION
                          /           \
                        no             yes
                        │                │
                        └──────┐    ┌────┘
                               ▼    ▼
                           RESEARCH  SYNTHESIS
                                      │
                                      ▼
                                INVESTIGATION
                                   REPORT
```

---

# 3. Architectural boundaries

The most important design principle is to separate **probabilistic reasoning** from **deterministic control**.

```text
            PROBABILISTIC LAYER
    ──────────────────────────────────

    Hypothesis Agent
    Research Planner
    Contradiction Agent
    Hypothesis Updater
    Synthesis Agent

                 │
                 ▼

            STRUCTURED DATA
    ──────────────────────────────────

    Hypotheses
    ResearchTasks
    Evidence
    Claims
    Sources
    InvestigationState

                 │
                 ▼

            DETERMINISTIC LAYER
    ──────────────────────────────────

    Orchestrator
    State management
    Tool execution
    Validation
    Budgets
    Retries
    Event logging
```

### Rule

> **Agents propose. The harness controls.**

An agent should not directly mutate the global investigation or bypass the executor.

---

# 4. InvestigationState

`InvestigationState` is the central object representing one investigation.

```text
InvestigationState
│
├── id
├── question
├── status
├── hypotheses[]
│
├── evidence[]
├── sources[]
├── contradictions[]
├── timeline[]
│
├── pending_tasks[]
├── completed_tasks[]
│
├── confidence_history[]
├── open_questions[]
│
└── event_history[]
```

Example:

```text
Question:
Why is Infineon doing worse than NVIDIA?

Hypotheses:
H1 → different market exposure
H2 → stronger NVIDIA market position / margins
H3 → investor sentiment / valuation
H4 → Infineon-specific problems

Evidence:
...

Pending tasks:
...

Status:
INVESTIGATING
```

The **Orchestrator owns this state**.

Agents receive relevant state and return structured results.

---

# 5. Hypothesis Agent

### Responsibility

Generate competing explanations for the initial question.

### It should produce

```text
Hypothesis
├── id
├── statement
├── prior_confidence
├── supporting_predictions[]
└── weakening_predictions[]
```

Example:

```text
H1
Different market segments explain the performance gap.

Prior confidence: 0.85

Supporting predictions:
- NVIDIA AI-related revenue is growing rapidly
- Infineon is more exposed to slower automotive/industrial markets

Weakening predictions:
- Comparable segments show similar growth
- Infineon's markets outperform NVIDIA's
```

### Boundary

The Hypothesis Agent **doesn't research the claims**.

It says:

> “What should be true if this explanation is correct?”

---

# 6. Research Planner

### Responsibility

Identify the **highest-value next research actions**.

Input:

```text
question
hypotheses
predictions
existing evidence
known gaps
available tools
```

Output:

```text
ResearchTask
├── id
├── objective
├── rationale
├── hypotheses_targeted[]
├── supporting_result
├── weakening_result
├── priority
└── tool_calls[]
```

Conceptually:

```text
Hypotheses
   │
   ▼
What don't we know?
   │
   ▼
What evidence would distinguish them?
   │
   ▼
Which research action gives the most information?
   │
   ▼
ResearchTask
```

A key principle:

> **Don't research everything. Research what can change the hypothesis ranking.**

---

# 7. Research Executor

The Research Planner should **not execute tools itself**.

The executor receives a task:

```text
ResearchTask
      │
      ▼
ResearchExecutor
      │
      ├── WebSearch
      ├── Dataset query
      ├── API
      └── other tools
      │
      ▼
ResearchResult
```

The executor should be relatively dumb.

Its job is to:

* execute requested tools,
* validate tool inputs,
* capture results,
* capture failures,
* preserve provenance,
* return structured results.

It should **not decide what the results mean**.

---

# 8. Evidence model

This is one of the most important boundaries in Wahrgus.

Separate:

```text
SOURCE
   ↓
OBSERVATION
   ↓
CLAIM
   ↓
INTERPRETATION
   ↓
HYPOTHESIS
```

Example:

```text
Source:
Infineon annual report

Observation:
Automotive revenue declined X%.

Claim:
Infineon's automotive segment experienced a decline.

Interpretation:
This may explain part of Infineon's weaker performance.

Hypothesis:
Different market exposure contributes to the performance gap.
```

This prevents the system from treating a source's interpretation as an established fact.

---

# 9. Provenance / source layer

Every piece of evidence should retain metadata:

```text
Evidence
├── source
├── source_type
├── published_at
├── retrieved_at
├── URL / identifier
├── source_family
├── related_sources[]
├── observation
└── provenance
```

The system should **not claim neutrality**.

Instead it evaluates:

* source diversity,
* source independence,
* duplication,
* primary vs secondary sources,
* temporal relevance,
* geographic coverage.

The goal is not:

> “This source is unbiased.”

The goal is:

> “How dependent is our conclusion on this particular source or source family?”

---

# 10. Hypothesis Updater

The updater receives:

```text
current hypotheses
+
new evidence
+
research task's expected outcomes
```

and updates hypothesis state.

Possible transitions:

```text
0.85 → 0.91   strengthened
0.85 → 0.72   weakened
0.85 → 0.31   strongly challenged
0.85 → rejected
```

Hypotheses can also:

```text
spawn
merge
split
remain unresolved
```

Track confidence over time:

```text
H1

0.50 ──→ 0.71 ──→ 0.83 ──→ 0.62
                         ↑
                  contradictory evidence
```

### Evidence evaluation loop

After research execution:

```text
Evidence
   ↓
EvidenceEvaluator
   ↓
Is it relevant?
 ├─ No → generate new research task
 └─ Yes
      ↓
   What is the impact?
   ├─ Supporting → update hypothesis
   ├─ Weakening → update hypothesis + feed weakness into next research
   ├─ Contradictory → update hypothesis + investigate alternative
   └─ Neutral/insufficient → generate new research task
```

The evaluator should distinguish:

```text
relevance ≠ impact
```

Its job is to determine **whether the evidence matters and what it does to current beliefs**, not to perform the actual hypothesis update.

Each piece of evidence is evaluated independently (one evaluation per evidence item); the harness aggregates the per-item verdicts, strongest signal first: contradictory > weakening > supporting > neutral.

---

### Research plan lifecycle

Treat `ResearchPlan` as **immutable**.

A plan represents:

> “Given what we currently know, this is what we need to establish.”

When new evidence materially changes the investigation:

```text
RP-001
  ↓
evidence changes understanding
  ↓
RP-001 → WEAKENED / INVALIDATED / COMPLETED
  ↓
create RP-002
```

Don't mutate an old plan into a new objective.

Minor execution changes (retrying a search, refining a query, adding another source) stay within the existing plan.

**Rule:**
**Change in execution → update the task.**
**Change in research objective → create a new plan.**

New plans are appended with fresh deterministic IDs (RP-002, RP-003, …); existing plans keep their ID and objective, only their status transitions.

---

# 11. Contradiction Agent

This agent has a deliberately different objective.

The ordinary research process asks:

> “What evidence can help explain this?”

The contradiction agent asks:

> **“What evidence would make our leading explanation wrong?”**

```text
Leading hypothesis
        │
        ▼
Contradiction Agent
        │
        ├── search counterevidence
        ├── identify competing explanation
        └── identify weak assumptions
        │
        ▼
Contradiction
        │
        ▼
Hypothesis Updater
```

This helps prevent confirmation bias.

---

# 12. Autonomous investigation loop

This is the core of Wahrgus.

```text
                  QUESTION
                     │
                     ▼
               HYPOTHESIZE
                     │
                     ▼
             IDENTIFY GAPS
                     │
                     ▼
             PLAN RESEARCH
                     │
                     ▼
             EXECUTE RESEARCH
                     │
                     ▼
              COLLECT EVIDENCE
                     │
                     ▼
             UPDATE HYPOTHESES
                     │
                     ▼
             ATTACK LEADING ONE
                     │
                     ▼
             DO WE KNOW ENOUGH?
                /           \
              NO             YES
              │               │
              ▼               ▼
        PLAN NEXT STEP       SYNTHESIZE
              │               │
              └───────────────┘
```

The key point:

> **Autonomy means selecting the next useful investigation step.**

It doesn't necessarily mean modifying a real-world system.

---

# 13. Orchestrator

The Orchestrator is the control plane.

Its responsibilities:

```text
Orchestrator
├── create investigation
├── load/save state
├── select next task
├── dispatch agent
├── validate result
├── update state
├── handle retries
├── enforce budgets
├── determine stopping conditions
└── log events
```

The initial implementation can be very simple:

```text
state
  ↓
select agent
  ↓
run agent
  ↓
validate
  ↓
commit result
  ↓
select next agent
```

No separate processes are necessary initially.

---

# 14. Agent vs Orchestrator

This boundary should remain explicit.

```text
Agent asks:

"What do I think?"
"What evidence should we seek?"
"What should challenge this?"

Orchestrator asks:

"Who runs next?"
"What state are we in?"
"Is this task allowed?"
"Did the result validate?"
"Do we continue?"
"When do we stop?"
```

---

# 15. Tasks and execution

An agent should produce a **task**, not directly control infrastructure.

```text
              Agent
                │
                ▼
           ResearchTask
                │
                ▼
          Task Executor
                │
                ▼
              Tool
                │
                ▼
             Result
                │
                ▼
             State
```

This makes the system easy to:

* trace,
* retry,
* replay,
* evaluate,
* test.

---

# 16. Status / CLI surface

The first interface can be entirely CLI-based.

```text
$ wahrgus investigate "Why is Infineon doing worse than NVIDIA?"
```

Then:

```text
Investigation: 8c0c87b9

Question
────────────────────────────────
Why is Infineon doing worse than NVIDIA?

Hypotheses
────────────────────────────────
H1  Different market exposure       0.85
H2  Market position / margins       0.75
H3  Investor sentiment              0.65
H4  Internal challenges              0.50

Current task
────────────────────────────────
Investigating segment revenue data

Evidence
────────────────────────────────
12 observations
7 sources
2 source families

Status
────────────────────────────────
INVESTIGATING
```

Later:

```text
$ wahrgus inspect 8c0c87b9
$ wahrgus resume 8c0c87b9
$ wahrgus replay 8c0c87b9
$ wahrgus evaluate dataset.yaml
```

---

# 17. Event log

Every significant transition should be recorded.

```text
INVESTIGATION_CREATED
        ↓
HYPOTHESES_GENERATED
        ↓
RESEARCH_PLAN_CREATED
        ↓
TASK_STARTED
        ↓
TOOL_CALLED
        ↓
EVIDENCE_RECEIVED
        ↓
HYPOTHESIS_UPDATED
        ↓
CONTRADICTION_FOUND
        ↓
NEW_TASK_CREATED
        ↓
INVESTIGATION_COMPLETED
```

This gives you a complete audit trail.

Conceptually:

```text
event log
────────────────────────────────────
08:44 investigation_created
08:45 hypotheses_generated
08:45 research_plan_created
08:46 task_started
08:46 web_search
08:46 evidence_received
08:47 hypothesis_updated
...
```

---

# 18. Reliability boundaries

Eventually the harness should own:

```text
                  SAFETY / RELIABILITY
                         │
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
   Validation          Budgets          Retries
       │                 │                 │
       ▼                 ▼                 ▼
 Structured           Tool calls        Model calls
 outputs              / time            / failures
```

An agent should never be able to silently:

* invent a tool,
* bypass validation,
* mutate state directly,
* exceed its budget,
* skip provenance,
* declare the investigation finished arbitrarily.

---

# 19. Main data flow

```text
USER QUESTION
      │
      ▼
InvestigationState
      │
      ▼
HypothesisAgent
      │
      ▼
Hypotheses + predictions
      │
      ▼
ResearchPlanner
      │
      ▼
ResearchTasks
      │
      ▼
ResearchExecutor
      │
      ▼
Raw observations
      │
      ▼
Evidence / Provenance
      │
      ├─────────────────────┐
      ▼                     ▼
HypothesisUpdater    ContradictionAgent
      │                     │
      └──────────┬──────────┘
                 ▼
       Updated InvestigationState
                 │
                 ▼
          Next-step decision
                 │
          ┌──────┴───────┐
          ▼              ▼
      investigate       stop
                           │
                           ▼
                      synthesis
```

---

# 20. The architecture in one sentence

> **Wahrgus is a stateful agent runtime in which constrained agents generate, investigate, challenge, and revise competing hypotheses, while a deterministic orchestrator controls state, tool execution, provenance, budgets, and the investigation lifecycle.**

---

# 21. Recommended implementation order

```text
1. HypothesisAgent
       ✓ already built

2. InvestigationState
       ↓

3. Orchestrator
       ↓

4. ResearchPlanner
       ✓ already built

5. ResearchTask / ResearchResult
       ↓

6. ResearchExecutor
       ↓

7. Evidence + Provenance
       ↓

8. HypothesisUpdater
       ↓

9. ContradictionAgent
       ↓

10. Stop / verification logic
       ↓

11. CLI status / replay
       ↓

12. Evaluation harness
```

The **minimum viable autonomous loop** is therefore:

```text
Hypothesize
    ↓
Plan
    ↓
Research
    ↓
Update
```

Then the distinctive part of Wahrgus becomes:

```text
                 ┌───────────────┐
                 │   Hypothesis  │
                 └───────┬───────┘
                         │
                         ▼
                 ┌───────────────┐
                 │    Research   │
                 └───────┬───────┘
                         │
                         ▼
                 ┌───────────────┐
                 │    Update     │
                 └───────┬───────┘
                         │
                         ▼
                 ┌───────────────┐
                 │  Contradict   │
                 └───────┬───────┘
                         │
                         └──────────→ repeat
```

That is the **architectural core** worth keeping in your reference notes.

