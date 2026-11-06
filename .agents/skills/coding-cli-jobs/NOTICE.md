# Sources and attribution

First-party implementation based on SPEC-08 and the repository's research notes, checked offline against Claude Code 2.1.296, Codex 0.162.1 and Cursor 2026.10.01-14929f9. Tests/fixtures reproduce the 13 **synthetic** examples in `docs/specs/archive/materialization-observation-2026-10/research/cli-adapters.md`; they are not captured model output.

Gotcha/pattern references (MIT): [skills-directory/skill-codex](https://github.com/skills-directory/skill-codex) (stdin EOF), [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (headless outputs), [daymade/claude-code-skills](https://github.com/daymade/claude-code-skills) (subscription guards), [steipete/agent-scripts](https://github.com/steipete/agent-scripts) (routing), [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin) (buffering/trust). No third-party implementation or prose is vendored.

[openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc), Apache-2.0, is recommended separately. [freema/cursor-plugin-cc](https://github.com/freema/cursor-plugin-cc), MIT, is optional after review. Trail of Bits second-opinion (CC-BY-SA-4.0) is linked only; no text is copied.
