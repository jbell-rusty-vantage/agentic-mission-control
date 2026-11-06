---
type: Decision Record
title: Knowledge workspaces and mission branches
description: Accepted workspace ownership, runtime input delivery and explicit output custody for code, knowledge and mixed missions.
tags: [mission-control, adr, accepted, workspaces, custody]
status: accepted
---

# Knowledge workspaces and mission branches

**Status: accepted 2026-11-01; implemented by the materialization-observation Run 2 finish (`b95ae4aa` completion summary; `152a3dcb` finish records, 2026-10-20) and the 1.4 database release (`b434e573`).** Previously proposed. Implements the direction in
[SPEC-03](../specs/archive/materialization-observation-2026-10/SPEC-03-workspaces-and-placement.md),
with live acceptance and deployment evidence tracked separately in the run report.

Code, knowledge and mixed missions use the same lease, snapshot and custody contracts.
Local knowledge work can use an initialized research directory without a code repository.
Cloud knowledge work resolves an explicitly configured application knowledge repository;
neither the manifest nor the runtime invents a repository or credentials.

Every cloud execution unit owns a distinct mission branch. Normalized names include an
identity digest so punctuation or truncation cannot make two units share a writable branch.
Generation recovery reattaches to that unit's branch; a recorded head SHA identifies its
snapshot. Local lanes continue to use the common WorkspaceAllocator.

Small nonsensitive inputs may be committed with the mission's cognition and setup files.
Large inputs and explicitly sensitive inputs remain durable Artifact references. Signed
download URLs are delivered at runtime, never committed. A bounded fetch helper verifies
path containment, HTTPS, byte count and the sealed digest before installing an input.
Unavailable signing or runtime delivery refuses preparation instead of committing the bytes.

Output channels are an explicit closed selection. Custody must register the collected bytes
or branch head before cleanup, and the Completion Contract must identify its evidence source.
A provider's completed turn is not acceptance. An unsupported channel must refuse rather than
be silently replaced by another channel. Public ingress upload-to-custody needs the run-2
IngressDrainer; local fixture proof does not establish that live path.

Knowledge Services queries use the application's admitted capability and authoritative
schema. Missing endpoint/schema bindings are owner prerequisites; they are not generic
network tools or invented catalog entries.

We reject a shared writable cloud branch, sensitive bytes in Git, implicit repository
creation, and prompt-only output selection. Placement limits and explicit lane preferences
govern concurrency separately from workspace identity.
