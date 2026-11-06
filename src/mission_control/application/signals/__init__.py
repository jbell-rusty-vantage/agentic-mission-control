"""Signal Ingress: authenticated public ingress for signals, gates, webhooks, artifact uploads
and remote launch requests (SPEC-04 section 3, SPEC-10; ADR-0045).

- `contracts`: wire documents (`mc.signal.v1`, `mc.signal_gate.v1`, `mc.mission_request.v1`),
  trust tiers and typed rejections;
- `verification`: bearer, derived-secret, environment-key, Standard Webhooks and HMAC checks;
- `ports`: the per-application `IngressStore` (one SQL function call per request), the provider
  OIDC verifier and quarantine upload signing;
- `wake`: Managed Agents and Agents API webhooks reduced to a `ProviderWake` (the event type
  and resource id only; the worker re-reads the provider);
- `service`: `SignalIngressService`, shared by the public edge and the worker's loopback mount.

The concrete store is `adapters/postgres/ingress.py`; the HTTP router is
`interfaces/http/ingress.py`.
"""

from mission_control.application.signals.contracts import (
    ArtifactCommitRequest,
    ArtifactPrepareRequest,
    ArtifactUploadSlot,
    GateAnswer,
    GateRequest,
    IngressRejected,
    MissionRequest,
    MissionRequestStatus,
    ProviderWake,
    Signal,
    SignalBatch,
    SignalReceipt,
    TrustTier,
)
from mission_control.application.signals.ports import (
    IngressStore,
    OidcIdentity,
    Principal,
    ProviderOidcVerifier,
    QuarantineUploads,
)
from mission_control.application.signals.service import (
    IngressKeys,
    IngressLimits,
    SignalIngressService,
)

__all__ = [
    "ArtifactCommitRequest",
    "ArtifactPrepareRequest",
    "ArtifactUploadSlot",
    "GateAnswer",
    "GateRequest",
    "IngressKeys",
    "IngressLimits",
    "IngressRejected",
    "IngressStore",
    "MissionRequest",
    "MissionRequestStatus",
    "OidcIdentity",
    "Principal",
    "ProviderOidcVerifier",
    "ProviderWake",
    "QuarantineUploads",
    "Signal",
    "SignalBatch",
    "SignalIngressService",
    "SignalReceipt",
    "TrustTier",
]
