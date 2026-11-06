"""`codex_agents` prepare: sync a pack's saved agent, environment template and vault through the
Agents API, keyed by digest, then prewarm on demand (SPEC-06 section 5.1; DECISIONS R30; HL-11).

A sync creates each resource once and reuses it on every later run, so a second sync of an
unchanged pack creates nothing:

- **saved agent**, one per pack digest. The Agents API takes no create id and no
  `Idempotency-Key` for agents, and an update applies only to new sessions, so an agent is never
  updated. It carries `mc_app` and `mc_pack` metadata and is found again by listing. A changed
  pack is a new digest and a new agent; the old one stays for sessions still bound to it;
- **environment template**, one per template digest (network, packages, setup commands,
  variables and the inline skill and plugin bundles). Templates take no metadata and, in
  `openai` 3.29.0, no `Idempotency-Key`, so the digest rides in the template name and a lost
  create response is found again by that name;
- **vault**, one per secret-set digest (the credential declarations, never their values), found
  by `mc_app` and `mc_secret_set` metadata. Credentials are written through the Secret Broker's
  `ProviderVaultStore` (the `provider_vault` channel), and only the ones the vault does not yet
  hold. Every value they need is read from the worker before anything is created, so a missing
  variable refuses the sync instead of leaving a half-filled vault;
- **prewarm**, per launch rather than per sync: an unattached prewarm expires in about five
  minutes. Its `Idempotency-Key` is derived from the pack digest and the caller's launch key, so
  a retried prewarm returns the same environment within the API's 24-hour key window
  (research/openai-hosted-agents.md section 2).

Labels such as `mc_run=run1-HL-11` go on every resource that takes metadata and never into a
lookup key, so a labelled drill reuses what an earlier sync made. When several listed resources
match, the oldest wins, so two racing syncs converge on one id. Each resource's read-back digest
(its response without timestamps) is kept as discovery proof. Nothing here logs or returns a
secret value.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID, uuid5

from mission_control.adapters.openai_agents.client import AgentsApiClient
from mission_control.adapters.openai_agents.pack import CodexAgentsPack, VaultCredentialSpec
from mission_control.adapters.secrets.vaults import ProviderVaultStore
from mission_control.application.secrets.broker import SecretBroker, SecretSource, SecretUnavailable
from mission_control.domain.authoring.canonical import sha256_digest

# uuid5 namespace of `codex_agents` prewarm idempotency keys.
PREWARM_NAMESPACE: Final = UUID("6f1c2f0e-3b8a-5d47-9e21-0c5a7d4b8e13")
APP_KEY: Final = "mc_app"
PACK_KEY: Final = "mc_pack"
SECRET_SET_KEY: Final = "mc_secret_set"  # noqa: S105 - a metadata key, not a secret
METADATA_LIMIT: Final = 16
_LABEL_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LABEL_VALUE_LIMIT: Final = 512
_VOLATILE: Final = frozenset({"created_at", "updated_at"})

Outcome = Literal["created", "reused"]


@dataclass(frozen=True)
class PreparedResource:
    kind: Literal["agent", "environment_template", "vault"]
    id: str
    digest: str
    outcome: Outcome
    readback_digest: str


@dataclass(frozen=True)
class PreparedCodexAgents:
    """What a `codex_agents` session is created from, and what this sync created."""

    pack_digest: str
    agent: PreparedResource
    template: PreparedResource
    vault: PreparedResource | None
    credentials_written: tuple[str, ...]
    container_size: str
    task_queue: str
    data_class: str

    @property
    def resources(self) -> tuple[PreparedResource, ...]:
        return (self.agent, self.template, *((self.vault,) if self.vault else ()))

    @property
    def created(self) -> tuple[str, ...]:
        return tuple(item.kind for item in self.resources if item.outcome == "created")

    @property
    def vault_ids(self) -> list[str]:
        return [self.vault.id] if self.vault else []

    def session_environment(self, prewarmed_environment_id: str | None = None) -> dict[str, Any]:
        """The session's `environment`: the prewarmed one when given, else the template at the
        pack's container size (a prewarm request takes no size in `openai` 3.29.0)."""

        if prewarmed_environment_id is not None:
            return {"type": "openai_hosted", "environment_id": prewarmed_environment_id}
        return {
            "type": "openai_hosted",
            "environment_template_id": self.template.id,
            "container_size": self.container_size,
        }


