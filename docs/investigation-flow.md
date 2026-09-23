# Investigation Flow

This diagram summarizes the implemented Wargs investigation flow from
`src/core/orchestrator/investigator.py`, with agent and tool responsibilities from
`src/core/agent/agent.py` and `src/tools/executor.py`.

```mermaid
flowchart TD
    Q["USER QUESTION"]

    Q --> STATE["INVESTIGATION STATE<br/>question | clarification | hypotheses | plans | tasks<br/>evidence | evaluations | contradictions | decision | events"]

    STATE --> BOOT["BOOTSTRAP: QuestionAnalyzerAgent<br/>identifies investigation type, missing information, and status"]

    BOOT --> NC{"NEEDS_CLARIFICATION?"}
    NC -->|yes| ASK["Ask user for input"]
    NC -->|no| HYP
    ASK --> HYP["HypothesisAgent<br/>creates competing hypotheses, confidence, and predictions"]

    HYP --> PLAN["ResearchPlanner<br/>creates immutable ACTIVE research plans (RP-001, RP-002, ...)"]
    PLAN --> TASK["ResearchTaskAgent<br/>converts ACTIVE plans into concrete tool tasks"]
    TASK --> EXEC["ToolExecutor<br/>validates the registered tool, executes it, saves trace<br/>current tool: WebSearch (Tavily)"]
    EXEC --> EV["Evidence<br/>task results are attached to task records and stored in state"]
    EV --> EVAL["EvidenceEvaluator<br/>evaluates each evidence item for relevance and impact"]

    EVAL --> NEUTRAL["Neutral or no relevant evidence<br/>neutral_streak += 1 (cap: 2 consecutive rounds)"]
    EVAL --> SIGNAL["Supporting, weakening, or contradictory signal<br/>update_hypothesis(): transition plan status, update confidence"]

    NEUTRAL --> STREAK{"streak reaches 2?"}
    STREAK -->|yes| FF["force_finish = true"]
    STREAK -->|no| LOOP
    SIGNAL --> LOOP

    subgraph LOOP["DECISION LOOP (up to max_iterations; an empty decision is an error)"]
        direction TB
        FF_CHECK{"force_finish?"}
        FF_CHECK -->|yes| EXIT
        FF_CHECK -->|no| DA["DecisionAgent"]
        DA --> FINISH
        DA --> RP["REFINE_PLAN<br/>new plans + new tasks"]
        DA --> RE["REASSESS<br/>new tasks for ACTIVE plans"]
        DA --> CH["CHALLENGE<br/>ContradictionAgent"]
        CH --> CH_FOUND{"contradiction?"}
        CH_FOUND -->|yes| CH_NEW["new plans + new tasks"]
        CH_FOUND -->|no| DA
        RP --> RUN["execute tasks → evaluate evidence"]
        RE --> RUN
        CH_NEW --> RUN
        RUN --> DA
    end

    FF --> FF_CHECK
    FINISH --> EXIT["LOOP EXIT<br/>FINISH | force finish | max iterations | error"]

    EXIT --> REPORT["ReportAgent<br/>proposes title, abstract, hypothesis verdicts, evidence, and conclusion"]
    REPORT --> OUT["Harness writes report.md<br/>owns section order, final confidence values, references,<br/>and trace files under the session trace directory"]
```

## Ownership boundary

Agents propose structured outputs. The orchestrator owns state transitions,
plan lifecycle status, tool execution, confidence updates, retries, budgets,
stopping conditions, report rendering, and trace persistence.
