from __future__ import annotations

import hmac
import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, get_args
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mission_control.bootstrap.application_profiles import (
    deployments_root,
    installation_defaults,
)
from mission_control.domain.execution.lanes import LaneProfileName
from mission_control.domain.execution.placement import PlacementLimit

# Deployment resources are selected by the operator, never relative to site-packages.
# Local commands use their working directory; installed deployments set this root.
PROJECT_ROOT = Path(os.environ.get("MISSION_CONTROL_HOME", str(Path.cwd()))).resolve()

# The private LangGraph saver/store schema (adapters/deep_agents/persistence.RUNTIME_SCHEMA;
# imported lazily there because the deep_agents package imports these settings).
RUNTIME_CHECKPOINT_SCHEMA = "mission_control_runtime"


def configured(value: SecretStr | None) -> SecretStr | None:
    """``value`` when it carries a non-blank secret, else ``None``: an empty variable is unset.

    An environment variable that is present but empty still wins over the `.env` file, so a
    deployment can blank a credential on purpose; every reader below treats that as unset.
    """

    return value if value is not None and value.get_secret_value().strip() else None


class IntegrationConfigurationError(ValueError):
    """A selected optional adapter lacks its deployment configuration."""


class InstallationDefaultUnavailable(IntegrationConfigurationError):
    """OC-R4 review B2: an installation setting with no neutral default (the Temporal queue
    base, the capability resource owner) is set neither in the environment nor by the
    selected application's profile. Startup fails instead of inventing a value."""


def _placement_limits() -> dict[LaneProfileName, PlacementLimit]:
    return {
        "cursor_cloud": PlacementLimit(max_active=8, launches_per_minute=15),
        "claude_managed": PlacementLimit(max_active=4),
        "codex_agents": PlacementLimit(max_active=4),
        "cursor_local": PlacementLimit(max_active=3),
        "claude_agent_sdk": PlacementLimit(max_active=3),
        "codex": PlacementLimit(max_active=3),
    }


DbPlane = Literal["AIENG", "BIOTECH", "LOCAL"]
_APPLICATION_PLANES: dict[str, DbPlane] = {"ai-engineer": "AIENG", "biotech": "BIOTECH"}
_DSN_ROLES = ("admin_dsn", "runtime_dsn", "family_writer_dsn", "backfill_dsn", "checkpoint_dsn")


def plane_for_application(application: str | None) -> DbPlane:
    """``ai-engineer`` is AIENG, ``biotech`` is BIOTECH, unset is the local Docker database."""

    if application is None:
        return "LOCAL"
    plane = _APPLICATION_PLANES.get(application)
    if plane is None:
        raise IntegrationConfigurationError(
            f"MISSION_CONTROL_APPLICATION={application} selects no database plane "
            "(ai-engineer, biotech, or unset for the local Docker database)"
        )
    return plane


