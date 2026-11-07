"""P1: the installation configuration source that ``value_ref: config:<key>`` names.

- ``mc.installation_config.v1`` maps each Application id to its non-secret values; malformed
  files and secret-like keys are typed errors naming keys, never values, and no exception
  context carries the file content.
- With an Application's values, compile resolves a present key, keeps an unknown key a pointed
  ``config_unresolved`` blocker at the environment that set the variable (node overrides too),
  and never reads the value of a secret-like key.
- The production composition (``compose_manifest_service``) selects the composing
  Application's mapping from one Settings file (an Application not listed has none), and fails
  loudly when it cannot load the file or select an Application; unset, every key blocks.

Offline: fixture catalog, in-memory compiler, no database, provider or Temporal.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import asyncpg
import pytest

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_service import (
    ManifestCompilation,
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.application.capabilities.catalog import CatalogService
from mission_control.application.environments.kits import (
    CatalogEnvironmentInputs,
    EnvironmentKitCatalog,
)
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.bootstrap import manifests
from mission_control.bootstrap.installation_config import (
    INSTALLATION_CONFIG_SCHEMA,
    MAX_VALUE_LENGTH,
    InstallationConfigError,
    InstallationConfigSecretLikeKey,
    load_installation_config,
    value_digest,
)
from mission_control.bootstrap.settings import Settings
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.mission_environment import is_secret_like_config_key
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.environment_kits import StaticDefinitions
from tests.unit.authoring.test_manifest_v2_environment import (
    AT,
    ENV,
    NODE,
    SCOPE,
    _set,
    blockers,
    manifest,
)

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "deployments/examples/installation-config.example.json"
KEY = "knowledge_services.public_url"
# FIXTURE: a distinctive value that must never be echoed by an error, a repr or compile output.
SENTINEL = "p1-installation-sentinel-41d2"
# The installation catalog of the fixture scope: mc/{installation}/{app}/catalog.
CATALOG_SCOPE = SCOPE.rsplit("/", 1)[0] + "/catalog"
HEADER = '{"schema": "mc.installation_config.v1", "applications": '


def write_config(
    tmp_path: Path,
    values: Mapping[str, object] | None = None,
    *,
    applications: Mapping[str, object] | None = None,
    **fields: object,
) -> Path:
    """FIXTURE: ``values`` as the ai-engineer Application's, or ``applications`` verbatim."""

    path = tmp_path / "installation-config.json"
    document = {
        "schema": INSTALLATION_CONFIG_SCHEMA,
        "applications": dict(applications)
        if applications is not None
        else {"ai-engineer": dict(values or {})},
        **fields,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _raw(tmp_path: Path, text: str | bytes) -> Path:
    path = tmp_path / "raw.json"
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def kitless(change: Callable[..., None] | None = None) -> str:
    """The environment test's manifest without its kit: the configuration is under test."""

    def edit(document: dict[str, Any]) -> None:
        document["mission"]["environment"].pop("kit")
        if change is not None:
            change(document)

    return manifest(change=edit)


class RecordingInputs(CatalogEnvironmentInputs):
    """FIXTURE: the production port, recording which keys compile asked a value for."""

    def __init__(self, config: Mapping[str, str]) -> None:
        super().__init__(EnvironmentKitCatalog(StaticDefinitions()), config=config)
        self.asked: list[str] = []

    async def config_value(self, key: str) -> str | None:
        self.asked.append(key)
        return await super().config_value(key)


async def _compile(text: str, inputs: CatalogEnvironmentInputs) -> ManifestCompilation:
    definitions, search = await fast_track_catalog()
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
        environment_inputs=inputs,
    )
    return await service.compile(text, ManifestScope(request_scope=SCOPE, actor_id="owner", at=AT))


def compile_with(
    text: str, config: Mapping[str, str] | CatalogEnvironmentInputs
) -> ManifestCompilation:
    inputs = config if isinstance(config, CatalogEnvironmentInputs) else RecordingInputs(config)
    return asyncio.run(_compile(text, inputs))


# --- Loading ----------------------------------------------------------------------------------


def test_the_example_file_lists_each_application_with_sorted_keys() -> None:
    config = load_installation_config(EXAMPLE)
    assert tuple(config.applications) == ("ai-engineer", "biotech")
    assert tuple(config.values_for("ai-engineer")) == ("knowledge_services.public_url", "log.level")
    assert dict(config.values_for("biotech")) == {}
    # An Application the file does not list has no values (its keys stay blockers).
    assert dict(config.values_for("unlisted-app")) == {}
    assert config.value_digests("ai-engineer")["log.level"] == value_digest("info")
    assert value_digest("info").startswith("sha256:") and len(value_digest("info")) == 71


def test_values_never_appear_in_the_repr_or_the_digests(tmp_path: Path) -> None:
    config = load_installation_config(write_config(tmp_path, {KEY: SENTINEL}))
    assert config.values_for("ai-engineer")[KEY] == SENTINEL
    assert SENTINEL not in repr(config)
    assert SENTINEL not in json.dumps(config.value_digests("ai-engineer"))
    assert KEY in repr(config) and "ai-engineer" in repr(config)


