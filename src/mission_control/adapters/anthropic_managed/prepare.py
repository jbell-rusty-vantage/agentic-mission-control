"""`claude_managed` prepare: sync a rendered pack to Managed Agents resources, keyed by digest.

SPEC-06 section 4.1 maps the Cognition Pack and the Environment Kit onto resources that are
created once and reused by id, so a mission costs one `sessions.create`:

- skill: keyed by bundle digest and scope tag, both carried in `display_name` (skills have no
  metadata); listed by display name and pinned in the agent by `latest_version_id`;
- environment: `metadata.mc_digest` is the kit digest. Environments are not versioned, so a new
  digest is a new environment;
- vault: `metadata.mc_digest` is the secret-set digest (installation, names, hosts). The
  Secret Broker resolves the credential values (`environment:<NAME>`, the worker environment)
  and every sync delivers them through its `provider_vault` channel (`ManagedVaultStore`), so
  each write is a recorded `SecretUse` and each value joins the broker's redaction registry;
- agent: found by `metadata.mc_pack`, one version per materialization digest. A changed digest
  updates the agent under the `version` it was read at (`409` is `AgentVersionConflict`).

Every resource that takes metadata also carries the scope (`mc_installation` plus any labels,
e.g. `mc_run`) and `mc_scope`, the digest of exactly that scope. Resources are matched on
`mc_scope`, never on a subset of keys, so neither a drill nor production (nor two label sets
where one contains the other) adopts the other's resources; a skill carries the first eight hex
digits of the scope digest in its display name for the same reason. Nothing is
retried here: a create whose response was lost is found again by the next sync's listing. After
the sync each resource is read back and the digest of what the API returned is recorded as the
discovery proof (`PreparedPack`); the receipt carries ids, versions, names and digests only,
never a credential value.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from mission_control.adapters.anthropic_managed.client import JsonObject, ManagedAgentsClient
from mission_control.adapters.anthropic_managed.pack import (
    PackRefused,
    RenderedPack,
    SkillBundle,
)
from mission_control.adapters.anthropic_managed.vault import CredentialAction, ManagedVaultStore
from mission_control.application.secrets.broker import ResolvedSecrets, SecretBroker
from mission_control.application.secrets.delivery import SecretUse, deliver_to_store
from mission_control.application.secrets.redaction import MIN_SECRET_CHARS
from mission_control.application.secrets.references import BrokerRef, SecretDeclaration
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.data_class import DataClass

METADATA_INSTALLATION: Final = "mc_installation"
METADATA_PACK: Final = "mc_pack"
METADATA_DIGEST: Final = "mc_digest"
METADATA_SCOPE: Final = "mc_scope"
# Managed Agents metadata holds at most 16 pairs (anthropic SDK `agent_create_params`).
MAX_METADATA_PAIRS: Final = 16

ResourceAction = Literal["created", "reused", "updated"]

# The fields of each read-back that make up its discovery digest (ids and timestamps excluded).
_AGENT_FIELDS: Final = (
    "name",
    "model",
    "system",
    "tools",
    "mcp_servers",
    "skills",
    "multiagent",
    "metadata",
    "version",
)
_ENVIRONMENT_FIELDS: Final = ("name", "config", "metadata")
_SKILL_FIELDS: Final = ("display_name", "latest_version_id", "source")
_VAULT_FIELDS: Final = ("display_name", "metadata")


class PackSecretMissing(LookupError):
    def __init__(self, names: Sequence[str]) -> None:
        super().__init__(f"the worker environment holds no value for {', '.join(names)}")
        self.names = tuple(names)


class _Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PreparedSkill(_Receipt):
    name: str
    bundle_digest: str
    skill_id: str
    version_id: str
    display_name: str
    action: Literal["created", "reused"]
    readback_digest: str


class PreparedEnvironment(_Receipt):
    environment_id: str
    name: str
    kit_digest: str
    action: Literal["created", "reused"]
    readback_digest: str


class PreparedCredential(_Receipt):
    name: str
    credential_id: str
    action: CredentialAction


class PreparedVault(_Receipt):
    vault_id: str
    secret_set_digest: str
    action: Literal["created", "reused"]
    credentials: tuple[PreparedCredential, ...]
    secret_uses: tuple[SecretUse, ...] = Field(
        description="The Secret Broker's record of this delivery (names and channel only)."
    )
    readback_digest: str


class PreparedAgent(_Receipt):
    agent_id: str
    version: int = Field(ge=1)
    materialization_digest: str
    action: ResourceAction
    readback_digest: str


class PreparedPack(_Receipt):
    """What one sync left at the provider: ids, versions and digests (never a value)."""

    pack_id: str
    application: str
    lane_profile: Literal["claude_managed"]
    task_queue: str
    data_class: DataClass
    installation_id: str
    skills: tuple[PreparedSkill, ...]
    environment: PreparedEnvironment
    vault: PreparedVault | None
    agent: PreparedAgent

    def session_fields(self) -> dict[str, Any]:
        """The prepared part of `POST /v1/sessions`: the pinned agent version, the
        environment and the vault (SPEC-06 section 4.2 `start`)."""

        return {
            "agent": {"type": "agent", "id": self.agent.agent_id, "version": self.agent.version},
            "environment_id": self.environment.environment_id,
            "vault_ids": [self.vault.vault_id] if self.vault else [],
        }

    def projection_digests(self) -> dict[str, str]:
        """The digests a `PreparedSession` records for this pack."""

        digests = {
            "materialization_digest": self.agent.materialization_digest,
            "agent_readback_digest": self.agent.readback_digest,
            "kit_digest": self.environment.kit_digest,
            "environment_readback_digest": self.environment.readback_digest,
        }
        if self.vault is not None:
            digests["secret_set_digest"] = self.vault.secret_set_digest
            digests["vault_readback_digest"] = self.vault.readback_digest
        return digests

    def created(self) -> tuple[str, ...]:
        """Every resource id this sync created (custody and drill cleanup)."""

        return tuple(
            resource_id
            for resource_id, action in (
                *((skill.skill_id, skill.action) for skill in self.skills),
                (self.environment.environment_id, self.environment.action),
                *(((self.vault.vault_id, self.vault.action),) if self.vault else ()),
                (self.agent.agent_id, self.agent.action),
            )
            if action == "created"
        )


class ClaudeManagedPrepare:
    """Syncs rendered packs for one installation (and optional labels) through `client`;
    the vault's credential values come from `broker`."""

    def __init__(
        self,
        client: ManagedAgentsClient,
        broker: SecretBroker,
        *,
        installation_id: str,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        reserved = {
            METADATA_INSTALLATION,
            METADATA_PACK,
            METADATA_DIGEST,
            METADATA_SCOPE,
        } & set(labels or {})
        if reserved:
            raise ValueError(f"labels may not set {', '.join(sorted(reserved))}")
        self._client = client
        self._broker = broker
        self._installation_id = installation_id
        self._labels = dict(sorted((labels or {}).items()))
        scope = {METADATA_INSTALLATION: installation_id, **self._labels}
        self._scope_digest = sha256_digest(scope)
        self._scope = {**scope, METADATA_SCOPE: self._scope_digest}

    async def sync(self, rendered: RenderedPack) -> PreparedPack:
        self._agent_metadata(rendered)  # refused before any provider call
        resolved = await self._resolve(rendered)
        _refuse_values_in_payload(rendered, resolved.values.values())
        skills = tuple([await self._skill(bundle) for bundle in rendered.skills])
        environment = await self._environment(rendered)
        vault = await self._vault(rendered, resolved) if resolved.values else None
        agent = await self._agent(rendered, skills)
        identity = rendered.pack.identity
        return PreparedPack(
            pack_id=rendered.pack.pack_id,
            application=identity.application,
            lane_profile=identity.lane_profile,
            task_queue=identity.task_queue,
            data_class=identity.data_class,
            installation_id=self._installation_id,
            skills=skills,
            environment=environment,
            vault=vault,
            agent=agent,
        )

    # -- resources --------------------------------------------------------------------------------

    async def _skill(self, bundle: SkillBundle) -> PreparedSkill:
        scope_tag = self._scope_digest.removeprefix("sha256:")[:8]
        display_name = self._named(f"{bundle.display_name}-{scope_tag}")
        existing = _oldest(
            skill
            for skill in await self._client.list_skills()
            if skill.get("display_name") == display_name
        )
        if existing is None:
            skill, action = (
                await self._client.create_skill(display_name, bundle.upload()),
                "created",
            )
        else:
            skill, action = existing, "reused"
        readback = await self._client.retrieve_skill(str(skill["id"]))
        return PreparedSkill(
            name=bundle.name,
            bundle_digest=bundle.bundle_digest,
            skill_id=str(skill["id"]),
            version_id=str(readback["latest_version_id"]),
            display_name=display_name,
            action=action,
            readback_digest=_digest(readback, _SKILL_FIELDS),
        )

    async def _environment(self, rendered: RenderedPack) -> PreparedEnvironment:
        metadata = self._metadata(rendered, rendered.kit_digest)
        existing = _oldest(self._owned(await self._client.list_environments(), metadata))
        if existing is None:
            environment = await self._client.create_environment(
                {
                    "name": self._named(rendered.environment_name),
                    "config": dict(rendered.environment_config),
                    "metadata": metadata,
                }
            )
            action: Literal["created", "reused"] = "created"
        else:
            environment, action = existing, "reused"
        readback = await self._client.retrieve_environment(str(environment["id"]))
        return PreparedEnvironment(
            environment_id=str(environment["id"]),
            name=str(readback["name"]),
            kit_digest=rendered.kit_digest,
            action=action,
            readback_digest=_digest(readback, _ENVIRONMENT_FIELDS),
        )

    async def _vault(self, rendered: RenderedPack, resolved: ResolvedSecrets) -> PreparedVault:
        metadata = self._metadata(rendered, rendered.secret_set_digest)
        existing = _oldest(self._owned(await self._client.list_vaults(), metadata))
        if existing is None:
            vault = await self._client.create_vault(
                {
                    "display_name": self._named(f"{rendered.environment_name}-vault"),
                    "metadata": metadata,
                }
            )
            action: Literal["created", "reused"] = "created"
        else:
            vault, action = existing, "reused"
        vault_id = str(vault["id"])
        store = ManagedVaultStore(
            self._client,
            vault_id,
            allowed_hosts={
                spec.name: spec.allowed_hosts for spec in rendered.pack.vault.credentials
            },
            metadata=self._scope,
        )
        uses = await deliver_to_store(resolved, store)
        credentials = tuple(
            PreparedCredential(name=name, credential_id=credential_id, action=action)
            for name, (credential_id, action) in store.written.items()
        )
        readback = await self._client.retrieve_vault(vault_id)
        listed = await self._client.list_credentials(vault_id)
        return PreparedVault(
            vault_id=vault_id,
            secret_set_digest=rendered.secret_set_digest,
            action=action,
            credentials=credentials,
            secret_uses=uses,
            readback_digest=sha256_digest(
                {
                    "vault": {field: readback.get(field) for field in _VAULT_FIELDS},
                    "credentials": sorted(
                        (
                            str(credential["auth"].get("secret_name")),
                            credential["auth"].get("networking"),
                        )
                        for credential in listed
                        if credential.get("archived_at") is None
                        and isinstance(credential.get("auth"), dict)
                    ),
                }
            ),
        )

    async def _agent(
        self, rendered: RenderedPack, skills: Sequence[PreparedSkill]
    ) -> PreparedAgent:
        digest = rendered.materialization_digest
        metadata = self._agent_metadata(rendered)
        body = rendered.agent_body(
            [
                {"type": "custom", "skill_id": skill.skill_id, "version": skill.version_id}
                for skill in skills
            ]
        )
        body["name"] = self._named(body["name"])
        existing = _oldest(
            self._owned(await self._client.list_agents(), {METADATA_PACK: rendered.pack.pack_id})
        )
        action: ResourceAction
        if existing is None:
            agent, action = (
                await self._client.create_agent({**body, "metadata": metadata}),
                "created",
            )
        elif _current(existing, digest, body["skills"]):
            agent, action = existing, "reused"
        else:
            stale = {key: None for key in existing.get("metadata") or {} if key not in metadata}
            agent = await self._client.update_agent(
                str(existing["id"]),
                {**body, "metadata": {**stale, **metadata}, "version": existing["version"]},
            )
            action = "updated"
        readback = await self._client.retrieve_agent(str(agent["id"]))
        return PreparedAgent(
            agent_id=str(agent["id"]),
            version=int(readback["version"]),
            materialization_digest=digest,
            action=action,
            readback_digest=_digest(readback, _AGENT_FIELDS),
        )

    # -- helpers ----------------------------------------------------------------------------------

    def _metadata(self, rendered: RenderedPack, digest: str) -> dict[str, str]:
        return {**self._scope, METADATA_PACK: rendered.pack.pack_id, METADATA_DIGEST: digest}

    def _agent_metadata(self, rendered: RenderedPack) -> dict[str, str]:
        metadata = {
            **rendered.pack.agent.metadata,
            **self._metadata(rendered, rendered.materialization_digest),
        }
        if len(metadata) > MAX_METADATA_PAIRS:
            raise PackRefused(
                "agent.yaml: its metadata and the keys prepare sets exceed the provider's "
                f"{MAX_METADATA_PAIRS} pairs"
            )
        return metadata

    def _named(self, name: str) -> str:
        """Labels (a drill's `mc_run`) also go into every resource name: skills carry no
        metadata, and a labelled resource is told apart at a glance in the Console."""

        if not self._labels:
            return name
        tag = "-".join(self._labels.values())
        return f"mc-{tag}-{name.removeprefix('mc-')}"

    def _owned(self, items: Iterable[JsonObject], keys: Mapping[str, str]) -> list[JsonObject]:
        """The unarchived listed resources of exactly this scope that also hold `keys`. The
        match is on `mc_scope`: a resource whose labels merely include ours is not ours."""

        wanted = {**keys, METADATA_SCOPE: self._scope_digest}
        return [
            item
            for item in items
            if item.get("archived_at") is None
            and all((item.get("metadata") or {}).get(key) == value for key, value in wanted.items())
        ]

    async def _resolve(self, rendered: RenderedPack) -> ResolvedSecrets:
        """The vault's values from the Secret Broker (the worker environment, by name). Every
        missing one is named before any provider call."""

        requested = rendered.secret_declarations or tuple(
            SecretDeclaration(
                name=credential.name,
                ref=BrokerRef(scheme="environment", key=credential.name),
                phases=("agent",),
                required=False,
            )
            for credential in rendered.pack.vault.credentials
        )
        resolved = await self._broker.resolve_declarations(requested)
        if resolved.omitted:
            raise PackSecretMissing(resolved.omitted)
        return resolved


def _oldest(items: Iterable[JsonObject]) -> JsonObject | None:
    """At-least-once creates can leave duplicates; the oldest one is the resource."""

    ordered = sorted(items, key=lambda item: str(item.get("created_at") or ""))
    return ordered[0] if ordered else None


def _current(agent: JsonObject, digest: str, skills: Sequence[Mapping[str, Any]]) -> bool:
    """The agent already is this materialization: same digest and the same skill ids (a skill
    recreated under the same bundle digest has a new id)."""

    listed = {str(skill.get("skill_id")) for skill in agent.get("skills") or ()}
    return (agent.get("metadata") or {}).get(METADATA_DIGEST) == digest and listed == {
        str(skill["skill_id"]) for skill in skills
    }


def _digest(readback: Mapping[str, Any], fields: Sequence[str]) -> str:
    return sha256_digest({field: readback.get(field) for field in fields})


def _refuse_values_in_payload(rendered: RenderedPack, values: Iterable[str]) -> None:
    """No credential value may travel in the agent's system prompt or a skill file."""

    payload = [
        rendered.system.encode("utf-8"),
        *(content for skill in rendered.skills for _, content in skill.files),
    ]
    for value in values:
        if len(value) < MIN_SECRET_CHARS:
            continue
        needle = value.encode("utf-8")
        if any(needle in item for item in payload):
            raise PackRefused("the pack's system prompt or skills carry a vault credential value")


__all__ = [
    "METADATA_DIGEST",
    "METADATA_INSTALLATION",
    "METADATA_PACK",
    "METADATA_SCOPE",
    "ClaudeManagedPrepare",
    "PackSecretMissing",
    "PreparedAgent",
    "PreparedCredential",
    "PreparedEnvironment",
    "PreparedPack",
    "PreparedSkill",
    "PreparedVault",
]
