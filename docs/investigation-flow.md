# Investigation Flow

This diagram summarizes the implemented Wahrgus investigation flow from
`src/core/orchestrator/investigator.py`, with agent and tool responsibilities from
`src/core/agent/agent.py` and `src/tools/executor.py`.

```text
+----------------------------------------------------------------+
|                         USER QUESTION                          |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
|                      INVESTIGATION STATE                       |
| question | clarification | hypotheses | plans | tasks          |
| evidence | evaluations | contradictions | decision | events    |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
| BOOTSTRAP: QuestionAnalyzerAgent                               |
| identifies investigation type, missing information, and status |
+-------------------------------+--------------------------------+
                                |
                                v
                    NEEDS_CLARIFICATION?
                    /                  \
                  yes                   no
                  |                      |
                  v                      |
        +---------------------+          |
        | Ask user for input  |          |
        +----------+----------+          |
                   |                     |
                   +----------+----------+
                              |
                              v
+----------------------------------------------------------------+
| HypothesisAgent                                                |
| creates competing hypotheses, confidence, and predictions      |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
| ResearchPlanner                                                |
| creates immutable ACTIVE research plans (RP-001, RP-002, ...)  |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
| ResearchTaskAgent                                              |
| converts ACTIVE plans into concrete tool tasks                 |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
| ToolExecutor                                                   |
| validates the registered tool, executes it, saves trace        |
| current tool: WebSearch (Tavily)                               |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
| Evidence                                                       |
| task results are attached to task records and stored in state  |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
| EvidenceEvaluator                                              |
| evaluates each evidence item for relevance and impact          |
+-------------------------------+--------------------------------+
                                |
              +-----------------+-----------------+
              |                                   |
              v                                   v
+----------------------------+        +--------------------------+
| Neutral or no relevant     |        | Supporting, weakening,   |
| evidence                   |        | or contradictory signal  |
|                            |        |                          |
| neutral_streak += 1        |        | update_hypothesis()      |
| cap: 2 consecutive rounds  |        | - transition plan status |
+-------------+--------------+        | - update confidence      |
              |                       +-------------+------------+
              v                                     |
      streak reaches 2?                             |
              |                                     |
             yes                                    |
              |                                     |
              v                                     |
        force_finish = true                         |
              |                                     |
              +-------------------+-----------------+
                                  |
                                  v
+----------------------------------------------------------------+
| DECISION LOOP                                                  |
| up to max_iterations; an empty decision is an error            |
+-------------------------------+--------------------------------+
                                |
                                v
                          force_finish?
                           /          \
                         yes            no
                          |              |
                          v              v
                         exit    +----------------+
                                 | DecisionAgent  |
                                 +-------+--------+
                                         |
             +----------------+----------+----------+----------------+
             |                |                     |                |
             v                v                     v                v
           FINISH        REFINE_PLAN             REASSESS        CHALLENGE
             |                |                     |                |
             |           new plans +           new tasks for   ContradictionAgent
             |           new tasks             ACTIVE plans          |
             |                |                     |         contradiction?
             |                |                     |          yes /    \ no
             |                |                     |           |        |
             |                |                     |     new plans +    |
             |                |                     |     new tasks      +--> next decision
             |                |                     |           |
             |                +---------------------+-----------+
             |                                      |
             |                                execute tasks
             |                                      |
             |                                evaluate evidence
             |                                      |
             |                               next decision
             |                                      |
             |                       +--------------+
             |                       |
             |                       v
             |                 repeat loop
             v
            exit
+----------------------------------------------------------------+
                                |
                                v
+----------------------------------------------------------------+
| LOOP EXIT                                                      |
| FINISH | force finish | max iterations | error                 |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
| ReportAgent                                                    |
| proposes title, abstract, hypothesis verdicts, evidence, and   |
| conclusion                                                     |
+-------------------------------+--------------------------------+
                                |
                                v
+----------------------------------------------------------------+
| Harness writes report.md                                       |
| owns section order, final confidence values, references, and   |
| trace files under the session trace directory                  |
+----------------------------------------------------------------+
```

## Ownership boundary

Agents propose structured outputs. The orchestrator owns state transitions,
plan lifecycle status, tool execution, confidence updates, retries, budgets,
stopping conditions, report rendering, and trace persistence.