@pytest.mark.parametrize(
    "key",
    [
        "service.api_key",
        "GITHUB_TOKEN",
        "client.Secret",
        "db.password",
        "legacy_passwd",
        "supabase.dsn",
        "gcp.credentials",
    ],
)
def test_a_secret_like_key_is_refused_at_load_naming_only_the_key(tmp_path: Path, key: str) -> None:
    assert is_secret_like_config_key(key)
    # Any Application's secret-like key refuses the whole file.
    path = write_config(
        tmp_path, applications={"ai-engineer": {KEY: "https://ks"}, "biotech": {key: SENTINEL}}
    )
    with pytest.raises(InstallationConfigSecretLikeKey) as raised:
        load_installation_config(path)
    assert raised.value.key == key
    assert key in str(raised.value)
    assert SENTINEL not in str(raised.value)


@pytest.mark.parametrize(
    ("build", "match"),
    [
        (lambda tmp: tmp / "absent.json", "unreadable"),
        (lambda tmp: _raw(tmp, b'{"x": "\xff' + SENTINEL.encode() + b'"}'), "unreadable"),
        (lambda tmp: _raw(tmp, HEADER + '{"ai-engineer": {"a": "' + SENTINEL), "not JSON"),
        (
            lambda tmp: _raw(tmp, HEADER + '{"ai-engineer": {"a.b": ' + "1" * 5000 + "}}}"),
            "not JSON",
        ),
        (lambda tmp: _raw(tmp, json.dumps([SENTINEL])), "JSON object"),
        (lambda tmp: write_config(tmp, {KEY: SENTINEL}, schema="mc.other.v1"), "schema must"),
        (lambda tmp: write_config(tmp, {KEY: SENTINEL}, extra=SENTINEL), "unknown fields: extra"),
        (lambda tmp: write_config(tmp, applications={"AI": {KEY: SENTINEL}}), "application id"),
        (lambda tmp: write_config(tmp, applications={"ai-engineer": [SENTINEL]}), "must map"),
        (lambda tmp: write_config(tmp, {"bad key": SENTINEL}), "does not match"),
        (lambda tmp: write_config(tmp, {KEY: 7}), "must be a string"),
        (lambda tmp: write_config(tmp, {KEY: "x" * (MAX_VALUE_LENGTH + 1)}), "exceeds"),
        (lambda tmp: write_config(tmp, {KEY: SENTINEL + "\n"}), "control characters"),
        (
            lambda tmp: _raw(
                tmp, HEADER + f'{{"ai-engineer": {{"{KEY}": "{SENTINEL}", "{KEY}": "x"}}}}}}'
            ),
            "duplicate",
        ),
    ],
)
def test_an_invalid_file_is_a_typed_error_that_never_echoes_a_value(
    tmp_path: Path, build: Callable[[Path], Path], match: str
) -> None:
    with pytest.raises(InstallationConfigError, match=match) as raised:
        load_installation_config(build(tmp_path))
    assert SENTINEL not in str(raised.value)
    # Raised outside any handler: no JSONDecodeError.doc / UnicodeDecodeError.object rides along.
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


# --- Compile with an Application's values -------------------------------------------------------


def test_a_present_key_resolves_with_no_configuration_blocker(tmp_path: Path) -> None:
    config = load_installation_config(write_config(tmp_path, {KEY: SENTINEL}))
    compilation = compile_with(kitless(), config.values_for("ai-engineer"))
    assert compilation.ok, blockers(compilation)
    assert compilation.resolution is not None
    dumped = compilation.report.model_dump_json() + compilation.resolution.model_dump_json()
    dumped += "".join(item.model_dump_json() for item in compilation.definitions)
    assert SENTINEL not in dumped


def test_an_unknown_key_stays_config_unresolved(tmp_path: Path) -> None:
    config = load_installation_config(write_config(tmp_path, {"other.url": "https://x"}))
    compilation = compile_with(kitless(), config.values_for("ai-engineer"))
    assert blockers(compilation) == {f"{ENV}/variables/1/value_ref": "config_unresolved"}


def test_a_secret_like_key_is_refused_with_an_empty_source_and_its_value_never_read() -> None:
    text = kitless(_set("mission/environment/variables/1/value_ref", "config:github.token"))
    empty = RecordingInputs({})
    assert blockers(compile_with(text, empty)) == {
        f"{ENV}/variables/1/value_ref": "config_secret_like"
    }
    # Even a source that supplies the key is not asked for its value.
    supplied = RecordingInputs({"github.token": SENTINEL})
    compilation = compile_with(text, supplied)
    assert blockers(compilation) == {f"{ENV}/variables/1/value_ref": "config_secret_like"}
    assert "github.token" not in empty.asked + supplied.asked
    assert SENTINEL not in compilation.report.model_dump_json()