@dataclass(frozen=True)
class PrewarmedEnvironment:
    id: str
    status: str


def readback_digest(resource: Mapping[str, Any]) -> str:
    return sha256_digest({key: value for key, value in resource.items() if key not in _VOLATILE})


def prewarm_idempotency_key(pack_digest: str, launch_key: str) -> str:
    return f"mc-prewarm-{uuid5(PREWARM_NAMESPACE, f'{pack_digest}:{launch_key}')}"


def _labels(labels: Mapping[str, str]) -> dict[str, str]:
    reserved = {APP_KEY, PACK_KEY, SECRET_SET_KEY}
    for key, value in labels.items():
        if key in reserved or not _LABEL_KEY.match(key) or len(value) > _LABEL_VALUE_LIMIT:
            raise ValueError(f"label {key} is reserved or malformed")
    if len(labels) + len(reserved) > METADATA_LIMIT:
        raise ValueError(f"at most {METADATA_LIMIT - len(reserved)} labels fit the metadata")
    return dict(labels)


async def _oldest(
    items: AsyncIterator[dict[str, Any]], matches: Callable[[dict[str, Any]], bool]
) -> dict[str, Any] | None:
    """The first match of an oldest-first listing."""

    async for item in items:
        if matches(item):
            return item
    return None


async def _visible_created(
    listing: Callable[[], AsyncIterator[dict[str, Any]]], created: dict[str, Any]
) -> dict[str, Any]:
    """Do not release a create receipt before the provider index can rediscover it.

    Native listings can lag successful creates. Require the exact returned ID and
    immutable response, rather than treating an empty index as permission to duplicate.
    """
    try:
        async with asyncio.timeout(10):
            while True:
                found = await _oldest(listing(), lambda row: row.get("id") == created["id"])
                if found is not None:
                    if readback_digest(found) != readback_digest(created):
                        raise ValueError("created hosted resource readback changed")
                    return found
                await asyncio.sleep(0.25)
    except TimeoutError as error:
        raise ValueError("created hosted resource not visible in bounded readback") from error


def _tagged(tags: Mapping[str, str]) -> Callable[[dict[str, Any]], bool]:
    def matches(item: dict[str, Any]) -> bool:
        metadata = item.get("metadata")
        return isinstance(metadata, Mapping) and all(
            metadata.get(key) == value for key, value in tags.items()
        )

    return matches


