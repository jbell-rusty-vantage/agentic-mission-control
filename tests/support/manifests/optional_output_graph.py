"""A three-stage Stage Graph whose producer adds an optional plain-text output.

``discover`` promises a required structured ``discovery`` record (bound schema) and an optional
plain-text ``optional_background``. ``synthesize`` consumes both, the background as an optional
input; ``finalize`` consumes the report. It is the smallest graph in which launch eligibility
must tell the optional text output apart from the exact-bound structured outputs around it.
"""

from __future__ import annotations

from typing import Any

RECORD_REF = "graph_record@1"
RECORD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary"],
    "properties": {"summary": {"type": "string"}},
}
CONSUMERS = frozenset({"synthesize", "finalize"})

MANIFEST = f"""\
manifest: mission/v1
mission:
  key: optional-output-graph
  title: Optional plain-text output graph
  application: biotech
  goals:
    - key: discovery
      description: Produce the discovery record
      criteria:
        - {{ key: recorded, description: Fulfill the schema, evidence: [discovery],
             acceptance: {{ schema: {RECORD_REF} }} }}
    - key: report
      description: Produce the report record
      criteria:
        - {{ key: recorded, description: Fulfill the schema, evidence: [report],
             acceptance: {{ schema: {RECORD_REF} }} }}
    - key: summary
      description: Produce the summary record
      criteria:
        - {{ key: recorded, description: Fulfill the schema, evidence: [summary],
             acceptance: {{ schema: {RECORD_REF} }} }}
  environment:
    lane: deep_agents
    model: {{ profile: frontier.default }}
    sandbox: {{ profile: research.standard, egress: [pubmed] }}
    capabilities:
      - {{ search: "pubmed literature retrieval", kind: mcp_server, as: pubmed,
           tools: [search_articles] }}
    budget: {{ usd: 10, tokens: 500000, wall_clock: 1h, tool_calls: 40 }}
    governors: {{ depth: 2, fan_out: 4, iterations: 8, patience: 2 }}
    side_effects: [read_only, workspace_write]
  program:
    key: root
    behavior: stage_graph
    objectives: [discovery, report, summary]
    nodes:
      - key: discover
        behavior: agent_executor
        objectives: [discovery]
        instruction: Find the sources; background notes are optional.
        outputs:
          - {{ name: discovery, schema: {RECORD_REF}, enforcement: required }}
          - {{ name: optional_background, form: text, enforcement: optional }}
      - key: synthesize
        behavior: agent_executor
        objectives: [report]
        instruction: Synthesize the discovery; use background notes only when present.
        inputs:
          - {{ name: discovery, from: discover.discovery, expand: materialize }}
          - {{ name: background, from: discover.optional_background, expand: materialize,
               required: false }}
        outputs:
          - {{ name: report, schema: {RECORD_REF}, enforcement: required }}
      - key: finalize
        behavior: agent_executor
        objectives: [summary]
        instruction: Summarize the report.
        inputs:
          - {{ name: report, from: synthesize.report, expand: materialize }}
        outputs:
          - {{ name: summary, schema: {RECORD_REF}, enforcement: required }}
  controls:
    commands_allowed: [pause, resume, cancel]
"""