class PlaneDatabase(BaseModel):
    """The database variables of one plane, resolved once. Secrets stay ``SecretStr``."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    plane: DbPlane
    project_ref: str | None = None
    url: str | None = None
    publishable_key: SecretStr | None = None
    secret_key: SecretStr | None = None
    legacy_jwt_secret: SecretStr | None = None
    admin_dsn: SecretStr | None = None
    runtime_dsn: SecretStr | None = None
    family_writer_dsn: SecretStr | None = None
    backfill_dsn: SecretStr | None = None
    checkpoint_dsn: SecretStr | None = None

    def env_name(self, role: str) -> str:
        """The environment variable name of ``role`` on this plane, e.g. ``MC_AIENG_DB_URL``."""

        return f"MC_{self.plane}_DB_{role.upper()}"

    def required_dsn(self, role: str, purpose: str) -> str:
        value: SecretStr | None = getattr(self, role)
        if value is None:
            raise ValueError(f"{self.env_name(role)} is required for {purpose}")
        return value.get_secret_value()

    def check_project_ref(self) -> None:
        """Refuse when ``PROJECT_REF`` is absent from a sibling's host or login (names the plane,
        ref, variable and host only; never a credential)."""

        ref = (self.project_ref or "").lower()
        if self.plane == "LOCAL" or not ref:
            return
        siblings: list[tuple[str, str]] = []
        if self.url:
            siblings.append(("url", self.url))
        for dsn_role in _DSN_ROLES:
            secret: SecretStr | None = getattr(self, dsn_role)
            if secret is not None:
                siblings.append((dsn_role, secret.get_secret_value()))
        for role, location in siblings:
            try:
                parts = urlsplit(location)
                host, login = (parts.hostname or "").lower(), (parts.username or "").lower()
            except ValueError:
                host, login = "", ""
            if ref not in host and ref not in login:
                raise ValueError(
                    f"{self.env_name('project_ref')} ({ref}) is not in the host or login of "
                    f"{self.env_name(role)} (plane {self.plane}, host {host or 'unparsed'})"
                )


class Settings(BaseSettings):
    """Deployment settings; optional integrations validate credentials when selected."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    mission_control_placement_limits: dict[LaneProfileName, PlacementLimit] = Field(
        default_factory=_placement_limits
    )
    mission_control_source_watches: list[dict[str, object]] = Field(
        default_factory=list, max_length=16
    )
    # Database variables (docs/ENVIRONMENT.md, config/env.registry.yaml). One block per plane;
    # `MISSION_CONTROL_APPLICATION` selects which one this process reads (`Settings.db`).
    # No other database variable name is read, and there are no aliases.
    mc_aieng_db_project_ref: str | None = None
    mc_aieng_db_url: str | None = None
    mc_aieng_db_publishable_key: SecretStr | None = None
    mc_aieng_db_secret_key: SecretStr | None = None
    mc_aieng_db_legacy_jwt_secret: SecretStr | None = None
    mc_aieng_db_admin_dsn: SecretStr | None = None
    mc_aieng_db_runtime_dsn: SecretStr | None = None
    mc_aieng_db_family_writer_dsn: SecretStr | None = None
    mc_aieng_db_backfill_dsn: SecretStr | None = None
    mc_aieng_db_checkpoint_dsn: SecretStr | None = None
    mc_biotech_db_project_ref: str | None = None
    mc_biotech_db_url: str | None = None
    mc_biotech_db_publishable_key: SecretStr | None = None
    mc_biotech_db_secret_key: SecretStr | None = None
    mc_biotech_db_legacy_jwt_secret: SecretStr | None = None
    mc_biotech_db_admin_dsn: SecretStr | None = None
    mc_biotech_db_runtime_dsn: SecretStr | None = None
    mc_biotech_db_family_writer_dsn: SecretStr | None = None
    mc_biotech_db_backfill_dsn: SecretStr | None = None
    mc_biotech_db_checkpoint_dsn: SecretStr | None = None
    mc_local_db_admin_dsn: SecretStr | None = None
    mc_local_db_runtime_dsn: SecretStr | None = None
    mc_local_db_family_writer_dsn: SecretStr | None = None
    mc_local_db_backfill_dsn: SecretStr | None = None
    mc_local_db_checkpoint_dsn: SecretStr | None = None
    mc_local_db_port: int = 55432  # read by docker-compose and the Makefile
    ingress_drainer_enabled: bool = False
    ingress_manifest_paths: dict[str, Path] = Field(default_factory=dict)
    ingress_quarantine_bucket: str | None = None
    ingress_custody_bucket: str | None = None
    ingress_storage_credential: SecretStr | None = None
    ingress_listen_secret_ref: str | None = None
    cursor_missing_output_followup: bool = False
    cursor_cost_settlement: bool = False

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    # OVE-169: the independent evaluators' OWN credentials (names are their credential refs; never
    # the producer's ANTHROPIC_API_KEY). Both set: production composes the trusted settlement.
    mc_judge_openai_api_key: SecretStr | None = None
    mc_auditor_anthropic_api_key: SecretStr | None = None
    firecrawl_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None

    langsmith_api_key: SecretStr | None = None
    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    # Application-neutral defaults; the selected application's profile supplies its own
    # (`[installation]`, see `_application_defaults`), and the environment wins over both.
    langsmith_project: str = "MissionControl"
    langsmith_workspace_id: str | None = None
    agent_server_langsmith_project: str = "MissionControl-AgentServer-Local"
    bell_labs_trace_pseudonym_key: SecretStr | None = None

    langgraph_runtime_enabled: bool = False
    async_subagent_spawning_enabled: bool = False
    bell_labs_environment: Literal["development", "staging", "production"] = "development"
    agent_server_goal_directed_id: Literal["belllabs_goal_directed"] = "belllabs_goal_directed"
    agent_server_deployment_endpoint_id: str | None = None
    agent_server_deployment_revision: str | None = None
    bell_labs_agent_auth_issuer: str | None = None
    bell_labs_agent_auth_audience: str = "authenticated"
    bell_labs_agent_auth_jwks_uri: str | None = None
    bell_labs_agent_auth_public_key: SecretStr | None = None
    bell_labs_agent_auth_algorithm: Literal["RS256", "ES256"] = "RS256"

    coordinator_mcp_enabled: bool = False
    coordinator_mcp_mount_path: str = Field(
        default="/mcp/coordinator",
        min_length=2,
    )
    coordinator_mcp_jwt_issuer: str | None = None
    coordinator_mcp_jwt_audience: str = Field(default="authenticated", min_length=1)
    coordinator_standalone_mode: Literal["read-only"] = "read-only"
    coordinator_request_timeout_seconds: float = Field(default=30, ge=1, le=120)
    coordinator_max_request_bytes: int = Field(
        default=131_072,
        ge=1_024,
        le=1_000_000,
    )
    coordinator_max_response_bytes: int = Field(
        default=1_000_000,
        ge=1_024,
        le=4_000_000,
    )
    coordinator_max_concurrency: int = Field(default=16, ge=1, le=256)
    coordinator_requests_per_minute: int = Field(default=120, ge=1, le=10_000)
    capability_search_enabled: bool = False
    external_capability_discovery_enabled: bool = False
    coordinator_launch_enabled: bool = False
    capability_embedding_model: Literal["text-embedding-3-small"] = "text-embedding-3-small"
    capability_embedding_dimensions: Literal[1536] = 1536
    # FT-A3: the Model Profile naming the catalog search embedding route. Unset means the
    # public catalog search runs lexical-only (never unavailable for a missing route).
    capability_embedding_profile: Literal["embedding.openai.text-embedding-3-small"] | None = None
    capability_projection_lease_seconds: int = Field(
        default=120,
        ge=15,
        le=900,
    )
    capability_projection_max_attempts: int = Field(default=6, ge=1, le=20)
    capability_projection_base_backoff_seconds: int = Field(
        default=5,
        ge=1,
        le=300,
    )
    capability_projection_max_backoff_seconds: int = Field(
        default=900,
        ge=5,
        le=86_400,
    )
    capability_projection_batch_size: int = Field(default=64, ge=1, le=256)
    coordinator_launch_ticket_ttl_seconds: int = Field(
        default=900,
        ge=60,
        le=3_600,
    )
    external_discovery_request_timeout_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
    )
    external_discovery_command_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=120.0,
    )
    external_discovery_max_output_bytes: int = Field(
        default=1_000_000,
        ge=1_024,
        le=10_000_000,
    )
    external_discovery_max_results: int = Field(default=25, ge=1, le=100)
    external_discovery_max_pages: int = Field(default=5, ge=1, le=20)
    external_discovery_max_retries: int = Field(default=2, ge=0, le=5)
    mcp_registry_base_url: str = "https://registry.modelcontextprotocol.io"
    mcp_registry_api_version: Literal["v0.1"] = "v0.1"
    npx_skills_executable: str = Field(default="npx", min_length=1)
    npx_skills_package_version: str = Field(
        default="1.5.20",
        pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$",
    )
    web_research_firecrawl_mcp_command: Path | None = None
    web_research_firecrawl_mcp_arguments: tuple[str, ...] = ()
    # Unset: under the capability resource owner (`workspace_root`), when one is known.
    web_research_firecrawl_mcp_module: Path | None = None
    web_research_tavily_mcp_command: Path | None = None
    web_research_tavily_mcp_arguments: tuple[str, ...] = ()
    web_research_tavily_mcp_module: Path | None = None
    web_research_agent_browser_node: Path | None = None
    web_research_agent_browser_entrypoint: Path | None = None
    web_research_mcp_timeout_seconds: float = Field(default=30, ge=5, le=120)
    web_research_browser_timeout_seconds: float = Field(default=90, ge=10, le=300)
    web_research_browser_command_timeout_seconds: float = Field(
        default=25,
        ge=5,
        le=60,
    )
    web_research_max_provider_output_bytes: int = Field(
        default=1_000_000,
        ge=16_384,
        le=10_000_000,
    )
    web_research_max_browser_output_bytes: int = Field(
        default=250_000,
        ge=16_384,
        le=2_000_000,
    )

    # RRM-009: production runtime composition. The API composes Temporal-backed inspection,
    # boundary delivery (with its relay), the governed launch path and the generic artifact
    # submitter only when this is set; the worker verifies the Search Attributes at
    # readiness and composes the deployment `WorkerActivityCompositionFactory` when
    # COORDINATOR_LAUNCH_ENABLED is set.
    run_control_temporal_enabled: bool = False
    boundary_relay_interval_seconds: float = Field(default=5.0, ge=0.5, le=300)
    # Scopes the delivery relay re-drives; forced RLS confines every read to one scope.
    boundary_relay_request_scopes: tuple[str, ...] = ()
    # One shared key for multi-replica inspection pagination (>= 16 bytes). When absent the
    # checkpoint signing key derives it, which is also shared by every replica.
    inspection_cursor_key: SecretStr | None = None
    # REQ-CP-DA-004 (clarified): the persistent, registered LangGraph saver and store live
    # in the private `mission_control_runtime` schema, provisioned only by
    # `mission-db runtime-apply` (packages/mission-control-db-contract/runtime). There is no
    # fallback to `belllabs_langgraph` or `public`. `setup` is a TEST-ONLY vendor setup()
    # switch for disposable schemas; it is refused for the runtime schema and in production.
    langgraph_checkpoint_schema: str = Field(
        default=RUNTIME_CHECKPOINT_SCHEMA, pattern=r"^[a-z_][a-z0-9_]{0,62}$"
    )
    langgraph_checkpoint_setup: bool = False
    # The exact checkpointer/store definition digests the deployment serves with that saver
    # and store (`ExactComponentRegistry` keys); bindings naming any other digest refuse.
    deep_agent_checkpointer_digests: tuple[str, ...] = ()
    deep_agent_store_digests: tuple[str, ...] = ()
    # Deployment-stable journal claimant (RRM-004): a per-worker value would make the
    # replacement worker's claim replay conflict.
    operation_journal_claimed_by: str = Field(default="operation-runtime:belllabs", min_length=1)
    # Content-addressed artifact and result payloads when no S3 bucket is configured: a
    # directory every worker and the API can reach (a local object-store stand-in).
    artifact_payload_root: Path | None = None
    # Split-host deployments must attest one shared marker or use S3 on both hosts.
    mission_control_payload_shared_id: str | None = None
    mission_control_split_host: bool = False
    mission_control_worker_role: Literal["base", "lane"] = "base"
    async_subagent_submitter_identity: str = Field(default="belllabs-async-submitter", min_length=1)
    # How long the parent operation boundary waits for its async children to finish before
    # settling the parent; an unfinished child stays an unsettled effect of the run.
    async_subagent_completion_wait_seconds: float = Field(default=120.0, ge=0, le=3_600)
    # Sprint OC WI-04: a saved provider result's settlement wait. The delay between passes is
    # capped here; an effect wait older than the deadline becomes an operator incident; a
    # review wait has no deadline and records one durable alarm per interval.
    settlement_wait_cap_seconds: int = Field(default=3_600, ge=5, le=604_800)
    settlement_effect_deadline_seconds: int = Field(default=86_400, ge=60)
    settlement_review_alarm_seconds: int = Field(default=3_600, ge=60)
    # RRM-008 composed by RRM-009: the heartbeat timeout of `operation.execute`/`cancel` per
    # operation class. A cancel reaches running cognition within about 0.8 * timeout (the SDK
    # heartbeat throttle); a unit holding async children is cancelled sooner because its
    # children keep spending until they are cancelled. Every worker's graceful shutdown must
    # be shorter than the shortest of them (checked when the worker set is composed).
    operation_heartbeat_timeout_seconds: int = Field(default=30, ge=1, le=3_600)
    operation_async_children_heartbeat_timeout_seconds: int = Field(default=15, ge=1, le=3_600)
    operation_bound_heartbeat_timeout_seconds: int = Field(default=30, ge=1, le=3_600)
    worker_graceful_shutdown_seconds: float = Field(default=10.0, ge=0, le=3_600)
    # Digest/revision pins of the search and browser capabilities the deployment mounts.
    capability_pins_path: Path = (
        PROJECT_ROOT / "infra" / "capability-pins" / "research-capabilities.json"
    )
    # MP-02: the operator-reviewed `mc.manifest_launch_bindings.v1` file (Deep Agent scaffold,
    # model/sandbox profile and catalog capability components) the production manifest launch
    # author resolves node environments against. Unset: manifest start needs a family input.
    manifest_launch_bindings_path: Path | None = None
    mission_control_owner_probes_path: Path | None = None
    # P1: the operator-reviewed `mc.installation_config.v1` file of each Application's non-secret
    # values that a manifest `value_ref: config:<key>` names (`bootstrap/installation_config.py`,
    # shape in deployments/examples/installation-config.example.json). Unset: every such key
    # stays a compile blocker. A missing or invalid file fails manifest composition.
    mission_control_installation_config_path: Path | None = None
    # Model provider -> the environment variable naming its credential. Launch templates carry
    # `environment:<NAME>` references only; no process reads the value to author them.
    manifest_provider_secret_env: dict[str, str] = Field(
        default_factory=lambda: {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    )
    # MP-02: the worker's Mission Chain relay pump (`mc.chain.start_run` delivery through the
    # governed launch). Off unless enabled; it also needs the manifest launch bindings.
    chain_relay_enabled: bool = False
    chain_relay_interval_seconds: float = Field(default=2.0, ge=0.1, le=300)
    chain_relay_batch_limit: int = Field(default=20, ge=1, le=500)
    chain_relay_lease_owner: str | None = Field(default=None, min_length=1)
    capability_bundle_backend: Literal["local", "supabase"] = "local"
    capability_bundle_namespace: str | None = None
    # FT-A2: custody credentials (never the service key). The publisher holds INSERT+SELECT
    # on the application prefix of `capability-bundles`; the reader holds SELECT only.
    capability_bundle_publisher_token: SecretStr | None = None
    capability_bundle_reader_token: SecretStr | None = None
    capability_bundle_local_root: Path | None = None
    deep_agent_sandbox_workspace_root: Path | None = None

    # Sprint V SV-16 (M02/K07): the application knowledge binding (K01
    # `ks.knowledge_operation.v2` over HTTP) and the issuer that signs one short-lived
    # Ed25519 credential per dispatch. All unset: no knowledge tools are composed. Any one
    # set, or `KNOWLEDGE_GATEWAY_REQUIRED=true`: the URL, audience, issuer and active key file
    # are all required and composition fails closed naming the missing variables. Key files
    # hold an Ed25519 private JWK (or PKCS#8 PEM with `KNOWLEDGE_ISSUER_KEY_ID`); their bytes
    # are never logged. The retiring key is published in the JWKS only (rotation).
    knowledge_gateway_required: bool = False
    # WI-03 S7: this installation is an identified disposable proof target; only then may the
    # producer-started `report.assess` path run against a KS scripted census auditor.
    knowledge_disposable_installation: bool = False
    knowledge_binding_url: str | None = None
    knowledge_binding_audience: str | None = None
    knowledge_issuer: str | None = None
    knowledge_issuer_key_file: Path | None = None
    knowledge_issuer_key_id: str | None = None
    knowledge_issuer_retiring_key_file: Path | None = None
    knowledge_issuer_retiring_key_id: str | None = None
    knowledge_credential_lifetime_seconds: int = Field(default=300, ge=1, le=300)
    knowledge_credential_skew_seconds: int = Field(default=30, ge=0, le=120)
    # The K01 binding, apply contract and payload layout come from the application's profile
    # (`deployments/<app>/application.toml` `[knowledge]`, OC-R4); settings name none.
    knowledge_subject: str = Field(default="mission-control-runtime", min_length=1)
    knowledge_gateway_max_polls: int = Field(default=10, ge=0, le=100)
    knowledge_binding_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    # The tenant a startup `knowledge.describe` preflight names (no mission invocation exists
    # yet); unset: the installation id. Its scope rule is the executor's (K07).
    knowledge_describe_tenant: str | None = None
    # W1 D6: the KS component installation the binding serves (its `KS_KNOWLEDGE_BINDINGS_JSON`
    # installationId), a distinct identity from this Mission Control installation. Every K01
    # origin MC sends names it; the describe preflight is refused when the executor serves
    # another. Required with KNOWLEDGE_GATEWAY_REQUIRED; otherwise unset means one shared id.
    knowledge_component_installation_id: str | None = Field(
        default=None, min_length=1, max_length=200
    )

    mission_control_catalog_scope: str | None = None
    redis_url: SecretStr = SecretStr("redis://localhost:16379/0")
    runtime_realtime_required: bool = False
    runtime_approval_timeout_seconds: int = Field(default=900, ge=30, le=86_400)
    runtime_checkpoint_signing_key: SecretStr | None = None

    aws_region: str = "us-east-1"
    aws_profile: str | None = "default"
    s3_bucket: str | None = None
    # OVE-204 slice 7: an S3-compatible object store (Supabase Storage's
    # `<project>/storage/v1/s3`). Unset: AWS S3 through the credential chain. https, or http
    # only for a loopback host (the local Supabase stack).
    s3_endpoint_url: str | None = None
    # Path-style addressing (`<endpoint>/<bucket>/<key>`); Supabase serves no virtual hosts.
    s3_force_path_style: bool = False
    # The signing region; unset: `aws_region`. Supabase local signs `local`.
    s3_region: str | None = None
    # Explicit keys take precedence over `aws_profile`; set both or neither.
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    # FT-G7: the local `make temporal-up` server stays the default even when the Cloud key
    # is present; `TEMPORAL_TARGET=cloud` selects Temporal Cloud (api key + TLS).
    temporal_target: Literal["local", "cloud"] = "local"
    temporal_cloud_api_key: SecretStr | None = None
    # FT-G7 Worker Deployment versioning: the deployment name and the build id of this
    # release (defaults to the package version); `false` keeps unversioned workers.
    temporal_worker_versioning: bool = True
    temporal_deployment_name: str = "mission-control"
    temporal_build_id: str | None = None
    temporal_promote_on_start: bool = True
    # FT-G1 lanes: a bound Cursor credential registers the Cursor lane profiles; unqualified
    # lanes are admitted only when this local-proof policy is explicitly enabled.
    cursor_api_key: SecretStr | None = None
    mission_control_allow_unqualified_lanes: bool = False
    # FT-G2: Deep Agents units run through the `lane.turn` segment loop instead of
    # `operation.execute` (Cursor units always do). Off until FT-G6 retires the old path.
    mission_control_lane_segment_loop: bool = False
    # FT-C1: the worker serves `mc.frames_expire.v1` on its maintenance queue and creates (or
    # updates) the per-application retention Schedule at startup; false skips the Schedule.
    mission_control_frames_expire_schedule: bool = True
    # 1.4.4 (tracing, TR-D2a): the frame capture profile every `FrameWriter` site receives
    # from composition (`application/frames/capture_policy.py::CAPTURE_PROFILES`: `standard`
    # promotes per-message objects and oversized closing bodies; `full_requests` also keeps
    # the whole batch of every `model_request`). A system lever, never a manifest field; an
    # unknown name fails composition (`bootstrap/frame_capture.py`).
    mission_control_frame_capture_profile: str = "standard"
    # 1.4.4 (P6.1): the wall-clock budget of the settlement's points walk over the saver;
    # past it the result point records `points_status: incomplete` for the reconciler.
    mission_control_points_walk_budget_ms: int = 5000
    # FT-G3 cursor_local: where workspace leases (git worktrees) live on the worker, the
    # worker-local checkout used when a binding names no repository, and the loopback port of
    # the Kernel Hook callback listener (127.0.0.1 only; started with the worker).
    cursor_lease_root: Path | None = None
    mission_control_cursor_windows: bool = False
    # Opt-in host cleanup considers only released Cursor leases in these trusted scopes.
    # Expired active leases remain recoverable and are never swept by startup.
    mission_control_cursor_bridge_sweep_scopes: tuple[str, ...] = Field(default=(), max_length=16)
    cursor_local_repository: str | None = None
    mission_control_hook_callback_port: int = Field(default=47555, ge=1024, le=65535)
    # MP-05 auth routes: the deployment-registry `mc.auth_profile.v1` records (JSON document
    # `{"profiles": [...]}`, shape in deployments/examples/provider-auth-profiles.example.json).
    # Unset: no profile resolves and credential-route lanes refuse before launch. The status
    # probe runs only read-only vendor status commands (never a login); off by default.
    mission_control_auth_profiles_path: Path | None = None
    mission_control_allow_unqualified_auth_routes: bool = False
    mission_control_auth_status_probe: bool = False
    mission_control_auth_status_timeout_s: float = Field(default=10.0, gt=0, le=120)
    # MP-05 capacity waits (`LimitWaitPolicy`): finite bounds for provider limit responses.
    mission_control_capacity_max_waits: int = Field(default=3, ge=0, le=32)
    mission_control_capacity_max_total_wait_s: int = Field(default=6 * 3600, ge=0)
    mission_control_capacity_reset_margin_s: int = Field(default=5, ge=0, le=600)
    mission_control_capacity_fallback_backoff_s: int = Field(default=30, ge=1)
    mission_control_capacity_max_backoff_s: int = Field(default=900, ge=1)
    # MP-06 session ownership (`WorkerSessionManager`): the minimum lease a worker holds on a
    # harness execution, the lease as a multiple of the lane's heartbeat timeout, and the
    # bounded grace a native dispatch's receipt gets before an activity cancel is honoured.
    mission_control_session_lease_min_s: int = Field(default=10, ge=1, le=3_600)
    mission_control_session_lease_heartbeats: int = Field(default=2, ge=1, le=10)
    mission_control_dispatch_receipt_grace_s: float = Field(default=10.0, ge=0, le=300)
    # MP-12 context pressure (SPEC-01 tuning inputs, not provider guarantees): the worker's
    # policy for Session Lanes until a binding carries its own. Native compaction is used only
    # where a lane's describe says `compaction_control: native` and it implements it.
    mission_control_context_soft_ratio: Decimal = Field(default=Decimal("0.70"), gt=0, le=1)
    mission_control_context_hard_ratio: Decimal = Field(default=Decimal("0.85"), gt=0, le=1)
    mission_control_context_reserve_ratio: Decimal = Field(default=Decimal("0.15"), ge=0, lt=1)
    mission_control_context_max_session_turns: int | None = Field(default=None, ge=1)
    mission_control_continuation_max_transfers: int = Field(default=8, ge=0)
    mission_control_continuation_max_compaction_failures: int = Field(default=2, ge=0)
    mission_control_native_compaction: Literal["preferred", "disabled", "required"] = "preferred"
    # MP-11 native approvals: how long a lane's native permission/question callback waits on
    # its Human Task inside one `lane.turn` segment (segments run up to 30 min) before the
    # native correlation expires; the durable task stays open and a later request re-binds it.
    mission_control_approval_wait_s: float = Field(default=300.0, gt=0, le=600)
    # Who may resolve a native approval task (a principal, or a verified `reviewer:<role>`
    # grant); the `owner` role by default, as for an undeclared Goal Loop review.
    mission_control_approval_reviewers: tuple[str, ...] = ("owner",)
    # MP-07 `claude_agent_sdk` and MP-08 `codex` local lanes: explicit opt-in per worker (they
    # spawn provider subprocesses, so Linux/WSL workers only) plus an MP-05 auth profile path.
    # Unset lease roots default under the sandbox workspace root.
    # The lane task queues this worker serves besides `<base>.agent-cognitive`: the
    # `task_queue` values of the Cursor/Claude/Codex launch bindings routed to this worker pool.
    mission_control_lane_task_queues: tuple[str, ...] = ()
    mission_control_claude_managed_lane: bool = False
    mission_control_codex_agents_lane: bool = False
    mission_control_claude_lane: bool = False
    mission_control_claude_lease_root: Path | None = None
    mission_control_claude_init_timeout_s: float = Field(default=60.0, gt=0, le=600)
    mission_control_claude_drain_timeout_s: float = Field(default=20.0, gt=0, le=600)
    mission_control_codex_lane: bool = False
    mission_control_codex_binary: str = "codex"
    mission_control_codex_lease_root: Path | None = None
    mission_control_codex_home_mode: Literal["isolated", "owner"] = "isolated"
    mission_control_codex_owner_home: Path | None = None
    mission_control_codex_repository: str | None = None
    # Refuse a `codex --version` other than the pinned 0.162.0 unless explicitly overridden.
    mission_control_codex_allow_version_mismatch: bool = False
    # MO-11 Secret Broker (ADR-0043): the installation's store for `secret:`/`vault:`
    # references: none (refused), a JSON file outside every repository, the owner's keyring
    # (entries under the service name) or Supabase Vault over its own DSN. Store paths listed
    # as provider-held are never read, only verified in the provider's store at delivery.
    mission_control_secret_store: Literal["none", "file", "keyring", "supabase_vault"] = "none"  # noqa: S105 - a store kind, not a secret
    mission_control_secret_store_path: Path | None = None
    mission_control_secret_keyring_service: str = "mission-control"  # noqa: S105 - a name
    mission_control_secret_vault_dsn: SecretStr | None = None
    mission_control_provider_held_secrets: tuple[str, ...] = ()
    # MP-14 `/missions` socket (`bootstrap/realtime.py`): relay presence and commit hints
    # between API processes over `redis_url`; off serves one process with PostgreSQL replay.
    mission_socket_redis_fanout: bool = False
    # The 0032 `mc_stream_hint` LISTEN source, one connection per application database.
    mission_socket_postgres_hints: bool = True
    # SPEC-04: an idle connection's credential is re-verified this often (revocation, expiry);
    # a command's accepted/delivered/applied receipts are followed for at most this long.
    mission_socket_reauthorize_seconds: float = Field(default=5.0, gt=0, le=300)
    mission_socket_command_follow_seconds: float = Field(default=120.0, gt=0, le=3_600)
    # MP-15 webhook egress: callbacks go to global addresses over https only; loopback and
    # private networks are admitted only when listed here (local development, in-cluster
    # receivers). Every delivery is pinned to the validated address.
    webhook_allow_loopback: bool = False
    # Set from the trusted application deployment; enables local child signal delivery.
    mission_control_local_signal_ingress: bool = False
    mission_control_signal_ingress_origin: str | None = None
    webhook_allowed_networks: tuple[str, ...] = ()
    # MP-22 local readiness: the `mc.local_run_profile.v1` the preflight gate and the worker
    # startup gate read, and the workspace root capability pins are verified under (unset:
    # the configured capability resource owner, `workspace_root()`).
    mission_control_local_run_profile: Path | None = None
    mission_control_preflight_workspace_root: Path | None = None

    @property
    def allow_unqualified_lanes(self) -> bool:
        return self.mission_control_allow_unqualified_lanes

    # The Temporal queue base. No neutral default (OC-R4 review B2): the environment or the
    # selected application's profile supplies it, a worker takes it from its installation
    # (`TemporalDeployment.queue_base`), and a reader without one fails
    # (`task_queue_base`, `InstallationDefaultUnavailable`).
    temporal_task_queue: str | None = None
    # The capability resource owner (`workspace://` locators); `.env` applies. Unset: the
    # selected application's `[installation] capability_workspace_root`, relative to
    # MISSION_CONTROL_HOME; neither: `workspace_root` fails.
    mission_control_workspace_root: Path | None = None
    # OC-R4: the installation's application id. It selects `deployments/<app>/application.toml`
    # (under the deployments root) whose `[installation]` table supplies the task queue and
    # LangSmith project defaults this process does not set explicitly.
    mission_control_application: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,63}$")
    # Unset: `<MISSION_CONTROL_HOME>/deployments`.
    mission_control_deployments_root: Path | None = None
    sandbox_image: str = "python:3.12-slim"

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    socketio_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def db_plane(self) -> DbPlane:
        """The database plane this process reads, from ``MISSION_CONTROL_APPLICATION``."""

        return plane_for_application(self.mission_control_application)

    @property
    def db(self) -> PlaneDatabase:
        """The resolved database variables of the selected plane (the only reader of them)."""

        plane = self.db_plane
        prefix = f"mc_{plane.lower()}_db_"

        def get(role: str) -> Any:
            return getattr(self, prefix + role, None)

        def text(role: str) -> str | None:
            value = get(role)
            return (value.strip() or None) if isinstance(value, str) else None

        def secret(role: str) -> SecretStr | None:
            return configured(get(role))

        return PlaneDatabase(
            plane=plane,
            project_ref=text("project_ref"),
            url=text("url"),
            publishable_key=secret("publishable_key"),
            secret_key=secret("secret_key"),
            legacy_jwt_secret=secret("legacy_jwt_secret"),
            admin_dsn=secret("admin_dsn"),
            runtime_dsn=secret("runtime_dsn"),
            family_writer_dsn=secret("family_writer_dsn"),
            backfill_dsn=secret("backfill_dsn"),
            checkpoint_dsn=secret("checkpoint_dsn"),
        )

    @property
    def postgres_dsn(self) -> str:
        """The common-database connection: the plane's schema-owner (admin) login."""

        return self.db.required_dsn("admin_dsn", "the common database connection")

    @property
    def application_postgres_dsn(self) -> str:
        """The restricted runtime login (never the admin login)."""

        return self.db.required_dsn("runtime_dsn", "the runtime pool")

    @property
    def has_application_postgres(self) -> bool:
        return self.db.runtime_dsn is not None

    @property
    def application_migration_postgres_dsn(self) -> str:
        # Migration authority is the admin login, never inferred from the runtime credential.
        return self.db.required_dsn("admin_dsn", "migrations")

    @property
    def application_backfill_postgres_dsn(self) -> str:
        return self.db.required_dsn("backfill_dsn", "backfill")

    @property
    def has_application_family_writer_postgres(self) -> bool:
        return self.db.family_writer_dsn is not None

    @property
    def application_family_writer_postgres_dsn(self) -> str:
        return self.db.required_dsn("family_writer_dsn", "atomic family admission")

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip() for origin in self.socketio_cors_origins.split(",") if origin.strip()
        ]

    @property
    def coordinator_jwt_issuer(self) -> str:
        if self.coordinator_mcp_jwt_issuer and self.coordinator_mcp_jwt_issuer.strip():
            return self.coordinator_mcp_jwt_issuer
        url = self.db.url
        if url:
            return f"{url.rstrip('/')}/auth/v1"
        raise IntegrationConfigurationError(
            "COORDINATOR_MCP_JWT_ISSUER or "
            f"{self.db.env_name('url')} is required for coordinator authentication"
        )

    @property
    def checkpoint_signing_key(self) -> bytes:
        secret = self.runtime_checkpoint_signing_key or self.db.secret_key
        if secret is None or not secret.get_secret_value().strip():
            raise IntegrationConfigurationError(
                "RUNTIME_CHECKPOINT_SIGNING_KEY is required for checkpoint signing "
                "when no Supabase signing fallback is configured"
            )
        return secret.get_secret_value().encode()

    @model_validator(mode="after")
    def _checkpoint_runtime_binding(self) -> Settings:
        from mission_control.adapters.deep_agents.persistence import (
            FORBIDDEN_CHECKPOINT_SCHEMAS,
            RUNTIME_SCHEMA,
        )

        schema = self.langgraph_checkpoint_schema
        if schema in FORBIDDEN_CHECKPOINT_SCHEMAS:
            raise ValueError("LANGGRAPH_CHECKPOINT_SCHEMA names a forbidden fallback schema")
        if self.langgraph_checkpoint_setup and schema == RUNTIME_SCHEMA:
            raise ValueError(
                "mission_control_runtime is provisioned only by mission-db runtime-apply"
            )
        if self.bell_labs_environment == "production" and (
            schema != RUNTIME_SCHEMA or self.langgraph_checkpoint_setup
        ):
            raise ValueError(
                "production checkpoints require mission_control_runtime without vendor setup"
            )
        return self

    @model_validator(mode="after")
    def _blank_secrets_are_unset(self) -> Settings:
        """Every optional secret that is present but blank is stored as ``None`` (``configured``).

        Readers test ``is not None`` (the Cursor lane binding, bundle custody, the Temporal Cloud
        key, ...); a blank variable that won over the `.env` must not bind a lane or a credential.
        """

        for name, info in type(self).model_fields.items():
            value = getattr(self, name)
            if (
                isinstance(value, SecretStr)
                and type(None) in get_args(info.annotation)
                and configured(value) is None
            ):
                setattr(self, name, None)
        return self

    @model_validator(mode="after")
    def _db_project_ref_matches_siblings(self) -> Settings:
        """Rule 3 of the database contract: the selected Supabase plane's ``PROJECT_REF`` appears in
        the host or login of every sibling URL/DSN that is set. LOCAL has no project."""

        try:
            view = self.db
        except IntegrationConfigurationError:
            return self  # an unknown application fails where the plane is first needed
        view.check_project_ref()
        return self

    @model_validator(mode="after")
    def _s3_endpoint(self) -> Settings:
        """OVE-204 slice 7: an S3-compatible endpoint is https, or http on a loopback host; the
        explicit key pair is set whole or not at all (secrets are blank-normalized above)."""

        endpoint = (self.s3_endpoint_url or "").strip() or None
        self.s3_endpoint_url = endpoint
        self.s3_region = (self.s3_region or "").strip() or None
        if endpoint is not None:
            parsed = urlsplit(endpoint)
            loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            if not parsed.hostname or not (
                parsed.scheme == "https" or (parsed.scheme == "http" and loopback)
            ):
                raise ValueError(
                    "S3_ENDPOINT_URL must be an https URL (http only for 127.0.0.1 or localhost)"
                )
        if (self.s3_access_key_id is None) != (self.s3_secret_access_key is None):
            raise ValueError("S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY are set together")
        return self

    @model_validator(mode="after")
    def _application_defaults(self) -> Settings:
        """OC-R4: the selected application's `[installation]` defaults, for unset fields only.

        A named application without a readable, valid profile fails settings validation.
        """

        defaults = installation_defaults(self.deployments_root, self.mission_control_application)
        for name in ("temporal_task_queue", "langsmith_project", "agent_server_langsmith_project"):
            value = getattr(defaults, name)
            if value is not None and name not in self.model_fields_set:
                setattr(self, name, value)
        if self.mission_control_workspace_root is None and defaults.capability_workspace_root:
            self.mission_control_workspace_root = PROJECT_ROOT / defaults.capability_workspace_root
        if self.mission_control_workspace_root is not None:
            root = self.mission_control_workspace_root.resolve()
            self.mission_control_workspace_root = root
            tools = root / ".tools"
            for name, value in (
                (
                    "web_research_firecrawl_mcp_module",
                    tools
                    / "reviewed"
                    / "firecrawl-mcp-7232b6d1cdd80335107d53a33b80c902b515a334"
                    / "dist"
                    / "index.js",
                ),
                (
                    "web_research_tavily_mcp_module",
                    tools / "node_modules" / "tavily-mcp" / "build" / "index.js",
                ),
                (
                    "web_research_agent_browser_entrypoint",
                    tools / "node_modules" / "agent-browser" / "bin" / "agent-browser.js",
                ),
            ):
                if getattr(self, name) is None:
                    setattr(self, name, value)
        return self

    @property
    def task_queue_base(self) -> str:
        """The Temporal queue base, or a typed startup failure when nothing supplies it."""

        if not self.temporal_task_queue:
            raise InstallationDefaultUnavailable(
                "no Temporal task queue: set TEMPORAL_TASK_QUEUE, or MISSION_CONTROL_APPLICATION "
                "to an application whose profile names one"
            )
        return self.temporal_task_queue

    @property
    def workspace_root(self) -> Path:
        """The capability resource owner, or a typed startup failure when nothing names it."""

        if self.mission_control_workspace_root is None:
            raise InstallationDefaultUnavailable(
                "no capability resource owner: set MISSION_CONTROL_WORKSPACE_ROOT, or "
                "MISSION_CONTROL_APPLICATION to an application whose profile names one"
            )
        return self.mission_control_workspace_root

    @property
    def deployments_root(self) -> Path:
        """Where `deployments/<app>/application.toml` profiles are read from."""

        return deployments_root(PROJECT_ROOT, self.mission_control_deployments_root)

    @property
    def langgraph_checkpoint_dsn(self) -> str:
        """The saver/store conninfo with exactly one `options=-c search_path=<schema>,pg_temp`.

        A configured DSN that already carries `options` or a search_path is rejected
        (`RuntimeConninfoError`), never silently overridden.
        """

        from mission_control.adapters.deep_agents.persistence import (
            runtime_checkpoint_conninfo,
        )

        checkpoint = self.db.checkpoint_dsn
        value = (
            checkpoint.get_secret_value()
            if checkpoint is not None
            else self.application_postgres_dsn
        )
        return runtime_checkpoint_conninfo(value, self.langgraph_checkpoint_schema)

    @property
    def inspection_cursor_secret(self) -> bytes:
        """The shared inspection cursor key: configured, or derived from the signing key."""

        key = configured(self.inspection_cursor_key)
        if key is not None:
            return key.get_secret_value().encode()
        return hmac.new(
            self.checkpoint_signing_key, b"belllabs.inspection-cursor.v1", "sha256"
        ).digest()


@lru_cache
def get_settings() -> Settings:
    return Settings()
