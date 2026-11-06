---
name: cited-findings
description: Write research findings with a source for every claim. Use when a mission asks for findings, a summary or a report.
---

# Cited findings

1. Collect sources first. Record each one's title, URL or path, and the date you read it.
2. Write `/workspace/outputs/findings.md` with three sections: `Findings`, `Open questions` and
   `Sources`.
3. End every finding with a bracketed source number, such as `[2]`, that points into `Sources`.
   A finding without a source belongs under `Open questions`.
4. Hand the file to Mission Control with `mc_upload_artifact`, then call `mc_signal` with
   `findings.ready`.
