"""Builders, constants and fakes that other test files import.

Moved from tests/unit/context/test_linked_transfer.py.
"""

from types import SimpleNamespace

from mission_control.application.context.linked_transfer import (
    LinkedExportAccess,
    LinkedExportResolver,
)
from mission_control.domain.context.transfer import LinkedExport, LinkedOutputRef
from mission_control.domain.context.transfer_builders import linked_mission
from tests.support.unit.context.transfer_materializer import RUN, dependent, seam

SOURCE = "33333333-3333-4333-8333-333333333333"


class Exports:
    def __init__(self, export):
        self.export = export
        self.reads = []

    async def get_export(self, scope, export_id):
        self.reads.append((scope, export_id))
        return self.export

    async def released_for(self, scope, receiver_run_id, receiver_position):
        return (self.export,)


class SourceRunOutputs:
    """The receiver's output store, plus the source run's exact reads: `output_revision`
    serves `rows` (recording each read) and `obligation_revision` the store's obligations.
    Every other read delegates to the store, so tests that change it are seen."""

    def __init__(self, outputs, rows, reads):
        self._outputs = outputs
        self._rows = rows
        self._reads = reads

    def __getattr__(self, name):
        return getattr(self._outputs, name)

    async def output_revision(self, scope, revision_id):
        self._reads.append((scope, revision_id))
        return self._rows.get(revision_id)

    async def obligation_revision(self, scope, run_id, key, revision_no):
        assert run_id == SOURCE
        return next(
            (
                item
                for item in self._outputs.obligations
                if item.key == key and item.revision == revision_no
            ),
            None,
        )


class Recheck:
    """The current-use recheck: records each check, or raises `failure` once it is set."""

    def __init__(self):
        self.checks = []
        self.failure: Exception | None = None

    async def __call__(self, access, revision):
        if self.failure is not None:
            raise self.failure
        self.checks.append((access.origin.run_id, revision.run_id, revision.revision_id))


def setup(_monkeypatch=None, *, repair=False):
    """The linked-transfer harness. The positional argument is ignored (callers that still
    pass `monkeypatch`); nothing here patches."""

    s = seam()
    s.accept_report()
    revision = s.outputs.accepted[0].model_copy(update={"run_id": SOURCE})
    rows = {revision.revision_id: revision}
    s.outputs.accepted = []  # delivery must not guess from current accepted heads
    export = LinkedExport(
        export_id="export-one",
        request_scope=s.access().scope,
        chain_id="chain",
        link_id="link",
        release_event_ref="mission-event:release",
        caller_ref="chain-actor",
        source_mission_id="mission-a",
        source_run_id=SOURCE,
        receiver_mission_id="mission-b",
        receiver_run_id=RUN,
        receiver_position="review",
        input_name="selected-report",
        purpose="repair" if repair else "dependent_input",
        admission="subject" if repair else "accepted",
        release_gate="execution_complete" if repair else "goal_accepted",
        source_goal=None if repair else "research",
        gate_ref="mission-event:goal-disposition",
        outputs=(
            LinkedOutputRef(
                obligation_key="draft.report",
                obligation_revision=1,
                owner_position="draft",
                revision_id=revision.revision_id,
                content_digest=revision.content_digest,
                acceptance_ref=None if repair else "mc-output-acceptance:pinned",
            ),
        ),
    )
    exports = Exports(export)
    reads = []
    recheck = Recheck()
    resolver = LinkedExportResolver(
        exports,
        SourceRunOutputs(s.outputs, rows, reads),
        s.materializer._resolvers["produced_output"],
        recheck=recheck,
    )
    s.materializer._resolvers["linked_export"] = resolver
    s.materializer._access["linked_export"] = LinkedExportAccess(
        resolver, s.materializer._access["produced_output"]
    )
    selection = linked_mission(dependent(), (export,))
    return SimpleNamespace(
        s=s,
        export=export,
        exports=exports,
        revision=revision,
        rows=rows,
        reads=reads,
        checks=recheck.checks,
        recheck=recheck,
        selection=selection,
        resolver=resolver,
    )
