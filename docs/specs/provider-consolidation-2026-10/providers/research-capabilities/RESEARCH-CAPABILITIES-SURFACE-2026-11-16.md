---
type: Research
title: "Research capabilities as of 2026-11-16: GitHub MCP Server 2.1.0, Context7 MCP 4.7.0, the arXiv servers, and the Knowledge Services executor as a catalog capability"
description: "Dated evidence for the catalog seed mc.catalog.agent-capabilities@1.1.0: the identity, exact version, transports, authentication, licence, maintenance signal, read-only configuration and captured tool list of GitHub's official MCP server and of Context7's, why no arXiv server is seeded, how the Knowledge Services executor's capture, source, schema and guide tools become one catalog capability, what Mission Control cannot yet mount, and the availability table the research skill should be updated from."
tags: [mission-control, providers, capabilities, catalog, mcp, github, context7, arxiv, knowledge-services, research]
status: active
date: 2026-11-16
as_of: 2026-11-16
pins:
  github-mcp-server: "2.1.0"
  "@upstash/context7-mcp": "4.7.0"
  knowledge-verification-executor: "0.1.0 (Knowledge Services 7bc4aee)"
---

# Research capabilities as of 2026-11-16

Evidence for [`mc.catalog.agent-capabilities@1.1.0`](../../../../../packages/mission-control-db-contract/seeds/common/mc.catalog.agent-capabilities-1.1.0.json).
It decides nothing beyond that seed: the proposals in [§7](#proposals) wait for the owner.

**Why.** The research method missions mount (`skill.knowledge-research`, its
[routing table](../../../../../packages/mission-control-db-contract/bundle-sources/imported/knowledge-services/7bc4aee/knowledge-research/references/tools/routing.md#availability))
says "capture every source you rely on" and "Context7 for a first look, GitHub for the file at the
release's commit". On 2026-11-15 the catalog offered neither: GitHub, Context7 and arXiv existed only as
test fixtures, and no mission could reach the capture path.

## How to read this note

Every observation was made on **2026-11-16**. Each finding has a label, a source and the version read.

| Label | Meaning |
| --- | --- |
| **[REG]** | The record a registry serves (the official MCP registry, npm, PyPI, the GitHub API, GHCR), fetched without credentials |
| **[DOCS]** | The provider's documentation in the repository at the pinned tag |
| **[SRC]** | Read in source: the provider's at the pinned tag, or this repository's and Knowledge Services' at the commit named |
| **[PROBE]** | Run on this machine; the command and the result are in [§6](#probes) |
| **[INF]** | My inference from the lines it names |
| **[NF]** | Looked for and not found |

Raw records (registry responses, the three `tools/list` snapshots, the comparison scripts) are under
`.scratch/provider-research/research-capabilities/2026-11-16/`, which is not committed.

<a id="bindings"></a>
## 1. The bindings chosen

| Capability | Server | Version | Transport seeded | Authentication | Read-only configuration | Tool list |
| --- | --- | --- | --- | --- | --- | --- |
| `mcp.github` | GitHub's official MCP server, registry name `io.github.github/github-mcp-server` | 2.1.0, commit `4bcdcdf8d7beee98c9448e73e257308280924cc4`, image `ghcr.io/github/github-mcp-server@sha256:f6056fc10bfffcc8c81a6417a2e9ca12808647e8dd6049642a4feaadee0e0f8a` | stdio: `github-mcp-server stdio --read-only --toolsets=repos,issues,pull_requests` | a token in `GITHUB_PERSONAL_ACCESS_TOKEN` | the server's own `--read-only` mode and three toolsets | captured, 22 tools |
| `mcp.context7` | Context7 by Upstash, registry name `io.github.upstash/context7` | 4.7.0, `npm:@upstash/context7-mcp@4.7.0` | stdio: `npx -y @upstash/context7-mcp@4.7.0`; remote `https://mcp.context7.com/mcp` as an overlay | optional API key in `CONTEXT7_API_KEY` | the server has only two tools, both read-only | captured, 2 tools |
| arXiv | none | - | - | - | - | not seeded ([§4](#arxiv)) |
| `mcp.knowledge-capture` | the Knowledge Services executor, `knowledge-verification-executor` | 0.1.0 at Knowledge Services `7bc4aeec77c645f41bb0f550f6a9626c3ef24cf0` | Streamable HTTP, `/mcp` | a static token in `VERIFY_EXECUTOR_TOKEN`, sent as `Authorization: Bearer` | an allowlist of 19 of the 40 tools | captured, 40 tools |

The upstream identifier of each row follows the accepted capability direction (CAP-D1, one identifier both
catalogs compare by equality): scheme `mcp_registry` with the registry name for GitHub and Context7, scheme
`belllabs` with the minted slug `knowledge-services/verification-executor` for the executor.
`SourceProvenance.source` already admits both words. The package coordinates (`oci`, `npm`, `git`) are
the `package_pin` of each row.

<a id="github"></a>
## 2. GitHub

| ID | Finding | Label and source | Impact |
| --- | --- | --- | --- |
| GH-1 | The official server is `github/github-mcp-server`, MIT, not archived, pushed 2026-11-16; latest release `v2.1.0` published 2026-11-03T11:11:41Z | [REG] `https://api.github.com/repos/github/github-mcp-server` and `/releases/latest` | the pin |
| GH-2 | The official MCP registry lists it as `io.github.github/github-mcp-server` 2.1.0, status active, published 2026-11-03: one OCI package `ghcr.io/github/github-mcp-server:2.1.0` over stdio and one remote, `https://api.githubcopilot.com/mcp/`, Streamable HTTP with a secret `Authorization` header | [REG] `https://registry.modelcontextprotocol.io/v0/servers/io.github.github%2Fgithub-mcp-server/versions/2.1.0` | identifier scheme `mcp_registry` |
| GH-3 | Tag `v2.1.0` is an annotated tag on commit `4bcdcdf8d7beee98c9448e73e257308280924cc4`; the release binary reports the same commit | [REG] `/git/ref/tags/v2.1.0`, `/git/tags/7c48164c…`; [PROBE] P1 | `commit_digest` |
| GH-4 | The image index of tag `2.1.0` (and `v2.1.0`) is `sha256:f6056fc10bfffcc8c81a6417a2e9ca12808647e8dd6049642a4feaadee0e0f8a`; the image's entrypoint is the binary and its default argument is `stdio` | [REG] `https://ghcr.io/v2/github/github-mcp-server/manifests/2.1.0` (anonymous pull token); [SRC] `Dockerfile` at `v2.1.0` | `package_pin` |
| GH-5 | The release ships checksummed binaries; `github-mcp-server_Windows_x86_64.zip` is `sha256:ddce2749…e9d3` in both the release record and `github-mcp-server_2.1.0_checksums.txt` | [REG] the release assets; [PROBE] P1 | the binary that was run |
| GH-6 | Local configuration: `--toolsets` (`GITHUB_TOOLSETS`), `--tools`, `--exclude-tools`, `--read-only` (`GITHUB_READ_ONLY`), `--lockdown-mode`. Read-only "acts as a strict security filter that takes precedence over any other configuration, by disabling write tools even when explicitly requested". With no configuration the default toolsets are `context`, `issues`, `pull_requests`, `repos`, `users` | [DOCS] `docs/server-configuration.md` and `README.md` at `v2.1.0` | the launch template |
| GH-7 | Remote configuration: headers `X-MCP-Toolsets`, `X-MCP-Tools`, `X-MCP-Readonly`, `X-MCP-Lockdown`; URL paths `/readonly`, `/x/all/readonly`, `/x/{toolset}/readonly`. "`{toolset}` can only be a single toolset, not a comma-separated list. To combine multiple toolsets, use the `X-MCP-Toolsets` header instead" | [DOCS] `docs/remote-server.md` at `v2.1.0` | the remote endpoint is not seeded (MC-5) |
| GH-8 | Since 2.x the stdio server starts with no token: official builds carry a registered OAuth application, and the tool middleware "authorizes the session lazily, on the first tool call". `GITHUB_PERSONAL_ACCESS_TOKEN`, when set, takes precedence and skips OAuth | [DOCS] `docs/oauth-login.md`; [SRC] `internal/ghmcp/oauth.go` `createOAuthToolMiddleware`, `cmd/github-mcp-server/main.go` at `v2.1.0` | `tools/list` could be captured with no credential |
| GH-9 | A classic token (`ghp_`) makes the server read the token's scopes at start with one HEAD request and hide tools the scopes do not cover; fine-grained and app tokens are not filtered. Read-only tools that need only `repo` or `public_repo` are always listed | [DOCS] `docs/scope-filtering.md` at `v2.1.0` | [INF] a deployment's list equals the captured one for a fine-grained read-only token; a classic token with fewer scopes may list fewer tools, which the Deep Agents lane reports as drift (MC-1) |
| GH-10 | With `--read-only --toolsets=repos,issues,pull_requests` the server lists 22 tools, every one annotated `readOnlyHint: true`: `get_commit`, `get_file_contents`, `get_label`, `get_latest_release`, `get_release_by_tag`, `get_tag`, `issue_read`, `list_branches`, `list_commits`, `list_issue_fields`, `list_issue_types`, `list_issues`, `list_pull_requests`, `list_releases`, `list_repository_collaborators`, `list_tags`, `pull_request_read`, `search_code`, `search_commits`, `search_issues`, `search_pull_requests`, `search_repositories` | [PROBE] P1 | the seeded tool list |
| GH-11 | Those three toolsets are the smallest set that covers the research method: files at a commit, commits, tags and releases and code search are `repos`; issue reads and search are `issues`; pull request reads and search are `pull_requests`. The 22 tools equal the tools of those three sections of the versioned README that are read-only in `pkg/github/__toolsnaps__`; 11 match their snapshot in description and input schema, and the other 11 differ only by the `x-mcp-header` annotations the running server adds to its `owner` and `repo` parameters | [PROBE] P2; [DOCS] `README.md` tools section at `v2.1.0` | the capture, not the snapshot files, is the seeded list |
| GH-12 | "Lockdown mode is a best-effort content filter, not a security boundary" | [DOCS] `docs/remote-server.md` at `v2.1.0` | not seeded; a deployment may add `--lockdown-mode`, which changes no tool |

**Decided by:** GH-2 (the registry record is the identity), GH-6 with GH-10 (read-only is the server's own
mode, so the catalog needs no allowlist), GH-7 (the remote endpoint cannot be narrowed to these toolsets
by URL alone).

<a id="context7"></a>
## 3. Context7

| ID | Finding | Label and source | Impact |
| --- | --- | --- | --- |
| C7-1 | `@upstash/context7-mcp` latest is 4.7.0, published 2026-11-12T09:04:46Z, MIT, node `>=20.18.1`, `mcpName` `io.github.upstash/context7`, with an npm registry signature and no provenance attestation; eight releases between 2026-10-13 and 2026-11-12 | [REG] `https://registry.npmjs.org/@upstash%2Fcontext7-mcp` | the pin; a fast-moving package, so the pin ages quickly |
| C7-2 | The official MCP registry lists `io.github.upstash/context7` 4.7.0, active, published 2026-11-12: npm over stdio with the secret environment variable `CONTEXT7_API_KEY`, and a remote `https://mcp.context7.com/mcp`, Streamable HTTP, header `Authorization` ("Accepts \"Bearer <key>\" or the raw key") | [REG] `https://registry.modelcontextprotocol.io/v0/servers/io.github.upstash%2Fcontext7/versions/4.7.0` | identifier scheme `mcp_registry`; the cursor_cloud overlay |
| C7-3 | The key is optional: "Context7 API Key (Optional) for higher rate limits and private repositories". The stdio server started and listed its tools with no key | [DOCS] `README.md` in the 4.7.0 package; [PROBE] P3 | `CONTEXT7_API_KEY` is declared as a name; whether a deployment requires it is its choice |
| C7-4 | The server lists two tools, `resolve-library-id` and `query-docs`, both annotated `readOnlyHint: true`, `destructiveHint: false`, `openWorldHint: true`. The test fixture's `context7_search` and `context7_docs` are Mission Control wrappers over the HTTP interface, not these tools | [PROBE] P3; [SRC] `tests/fixtures/aieng_web_tools.py` | the seeded tool list; the research skill's playbook can now name the two tools |
| C7-5 | The tool descriptions tell the agent to send the query to the Context7 API and to keep secrets and proprietary code out of it | [PROBE] P3 | a research node's queries leave the deployment; the data class of a mission decides whether this server may be mounted |
| C7-6 | The remote endpoint's tool list | [NF] not requested: only the local package was run | cursor_cloud is `unqualified` |

**Decided by:** C7-2 (registry identity and both transports), C7-4 (two read-only tools, so no allowlist),
C7-1 (exact npm version; the worker's pin file already launches npm modules, MC-3).

<a id="arxiv"></a>
## 4. arXiv

| ID | Finding | Label and source | Impact |
| --- | --- | --- | --- |
| AX-1 | The official MCP registry holds 17 latest entries matching `arxiv`. None is published under an arXiv namespace. Ten are remote-only endpoints run by individuals or unnamed operators; seven name a package, of which I examined the two general-purpose servers with the clearest maintenance record (AX-2, AX-4) | [REG] `https://registry.modelcontextprotocol.io/v0/servers?search=arxiv` | no first-party server exists |
| AX-2 | `io.github.blazickjp/arxiv-mcp-server`: PyPI `arxiv-mcp-server` 0.8.2, uploaded 2026-10-08, Apache-2.0, Python `>=3.11`, 41 releases, three of them between 2026-10-03 and 2026-10-08; repository 3,282 stars, pushed 2026-11-14, owner type User, 204 of the top contributors' 214 commits by the owner; no published advisory | [REG] `https://pypi.org/pypi/arxiv-mcp-server/json`, `https://api.github.com/repos/blazickjp/arxiv-mcp-server`, `/contributors`, `https://api.github.com/advisories?affects=arxiv-mcp-server` | meets "maintained, pinned, permissive"; one maintainer |
| AX-3 | Its 0.8.2 source registers 19 tools, among them `download_paper`, `watch_topic`, `unwatch_topic`, `reindex` and `semantic_search`, keeps papers, watches and an index under a storage path on the host, calls `api.semanticscholar.org` besides arXiv, and has 15 runtime dependencies including a web server stack | [SRC] the 0.8.2 sdist (`sha256:e27bb342…8722`), `src/arxiv_mcp_server/tools/`, `config.py`, `PKG-INFO`; transcribed, not run | not a read-only server; state on the worker |
| AX-4 | `io.github.cyanheads/arxiv-mcp-server`: npm `@cyanheads/arxiv-mcp-server` 1.8.2, published 2026-11-08, Apache-2.0, node `>=24`, 47 versions since 2026-03-30; repository 7 stars; dependencies include `better-sqlite3` and `node-cron`; its registry record also names the author-operated endpoint `arxiv.caseyjhand.com` | [REG] `https://registry.npmjs.org/@cyanheads%2Farxiv-mcp-server`, `https://api.github.com/repos/cyanheads/arxiv-mcp-server` | too little outside review; the public endpoint is a third party |
| AX-5 | arXiv's own interface is the export API, `http://export.arxiv.org/api/query` with `search_query` and `id_list`; its terms ask for "no more than one request every three seconds" and "a single connection at a time" | [DOCS] `https://info.arxiv.org/help/api/user-manual.html`, `https://info.arxiv.org/help/api/tou.html` | the first-party route |
| AX-6 | The seeded `mcp.firecrawl` 3.28.2 lists the paper-index tools (`firecrawl_research_search_papers`, `firecrawl_research_related_papers`, `firecrawl_research_inspect_paper`, `firecrawl_research_read_paper`) | [SRC] the [Firecrawl fixture](../../../../../tests/fixtures/mcp/mcp.firecrawl.tools.json) (transcribed 2026-10-07) | discovery and reading are already seeded |

**Verdict: not seeded.** One candidate (AX-2) passes the three stated criteria. I would still not put it on
a production worker today, for reasons the criteria do not cover: it is not arXiv's, it has one maintainer
and a release cadence that makes any pin stale within weeks (AX-2), it is stateful and partly writing
(AX-3), and it adds nothing evidence-bearing that the method does not already have. The method's own
route is the Firecrawl paper index first (AX-6), then arXiv's record of the exact version; with the
capture path that second step is a capture of `https://arxiv.org/abs/<id>v<n>` or of the export API
response (AX-5), which yields exact bytes and a digest and needs no third-party server. A search tool over
the export API as a first-party Mission Control tool is proposal IP-012. If the owner wants the community
server anyway, the pin would be `pypi:arxiv-mcp-server==0.8.2` (wheel `sha256:11cb0f60…32f7`) with an
allowlist of `search_papers` and `get_abstract`, after a capture of its `tools/list`.

<a id="capture-path"></a>
## 5. The capture path

### 5.1 The executor (Knowledge Services at `7bc4aee`, read only)

| ID | Finding | Label and source | Impact |
| --- | --- | --- | --- |
| KS-1 | `knowledge-verify serve [--port 4310] [--host 127.0.0.1]` serves `POST /mcp`, Streamable HTTP, stateless (one server per request, JSON responses); `knowledge-verify mcp-stdio` serves the same tools over stdio. The port defaults to `VERIFY_PORT` or 4310 | [SRC] `apps/verification-executor/src/index.ts`, `src/http.ts` | transport `streamable_http`; the catalog default endpoint |
| KS-2 | Authentication is an optional static token: with `--token` or `VERIFY_EXECUTOR_TOKEN` set, every route but `/health` and the knowledge-operation routes requires `Authorization: Bearer <token>`. The token grants every tool alike | [SRC] `src/http.ts` `createHttpServer`, `src/index.ts` | `header_refs: {Authorization: VERIFY_EXECUTOR_TOKEN}`; the token is no per-tool boundary |
| KS-3 | The five knowledge-operation tools (`knowledge_operation_invoke`, `_get`, `_cancel`, `knowledge_receipt_get`, `knowledge_describe`) need a second, issuer credential in the header `x-knowledge-operation-credential` | [SRC] `src/knowledge-operation/mcp-tools.ts`, `src/http.ts` | excluded: Mission Control mints that credential only for its governed knowledge tools |
| KS-4 | `knowledge_guide` and the ten `verify_*` tools are always registered; the 24 operation tools (`schema_*`, `db_*`, `ingest_*`, `checkpoint_*`, `source_*`, `artifact_get`) only when the executor has its knowledge database and schema workspace configured | [SRC] `src/mcp.ts` `createVerificationMcpServer`, `registerKnowledgeTools`; `src/serve.ts` | the captured list is that of an executor configured for the AI Engineer knowledge base; a Biotech executor's list was not observed |
| KS-5 | The executor running on this machine reports server `knowledge-verification-executor` 0.1.0 and lists 40 tools, with no annotations, and answered `tools/list` with no token | [PROBE] P4 | the seeded tool list; `read_only_hint` is null on every row |
| KS-6 | The MCP endpoint has no way to list fewer tools: one server with every tool is built per request. The executor's scoped access (`/scoped/invoke`, per-grant `allowedOperations`) is a different protocol, not MCP | [SRC] `src/http.ts`, `src/access.ts` | a narrowed mount has to be enforced by the client (MC-1) or built in the executor |
| KS-7 | `verify_capture_fragment` says "Requires durable artifact custody" and runs only on a served executor | [PROBE] P4 (its description); [SRC] the research skill's [verification reference](../../../../../packages/mission-control-db-contract/bundle-sources/imported/knowledge-services/7bc4aee/knowledge-research/references/verification.md#availability) | the stdio transport, a second executor inside the worker, is not the capture path |

**The allowlist (19).** `knowledge_guide`; `schema_search`, `schema_get`, `schema_manifest`;
`source_discover`, `source_import`, `source_attempt`, `source_reconcile`, `source_select`;
`verify_capture_source`, `verify_capture_file`, `verify_supported_media_types`, `verify_list_captures`,
`verify_read_capture`, `verify_search_capture`, `verify_locate_quote`, `verify_capture_fragment`,
`verify_register_artifact`, `verify_get_artifact`.

**Withheld (21), and why.** `ingest_plan`, `ingest_apply`, `ingest_receipt` (knowledge writes and their
ledger); the five knowledge-operation tools (KS-3); `db_head`, `db_read_intent`, `db_sql_readonly`,
`db_explain` (direct database reads: the recorded read is the governed `tool.knowledge-read-intent`);
the six `checkpoint_*` tools (host session state); `artifact_get` (ledger rows); `schema_materialize`
(writes a directory on the executor host); `source_prepare_captured` ("requires a trusted preparation
host" and starts durable preparation). Two calls are judgment, not the owner's words: `source_discover`
is kept although it spends the executor's own search-provider key outside Mission Control's budget, and
`source_prepare_captured` is withheld although it is a `source_*` tool.

### 5.2 What Mission Control expresses, and what it does not

| ID | Finding | Label and source | Impact |
| --- | --- | --- | --- |
| MC-1 | The Deep Agents materializer connects a remote server with `Authorization: Bearer` of its first credential reference and no other header, gives a stdio server only its credential references as environment, and requires the names of the tools a server lists to equal the bound tools exactly ("MCP server tool filter drift") | [SRC] [`materializer.py`](../../../../../src/mission_control/adapters/deep_agents/materializer.py) `_load_mcp_tools` | the executor's authentication fits; a catalog allowlist is not enforced; a server that lists more than the binding is refused |
| MC-2 | A deployment-supplied endpoint is expressible on the Deep Agents lane: `mc.manifest_launch_bindings` `capabilities[<id>]` may hold an inline `mcp_server` component with `transport: streamable_http`, its own `endpoint` and `credential_refs`; only the row's digest is compared with the catalog | [SRC] [`manifest_launch_inputs.py`](../../../../../src/mission_control/application/authoring/manifest_launch_inputs.py) `CapabilityComponentBinding`, [`compile.py`](../../../../../src/mission_control/adapters/deep_agents/compile.py) `_component` | endpoint and authentication need no new model field |
| MC-3 | A production worker launches only what its pin file describes: `PinnedMCPServer` is one stdio node module (`module_locator`, `module_digest`, `package.json` name and version) run with the deployment's node. `PinnedCapabilityAssetVerifier.verify_launch` refuses every other component unless it was registered through `DeploymentCapabilityComponents.mcp_servers`, which only test and qualification compositions pass | [SRC] [`capability_pins.py`](../../../../../src/mission_control/adapters/capabilities/capability_pins.py), [`runtime_ports.py`](../../../../../src/mission_control/adapters/operations/runtime_ports.py), [`deployment_composition.py`](../../../../../src/mission_control/adapters/temporal/deployment_composition.py), [`manifests.py`](../../../../../src/mission_control/bootstrap/manifests.py) | `mcp.context7` (npm) fits; `mcp.github` (a Go binary) and `mcp.knowledge-capture` (remote) cannot be served by a production worker yet |
| MC-4 | The pin writer lists and pins exactly two servers by name, Firecrawl and Tavily, with every tool each lists | [SRC] [`pin_research_capabilities.py`](../../../../../scripts/pin_research_capabilities.py) | pinning `mcp.context7` needs a row there |
| MC-5 | The host projection of the file lanes takes a remote URL from the definition or the overlay's `url` and headers from `header_refs` (secret references; `Authorization` gets a `Bearer` prefix). `url_ref` is in the overlay vocabulary and no projector reads it; no field carries a static header | [SRC] [`projections.py`](../../../../../src/mission_control/application/agentic_components/projections.py) `mcp_launch`, [`host_support.py`](../../../../../src/mission_control/domain/capabilities/host_support.py) | GitHub's remote endpoint cannot be given `X-MCP-Toolsets` and `X-MCP-Readonly`; an endpoint named by a deployment setting is not projected |
| MC-6 | A plugin a Deep Agents node selects has no launch binding: its first member is refused `ITEM_UNSUPPORTED_ON_LANE`, and the launch author creates every selected item required | [SRC] `compile.py` `_unsupported`, `manifest_launch_inputs.py`; the unit test `test_a_node_plugin_is_refused_at_its_row_after_hooks` | [INF] a Deep Agents mission pins the servers under `environment.capabilities`; a plugin pin serves the file lanes and a child's seeds. The `research-report` template selects two plugins on this lane, so it compiles and would be refused at launch resolution; not run |
| MC-7 | Manifest compile blocks a pin whose row does not declare the node's lane `supported` (`pin_lane_unsupported`); `unqualified` blocks too, and an optional plugin member is checked the same way | [SRC] [`manifest_service.py`](../../../../../src/mission_control/application/authoring/manifest_service.py) | an `unqualified` capability cannot be pinned by a template or a plugin |

**What follows for `mcp.knowledge-capture`.** The capability model expresses the executor's endpoint and
its authentication (MC-1, MC-2, KS-2). It cannot yet deliver the exclusion the owner asked for: the
executor lists all 40 tools (KS-6) and the Deep Agents lane either refuses a narrower binding or, bound
with all 40, hands the agent `ingest_apply` and `db_sql_readonly` under the same token (MC-1, KS-2). And a
production worker cannot launch a remote server at all (MC-3). The seed therefore declares the row
`unqualified` on the four worker-hosted profiles and `unsupported` on cursor_cloud (a loopback or
deployment-private endpoint is not reachable from a provider's cloud). By MC-7 no manifest can pin it yet,
so it is in no plugin and the `research-report` template is unchanged: adding it to
`plugin.cognition-knowledge` would block every knowledge mission that follows `@latest`.

It becomes mountable with two changes, IP-008 and IP-009 below, and then a revision 2 of the row that
declares `deep_agents` supported, a revision 3 of `plugin.cognition-knowledge` with it as a member, and
the template pin.

<a id="probes"></a>
## 6. Probes

| ID | Command | Result |
| --- | --- | --- |
| P1 | `uv run --no-sync python scripts/capture_mcp_tool_snapshot.py --command <dir>/github-mcp-server.exe --arg=stdio --arg=--read-only --arg=--toolsets=repos,issues,pull_requests --cwd <dir> --output <snapshot>`, the binary unpacked from the release asset `github-mcp-server_Windows_x86_64.zip` after its sha256 matched the published checksum; environment `PATH`, `PATHEXT`, `SYSTEMROOT`, `COMSPEC`, `NO_COLOR`, `CI` only, no token | `github-mcp-server --version`: "Version: 2.1.0, Commit: 4bcdcdf8d7beee98c9448e73e257308280924cc4, Build Date: 2026-11-03T11:04:46Z". Server log: `readOnly=true`, "using requested OAuth scopes for tool filtering". **22 tools.** No browser opened and no login started |
| P2 | `python -I probe_compare_github3.py` over the source archive of `v2.1.0` (`sha256:fb85acd5…705e`, unpacked, never run) and the P1 snapshot | The 22 captured names equal the read-only tools of the README's Issues, Pull Requests and Repositories sections; 11 of 22 equal their `__toolsnaps__` file in description and input schema, 11 differ by `x-mcp-header` only, none otherwise |
| P3 | `npm install @upstash/context7-mcp@4.7.0 --ignore-scripts --no-audit --no-fund --no-save --prefix <dir>`, then `uv run --no-sync python scripts/capture_mcp_tool_snapshot.py --command node.exe --arg=<dir>/node_modules/@upstash/context7-mcp/dist/index.js --cwd <dir> --output <snapshot>`, no key | "Context7 Documentation MCP Server v4.7.0 running on stdio". **2 tools.** Entry module `sha256:f38e50b0…f28f`. A first attempt through `npx -y` timed out in `initialize` after 30 s under the script's reduced environment; the installed module answered at once |
| P4 | `curl -X POST http://127.0.0.1:4310/mcp -H "content-type: application/json" -H "accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'`, and the same with `initialize`; the executor was already running and was not restarted | `serverInfo`: `knowledge-verification-executor` 0.1.0, protocol 2025-06-18. **40 tools**, HTTP 200 with no token. The Knowledge Services checkout was clean at `7bc4aee`; the server reports no commit, so that the process was built from it is [INF] |

The three snapshots became the fixtures [`mcp.github.tools.json`](../../../../../tests/fixtures/mcp/mcp.github.tools.json),
[`mcp.context7.tools.json`](../../../../../tests/fixtures/mcp/mcp.context7.tools.json) and
[`mcp.knowledge-capture.tools.json`](../../../../../tests/fixtures/mcp/mcp.knowledge-capture.tools.json)
(`capture_method: captured`; names, descriptions and input schemas as listed; icons and titles dropped).
`side_effect_class` is the server's read-only annotation for GitHub and Context7 and my classification of
each captured description for the executor, which publishes no annotation.

Not run: the OCI image, either remote endpoint, any tool call, any arXiv server.

<a id="proposals"></a>
## 7. Proposals for the current system

Registered in the [improvement register](../../PROVIDER-RESEARCH-RUNNING-PROPOSAL.md#5-improvement-register).

| ID | Proposal | Evidence |
| --- | --- | --- |
| IP-008 | Let the pin file describe, and the worker verify and launch, two more forms of MCP server: a remote Streamable HTTP endpoint (endpoint, credential environment name, tools) and a stdio executable that is not a node module (command digest, arguments) | MC-3 |
| IP-009 | Make a server's tool list narrowable on the Deep Agents lane: load only the bound tools and report drift when a bound tool is missing or its schema changed, so a catalog allowlist holds against a server that lists more | MC-1, KS-6 |
| IP-010 | Carry static, non-secret request headers and a deployment-named endpoint (`url_ref`) in an MCP server's definition or overlay and project them | MC-5, GH-7 |
| IP-011 | Give a node-level plugin's Skill and MCP members a Deep Agents launch binding, or refuse the plugin at compile instead of at launch | MC-6 |
| IP-012 | A first-party arXiv tool over the export API (search and one exact abstract version, rate-limited to the terms), from the existing test fixture | AX-5 |
| IP-013 | Add `mcp.context7` to the pin writer and the worker pin file | MC-4, C7-1 |

<a id="availability"></a>
## 8. Availability after this change

For the upstream research skill (the imported copies in this repository are exact and are not edited
here). "Seeded" means a catalog row in the seed bundle; a mission attaches one only if its manifest
selects it, its lane supports it and the deployment serves it. State as of 2026-11-16, after the
capture server's revision 3 and the first research mission that mounted it.

| Tool | Catalog pin | Tool list | Credential name | Reachable by a mission |
| --- | --- | --- | --- | --- |
| Tavily | `mcp.tavily@0.2.22` (seed 1.0.0, unchanged) | transcribed 2026-10-07 | `TAVILY_API_KEY` | as before; the local installation binds no launch component for it and its worker holds no key, so `plugin.web-research` does not launch there |
| Firecrawl, with the developer and paper indexes | `mcp.firecrawl@3.28.2` (seed 1.0.0, unchanged) | transcribed 2026-10-07 | `FIRECRAWL_API_KEY` | as Tavily |
| Browser | `mcp.agent-browser@0.38.2`, `skill.agent-browser` (unchanged) | transcribed 2026-10-07 | none | as before; no launch binding on the local installation (the first member a `research-report` start refuses) |
| GitHub, read-only | `mcp.github@2.1.0#sha256:8a9527386e0634359e8c61114aac0d9439ffdc2646b8d44b2875a6ef0d15a60a` (seed 1.1.0, unchanged) | captured 2026-11-16, 22 tools | `GITHUB_PERSONAL_ACCESS_TOKEN` (a read-only token) | a Deep Agents node, directly or through `plugin.code-research`, where a worker pins the binary. **Not pinned on this machine**: no release binary is on disk (`--github-mcp-server` names none; nothing is downloaded) |
| Context7 | `mcp.context7@4.7.0#sha256:47e93031a67707b5085404eeb1d5d535556c59b0246bdac0c25814c12671ddf4` (seed 1.1.0, unchanged) | captured 2026-11-16, 2 tools (`resolve-library-id`, `query-docs`) | `CONTEXT7_API_KEY` (optional upstream; pinned keyless unless named) | as GitHub, from a node-module pin. **Not pinned on this machine**: `@upstash/context7-mcp@4.7.0` is not installed under the workspace `.tools` |
| GitHub and Context7 with one pin | `plugin.code-research@1#sha256:8f6606886307e700bf19dc807189234511240274f601a6cc0593d5f787b1ad88` (unchanged) | - | the two above | a Deep Agents node, where both members are pinned and bound |
| arXiv's own interface | not seeded | - | - | the Firecrawl paper index, then a capture of arXiv's record; a first-party tool is IP-012 |
| Capture, quotable capture, anchored claim, source and schema tools of the executor | `mcp.knowledge-capture@0.1.0-1a451fd#sha256:a50c732566546291714dd987e7c6cea74d8112ccaaeba931ce8fec1e9eb9354c`, revision 3 (seed 1.3.0, fixture `mcp.knowledge-capture.1a451fd.tools.json`); revisions 2 (`…7bc4aee#sha256:836511b2…f928f960`, seed 1.2.0) and 1 stay admitted | captured 2026-11-16 from the executor at Knowledge Services `1a451fd`, 23 of 42 allowlisted: revision 2's 19 plus `chain_write`, `evidence_units`, `source_prepare_captured` and `knowledge_describe` | `VERIFY_EXECUTOR_TOKEN` | **a Deep Agents node**, directly or through `plugin.cognition-knowledge` revision 4: the lane attaches the 23 tools, the worker connects to `MCP_SERVER_ENDPOINTS["mcp.knowledge-capture"]` from a remote pin, and the node's sealed secret references now carry the token (it had carried only the children's). Withheld: `ingest_*`, `db_*`, `checkpoint_*`, `schema_materialize`, `artifact_get`, `knowledge_operation_*`, `knowledge_receipt_get`. `unqualified` on cursor_local, claude_agent_sdk and codex; `unsupported` on cursor_cloud |
| The research method with its capture tools, one pin | `plugin.cognition-knowledge@4` per application (seed `mc.app.<app>.cognition-profiles@1.0.3`): `skill.knowledge-research` and `skill.knowledge-verify` revision 2 (imported at `1a451fd`, seed `mc.app.<app>.agent-skills@1.0.6`), the application's charter, `mcp.knowledge-capture` revision 3 and the two subagents | - | `VERIFY_EXECUTOR_TOKEN` | a Deep Agents node. Run on the local installation (below); the `research-report` template still selects it at `@latest` beside two plugins and four knowledge tools that installation does not serve |
| SEC filings | `mcp.edgartools@5.61.1` (one application, unchanged) | transcribed 2026-10-07 | `EDGAR_IDENTITY` | as before |

State on 2026-11-16. Implemented and unit-tested: revision 3 and its seeds, the local installation
writing the worker pin rows (capture server and the nine imported method skills), the launch bindings
and `MCP_SERVER_ENDPOINTS`. Integrated once, on the local production-shaped installation (not
qualified): a mission submitted and started through the operator MCP mount only (run
`3b51d56c-89d5-5d9b-bacf-e21c14911bdb`, Deep Agents, Claude Haiku 5.5, estimated USD 0.028) mounted the
method skills and the 23 capture tools against an executor attached to the AI Engineer lab database. It
captured `https://pypi.org/pypi/deepagents/0.7.38/json`, made it quotable (`source_prepare_captured`),
recorded the proposed claim `01a1e709-df52-7bac-9f21-7d12fd8909a5` anchored to an exact quote
(`chain_write` `record_claim`, written as `pipeline_agent`), was refused
`VERIFIED_CLAIM_REQUIRES_ADMITTED_USE` when it asked for `status: verified`, and its review was
accepted. Not done: the node cannot submit a promised output on an installation without a Knowledge
Services knowledge binding (`submit_output` is one of the knowledge tools), the receipts carry no
Mission Control coordinates, GitHub and Context7 are not pinned on this machine, and no remote
installation holds any of these seeds.
