"""The git write path of a mission (SPEC-01 section 6; MO-14).

- `mission_branches`: the `mc/{run}/{unit}` branch a mission writes, and the ref prefix the
  pre-push guard allows.
- `ports`: the scoped git credential source and the repository host (branch lookup, pull
  requests, branch commits); concrete GitHub adapters live in `adapters/github`.
- `branch_heads`: the `mc.mission_branch_head.v1` head SHA artifact every lane records, and
  the `Claude-Session:` trailer correlation for Claude cloud commits.
- `repo_pr`: the `repo_pr` Governed Effect that opens a mission branch's draft pull request.

Import the submodules directly.
"""
