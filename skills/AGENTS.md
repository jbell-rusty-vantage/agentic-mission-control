<!-- BEGIN:sdlc-module id=skills -->
# Shipped skill bundles
Shipped agent skill bundles with digest manifests. Includes the mission-control router skill, the author, catalog, compose, intervene and observe skills, mc-signals, the mc-cognition-* skills and the Biotech knowledge charter. Method skills imported from sibling repositories live in packages/mission-control-db-contract/bundle-sources/imported, not here.
Entrypoints:
- mission-control/
- mc-signals/
- biotech-knowledge-charter/
- mc-cognition-cite-and-verify/
- mc-cognition-code-review/
- mc-cognition-diagnosing-bugs/
- mc-cognition-ingest/
- mc-cognition-knowledge-services/
- mc-cognition-pr/
- mc-cognition-research/
Also: mc-cognition-tdd/, mission-control-author/, mission-control-catalog/, mission-control-compose/, mission-control-intervene/, mission-control-observe/
Tests: tests/unit/skills
Invariants:
- A bundle's manifest.json digests must match the files on disk.
- A coordinator bundle's references/guide-*.md and whoami.md are generated from the guide: edit the guide page, never the reference.
- A coordinator SKILL.md carries judgment only; every missionctl command a bundle names is in the CLI's argparse tree.
Explained by (docs/knowledge): coordinator-surface, signal-ingress
Decided by (docs/adr): ADR-0015, ADR-0033, ADR-0043, ADR-0045, ADR-0049
Verify: make skills-check; make skills-references (rewrites references/guide-*.md from the guide); make skills-manifest (rewrites digests after editing a bundle)
<!-- END:sdlc-module -->
