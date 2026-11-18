"""Scripted cognition for the report-mission acceptance runs.

Each module is a script object for the one LLM double (`tests.support.models.ScriptedChatModel`,
wrapped through `Cognition.model()`): it reads what the real tools answered and decides the next
tool call, so the real Deep Agents graph, tools and host settlement run without spend.

- `stagegraph`: a StageGraph producer registers and submits a report; a consumer reads the exact
  materialized handle (`StageGraphScript`, `StageGraphCognition`, `stagegraph_components`).
- `goal_directed`: a two-iteration GoalDirected executor and verifier (`GoalScript`,
  `GoalCognition`).
- `linked`: a GoalDirected source feeding an independent StageGraph consumer (`LinkedScript`,
  `linked_script`, `linked_components`).
- `linked_repair`: a held linked report repaired from its sealed bytes and findings
  (`linked_repair_script`, `linked_repair_components`).
"""
