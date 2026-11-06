class WorkspaceMaterializationError(ValueError):
    """A workspace request violates its compiled contract."""


class WorkspaceSlotConflict(WorkspaceMaterializationError):
    """A logical writable slot is already owned by another workspace owner."""


class WorkspaceDigestMismatch(WorkspaceMaterializationError):
    """Mounted or candidate bytes do not match their governed digest."""


class UndeclaredWorkspacePath(WorkspaceMaterializationError):
    """A path is not governed by the materialized workspace contract."""


class UnsupportedWorkspaceRequirement(WorkspaceMaterializationError):
    """The selected sandbox provider cannot enforce a required control."""


class UnsupportedRuntimePolicy(ValueError):
    """The selected agent runtime cannot faithfully enforce a bound policy."""


class DeepAgentMaterializationError(ValueError):
    """An exact Deep Agent binding could not be materialized before model invocation."""


class DeepAgentRuntimeDrift(DeepAgentMaterializationError):
    """Installed runtime or resolved component differs from the immutable binding."""


class DeepAgentUnsupportedPlacement(DeepAgentMaterializationError):
    """The exact placement is not qualified by this adapter and cannot silently fall back."""


class OutputSchemaUnsupported(UnsupportedRuntimePolicy, DeepAgentMaterializationError):
    """W1 D16: the node's bound output schema cannot be enforced through its model row (no
    declared structured-output strategy, or a ``provider_native`` schema outside the vendor's
    supported subset). Raised before any model call; the operation settles ``failed`` with
    :attr:`code`, a terminal outcome: retrying the same sealed binding cannot succeed."""

    code = "output_schema_unsupported"


class SandboxSnapshotError(ValueError):
    """Snapshot creation or clone restore violated a governed invariant."""


class SnapshotCompatibilityError(SandboxSnapshotError):
    """A snapshot cannot be restored into the requested runtime contract."""


class SnapshotAuthorityError(SandboxSnapshotError):
    """Present authority does not admit snapshot creation or restoration."""


class SnapshotPayloadMismatch(SandboxSnapshotError):
    """Stored snapshot bytes do not match immutable snapshot metadata."""


class SnapshotMigrationRequired(SnapshotCompatibilityError):
    """An authored migration must run as a new semantic operation."""


class SnapshotCreationInProgress(RuntimeError):
    """Another worker owns the durable snapshot-creation claim."""


class SnapshotCloneInProgress(RuntimeError):
    """Another worker owns the durable snapshot-clone claim."""


class RuntimeInvocationFailure(RuntimeError):
    """A runtime invocation failed after it was admitted to provider work (REQ-CP-RUN-007).

    It carries only the original exception type and whether a terminal result was observed
    afterwards, never provider or secret text. The operation boundary settles such a unit
    `failed` only when no terminal result exists and every effect claim is settled.
    """

    def __init__(
        self,
        error_type: str,
        *,
        terminal_result_observed: bool,
        candidates: tuple[object, ...] = (),
        latest_capture: object | None = None,
        usage: object | None = None,
        cognition_points: tuple[object, ...] = (),
        failure_class: str | None = None,
    ) -> None:
        super().__init__(f"{error_type} after runtime admission")
        self.error_type = error_type
        # W1 D40: a typed fault class the boundary settles with instead of `runtime_failed`
        # (`transient_transport`: the call never reached the provider and its bounded
        # in-turn retry was exhausted).
        self.failure_class = failure_class
        self.terminal_result_observed = terminal_result_observed
        # Qualified keys of the terminal stamped leaf an operator may accept.
        self.candidates = candidates
        # RRM-008: the latest durable checkpoint of the unique stamped lineage, if any, so a
        # `failed` settlement can record the partial lineage as the namespace head.
        self.latest_capture = latest_capture
        # Tracing Stage 2 (F-S2-11): what the completed model calls spent before the failure
        # (parent and in-process children, as a settlement charges them), and the points of
        # the partial lineage up to `latest_capture`, so a provider failure mid-turn neither
        # drops the spend from the budget nor leaves the turn's frames without a point.
        self.usage = usage
        self.cognition_points = cognition_points