class CodexAgentsPreparer:
    """Syncs one pack into one OpenAI project; the client carries the project key (OA1)."""

    def __init__(
        self,
        client: AgentsApiClient,
        secrets: SecretSource,
        *,
        labels: Mapping[str, str] | None = None,
        broker: SecretBroker | None = None,
    ) -> None:
        self._client = client
        self._secrets = secrets
        self._broker = broker
        self._labels = _labels(labels or {})

    async def sync(self, pack: CodexAgentsPack) -> PreparedCodexAgents:
        vault, written = await self._vault(pack)
        template = await self._template(pack)
        agent = await self._agent(pack)
        document = pack.document
        return PreparedCodexAgents(
            pack_digest=pack.digest,
            agent=agent,
            template=template,
            vault=vault,
            credentials_written=written,
            container_size=document.environment.container_size,
            task_queue=document.task_queue,
            data_class=document.data_class,
        )

    async def prewarm(
        self, prepared: PreparedCodexAgents, *, launch_key: str
    ) -> PrewarmedEnvironment:
        """Prewarm the template's environment for one launch (needs the prewarming beta)."""

        body: dict[str, Any] = {
            "environment": {
                "type": "openai_hosted",
                "environment_template_id": prepared.template.id,
            }
        }
        if prepared.vault_ids:
            body["vault_ids"] = prepared.vault_ids
        environment = await self._client.prewarm_environment(
            body, idempotency_key=prewarm_idempotency_key(prepared.pack_digest, launch_key)
        )
        return PrewarmedEnvironment(id=str(environment["id"]), status=str(environment["status"]))

    async def _agent(self, pack: CodexAgentsPack) -> PreparedResource:
        tags = {APP_KEY: pack.application, PACK_KEY: pack.digest}
        found = await _oldest(self._client.agents(), _tagged(tags))
        outcome: Outcome = "reused"
        if found is None:
            found = await self._client.create_agent(
                {**pack.agent_config, "metadata": {**tags, **self._labels}}
            )
            found = await _visible_created(self._client.agents, found)
            outcome = "created"
        return PreparedResource(
            "agent", str(found["id"]), pack.digest, outcome, readback_digest(found)
        )

    async def _template(self, pack: CodexAgentsPack) -> PreparedResource:
        found = await _oldest(
            self._client.environment_templates(),
            lambda template: template.get("name") == pack.template_name,
        )
        outcome: Outcome = "reused"
        if found is None:
            found = await self._client.create_environment_template(pack.template_body())
            found = await _visible_created(self._client.environment_templates, found)
            outcome = "created"
        return PreparedResource(
            "environment_template",
            str(found["id"]),
            pack.template_digest,
            outcome,
            readback_digest(found),
        )

    async def _vault(
        self, pack: CodexAgentsPack
    ) -> tuple[PreparedResource | None, tuple[str, ...]]:
        declared = pack.document.vault.credentials
        if not declared:
            return None, ()
        tags = {APP_KEY: pack.application, SECRET_SET_KEY: pack.secret_set_digest}
        found = await _oldest(self._client.vaults(tags), _tagged(tags))
        held: frozenset[str] = frozenset()
        if found is not None:
            held = await self._store(pack, str(found["id"])).names()
        missing = [credential for credential in declared if credential.name not in held]
        values = await self._values(missing, pack)
        outcome: Outcome = "reused"
        if found is None:
            digest = pack.secret_set_digest.removeprefix("sha256:")
            found = await self._client.create_vault(
                {
                    "name": f"mc-{pack.application}-{digest[:16]}",
                    "metadata": {**tags, **self._labels},
                }
            )
            outcome = "created"
        store = self._store(pack, str(found["id"]))
        for credential in missing:
            await store.put(credential.name, values[credential.name])
        resource = PreparedResource(
            "vault", str(found["id"]), pack.secret_set_digest, outcome, readback_digest(found)
        )
        return resource, tuple(credential.name for credential in missing)

    def _store(self, pack: CodexAgentsPack, vault_id: str) -> ProviderVaultStore:
        return ProviderVaultStore(
            self._client.credentials,
            vault_id,
            provider="openai",
            allowed_hosts={
                credential.name: credential.allowed_hosts
                for credential in pack.document.vault.credentials
            },
            metadata={APP_KEY: pack.application, SECRET_SET_KEY: pack.secret_set_digest}
            | self._labels,
        )

    async def _values(
        self, credentials: Sequence[VaultCredentialSpec], pack: CodexAgentsPack
    ) -> dict[str, str]:
        """Every needed value, or a refusal naming only the absent worker variables."""

        if pack.secret_declarations:
            if self._broker is None:
                raise SecretUnavailable(
                    "selected secret references require the shared Secret Broker"
                )
            names = {item.name for item in credentials}
            declared = tuple(item for item in pack.secret_declarations if item.name in names)
            if {item.name for item in declared} != names:
                raise SecretUnavailable(
                    "selected secret declarations do not match the provider vault"
                )
            resolved = await self._broker.resolve_declarations(declared)
            if set(resolved.values) != names:
                raise SecretUnavailable("selected provider vault credentials are unavailable")
            return dict(resolved.values)
        values: dict[str, str] = {}
        absent: list[str] = []
        for credential in credentials:
            value = await self._secrets.read(credential.source_env)
            if value:
                values[credential.name] = value
            else:
                absent.append(credential.source_env)
        if absent:
            raise SecretUnavailable(
                f"the worker environment holds no value for {', '.join(sorted(absent))}"
            )
        return values


__all__ = [
    "PREWARM_NAMESPACE",
    "CodexAgentsPreparer",
    "PreparedCodexAgents",
    "PreparedResource",
    "PrewarmedEnvironment",
    "prewarm_idempotency_key",
    "readback_digest",
]