def test_a_node_override_points_at_the_node_environment() -> None:
    def override(document: dict[str, Any]) -> None:
        document["mission"]["program"]["nodes"][0].setdefault("environment", {})["variables"] = [
            {"name": "NODE_URL", "value_ref": "config:node.url"}
        ]

    text = kitless(override)
    # The node's own key is unknown: the blocker names the node, not the mission environment.
    missing = compile_with(text, {KEY: "https://ks"})
    assert blockers(missing) == {f"{NODE}/variables/0/value_ref": "config_unresolved"}
    # Configured, the override resolves; the mission-level key still resolves as before.
    resolved = compile_with(text, {KEY: "https://ks", "node.url": "https://node"})
    assert resolved.ok, blockers(resolved)
    # An unknown mission-level key still points at the mission environment.
    mission_missing = compile_with(
        kitless(_set("mission/environment/variables/1/value_ref", "config:no.such.url")),
        {KEY: "https://ks"},
    )
    assert blockers(mission_missing) == {f"{ENV}/variables/1/value_ref": "config_unresolved"}


# --- Production composition --------------------------------------------------------------------


class _Recorded:
    environment_inputs: Any = None


def _compose(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    *,
    request_scope: str = SCOPE,
    binding: ApplicationBinding | None = None,
) -> CatalogEnvironmentInputs:
    """``compose_manifest_service`` with a pool it never touches at composition."""

    recorded = _Recorded()
    real = manifests.ManifestCompileService

    def recording(**kwargs: Any) -> ManifestCompileService:
        recorded.environment_inputs = kwargs["environment_inputs"]
        return real(**kwargs)

    monkeypatch.setattr(manifests, "ManifestCompileService", recording)
    definitions, search = asyncio.run(fast_track_catalog())
    catalog = CatalogService(
        request_scope=request_scope,
        catalog_scope=CATALOG_SCOPE,
        definitions=definitions,
        search=search,
    )
    manifests.compose_manifest_service(
        cast(asyncpg.Pool, object()),
        request_scope=request_scope,
        catalog=catalog,
        extensions=ExtensionRegistry(),
        payload_store=InMemoryPayloadStore(),
        settings=settings,
        application_binding=binding,
    )
    inputs = recorded.environment_inputs
    assert isinstance(inputs, CatalogEnvironmentInputs)
    return inputs


def _binding(application_id: str) -> ApplicationBinding:
    return ApplicationBinding.seal(
        application_id=application_id,
        installation_id=UUID(int=1),
        binding_version="1",
        supabase_project_ref="fixture",
        database_secret_ref="TEST_RUNTIME_DSN",
        accepted_issuers=frozenset({"https://issuer.example"}),
        accepted_audiences=frozenset({"mission-control"}),
        required_component_version="1",
    )


def _settings(path: Path | None) -> Settings:
    return Settings(
        _env_file=None,
        mission_control_installation_config_path=path,
        mission_control_catalog_scope=CATALOG_SCOPE,
    )


def test_composition_wires_the_configured_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No binding: the canonical request scope names the composing Application.
    inputs = _compose(monkeypatch, _settings(write_config(tmp_path, {KEY: SENTINEL})))
    assert asyncio.run(inputs.config_value(KEY)) == SENTINEL
    assert asyncio.run(inputs.config_value("other.url")) is None


def test_composition_without_a_file_keeps_every_key_a_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _compose(monkeypatch, _settings(None))
    assert asyncio.run(inputs.config_value(KEY)) is None


def test_two_applications_compose_from_one_settings_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API composes every Application of a deployment with the same Settings: each
    selects its own mapping, and one the file leaves out composes with none."""

    settings = _settings(write_config(tmp_path, {KEY: SENTINEL}))
    engineer = _compose(monkeypatch, settings, binding=_binding("ai-engineer"))
    biotech = _compose(monkeypatch, settings, binding=_binding("biotech"))
    assert asyncio.run(engineer.config_value(KEY)) == SENTINEL
    assert asyncio.run(biotech.config_value(KEY)) is None
    # Through compile: the same manifest resolves for one Application and blocks for the other.
    assert compile_with(kitless(), engineer).ok
    assert blockers(compile_with(kitless(), biotech)) == {
        f"{ENV}/variables/1/value_ref": "config_unresolved"
    }


def test_composition_fails_loudly_when_the_file_cannot_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(InstallationConfigError, match="unreadable"):
        _compose(monkeypatch, _settings(tmp_path / "absent.json"))
    # Another Application's secret-like key fails every Application's composition.
    secret = write_config(tmp_path, applications={"biotech": {"service.api_key": SENTINEL}})
    with pytest.raises(InstallationConfigSecretLikeKey):
        _compose(monkeypatch, _settings(secret), binding=_binding("ai-engineer"))


def test_composition_without_a_known_application_refuses_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(write_config(tmp_path, {KEY: SENTINEL}))
    # Only a non-canonical scope without a binding leaves the Application unknown; the
    # typed refusal comes before any later scope check, and never loads the file unchecked.
    with pytest.raises(InstallationConfigError, match="no Application is known") as raised:
        _compose(monkeypatch, settings, request_scope="not-a-canonical-scope")
    assert SENTINEL not in str(raised.value)
