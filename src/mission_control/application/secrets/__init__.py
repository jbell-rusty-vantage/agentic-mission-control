"""The Secret Broker port and its framework-neutral rules (SPEC-01 section 4; ADR-0043).

- `references`: the reference grammar and the declarations bindings carry (names only);
- `broker`: `SecretBroker`, the deployment's `SecretResolutionPort`, over installation sources;
- `minting`: per-run credentials bound to scope, run, unit and generation (digest stored);
- `delivery`: per-lane channels (process environment, provider stores) and `SecretUse`;
- `redaction`: exact-match redaction of resolved values for frames, logs and receipts;
- `commit_scan`: the pre-commit scan of Mission Control's commits to mission branches.

Concrete sources, stores and provider clients live in `adapters/secrets` and the lane adapters.
"""

from mission_control.application.secrets.broker import (
    ResolvedSecrets,
    SecretBroker,
    SecretSource,
    SecretUnavailable,
)
from mission_control.application.secrets.commit_scan import SecretInCommit, scan_commit
from mission_control.application.secrets.delivery import (
    DeliveredEnvironment,
    DeliveryChannel,
    ProcessSecretDelivery,
    ProviderHeldSecretMissing,
    ProviderSecretStore,
    SecretUse,
    credential_binding,
    deliver_to_store,
)
from mission_control.application.secrets.minting import (
    MINT_PURPOSES,
    MISSION_REQUEST,
    SIGNAL_TOKEN,
    CredentialBinding,
    CredentialMinter,
    CredentialRejected,
    LaunchBinding,
    MintedCredential,
    MintedCredentialStore,
    MintedToken,
    MintPurpose,
)
from mission_control.application.secrets.redaction import (
    SecretValueRegistry,
    install_log_redaction,
    redact_receipt,
)
from mission_control.application.secrets.references import (
    BrokerRef,
    SecretDeclaration,
    SecretReferenceError,
    declarations,
)

__all__ = [
    "MINT_PURPOSES",
    "MISSION_REQUEST",
    "SIGNAL_TOKEN",
    "BrokerRef",
    "CredentialBinding",
    "CredentialMinter",
    "CredentialRejected",
    "DeliveredEnvironment",
    "DeliveryChannel",
    "LaunchBinding",
    "MintPurpose",
    "MintedCredential",
    "MintedCredentialStore",
    "MintedToken",
    "ProcessSecretDelivery",
    "ProviderHeldSecretMissing",
    "ProviderSecretStore",
    "ResolvedSecrets",
    "SecretBroker",
    "SecretDeclaration",
    "SecretInCommit",
    "SecretReferenceError",
    "SecretSource",
    "SecretUnavailable",
    "SecretUse",
    "SecretValueRegistry",
    "credential_binding",
    "declarations",
    "deliver_to_store",
    "install_log_redaction",
    "redact_receipt",
    "scan_commit",
]
