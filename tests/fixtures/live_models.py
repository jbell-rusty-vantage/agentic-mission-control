"""Tracing Stage 2 (SESSION-STAGE-2 §0, §3): the owner's live models on the tracing stack.

GPT-6 Sol is the parent and GPT-6 Luna the in-process sync subagent, both through the
production `OpenAIExactModelFactory` (the same constructor the worker composes for a pinned
model). The fixture binding of `rrm009_production_stack.technical_binding()` is rebuilt with
the two live model components, so the binding digest, the receipts and every `model_request`
frame name the real models; `LiveTechnicalBinding.components` registers the production factory
under both model digests, wrapped by a `SpendMeter` callback that records each call's usage
and its USD price (the 2026-10 OpenAI standard rates in
`docs/specs/archive/materialization-observation-2026-10/research/openai-hosted-agents.md` §6).

Gated by `BELLABS_RUN_TRACING_LIVE=1` and an OpenAI key (environment or repository `.env`);
the spend of every run is appended to `.scratch/tracing-stage-2/spend.jsonl`.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from dotenv import dotenv_values
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import LLMResult
from tests.fixtures import rrm009_production_stack as technical

from mission_control.adapters.deep_agents.materializer import OpenAIExactModelFactory
from mission_control.adapters.temporal.deployment_composition import DeploymentCapabilityComponents
from mission_control.bootstrap.settings import PROJECT_ROOT
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    DeepAgentModelComponent,
)

LIVE_GATE = "BELLABS_RUN_TRACING_LIVE"
PARENT_MODEL = "gpt-6-sol"
CHILD_MODEL = "gpt-6-luna"
OUTPUT_ROOT = PROJECT_ROOT / ".scratch" / "tracing-stage-2"
SPEND_LEDGER = OUTPUT_ROOT / "spend.jsonl"
# Every live call, appended as it is metered (a killed run still leaves its spend), and spend
# recovered by hand for a run whose calls were not metered (each line names its evidence).
CALLS_ROOT = OUTPUT_ROOT / "calls"
ADJUSTMENTS = OUTPUT_ROOT / "spend-adjustments.jsonl"
# USD per 1M tokens: input, cached input, output (reasoning bills as output).
PRICES: Mapping[str, tuple[float, float, float]] = {
    PARENT_MODEL: (2.00, 0.20, 10.00),
    CHILD_MODEL: (0.10, 0.01, 0.50),
}
# The owner's ceiling for the stage (SESSION-STAGE-2 §0, raised from 10 for §4c).
CEILING_USD = 12.0
# Parent settings: low reasoning (the turn 3 precedent), the Responses API, and streaming with
# usage so the lane records delta frames (§0: streaming on in the live lane profile).
PARENT_SETTINGS: Mapping[str, Any] = {
    "reasoning_effort": "low",
    "use_responses_api": True,
    "streaming": True,
    "stream_usage": True,
}
CHILD_SETTINGS: Mapping[str, Any] = {
    "reasoning_effort": "low",
    "use_responses_api": True,
    "streaming": True,
    "stream_usage": True,
}


def openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key or key.startswith("deterministic-"):
        key = str(dotenv_values(PROJECT_ROOT / ".env").get("OPENAI_API_KEY") or "")
    return key


def require_live() -> str:
    """Skip unless the paid gate is set and a key exists; returns the key (never printed)."""

    if os.environ.get(LIVE_GATE) != "1":
        pytest.skip(f"set {LIVE_GATE}=1 for the paid Sol/Luna tracing fixtures")
    key = openai_key()
    if not key:
        pytest.skip("an OpenAI key is required (environment or repository .env)")
    return key


def live_component(model_name: str, settings: Mapping[str, Any]) -> DeepAgentModelComponent:
    """An exact model component whose digest names the model and its settings (the profile
    digest the ledger records with every run)."""

    profile = {"provider": "openai", "model_name": model_name, "settings": dict(settings)}
    return DeepAgentModelComponent(
        ref=ExactDefinitionRef(
            kind=DefinitionKind.MODEL,
            logical_id=f"model.{model_name}",
            revision=1,
            digest=sha256_digest({"tracing-stage-2": profile}),
        ),
        provider="openai",
        model_name=model_name,
        settings=dict(settings),
        # W1 D16: the strategy LangChain auto-detection gave GPT-6 Sol and Luna in Stage 2.
        structured_output="tool_forced",
    )


def _price(model: str, usage: Mapping[str, Any]) -> float:
    rates = next((value for key, value in PRICES.items() if model.startswith(key)), None)
    if rates is None:
        raise KeyError(f"no price for model {model!r}")
    inputs = int(usage.get("input_tokens") or 0)
    cached = int((usage.get("input_token_details") or {}).get("cache_read") or 0)
    outputs = int(usage.get("output_tokens") or 0)
    return ((inputs - cached) * rates[0] + cached * rates[1] + outputs * rates[2]) / 1_000_000


@dataclass
class SpendMeter:
    """Every live model call's usage and price, in call order (thread-safe; workers run on
    threads of the test process)."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    path: Path | None = None
    # Model calls begun (FX-TR-DISCONNECT cuts the connection while one is in flight) and
    # calls that ended in an error (no usage reached the meter).
    started: int = 0
    errors: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def handler(self, model: str) -> BaseCallbackHandler:
        meter = self

        class _Handler(BaseCallbackHandler):
            def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
                meter.started += 1

            def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
                meter.errors.append(f"{type(error).__name__}: {error}"[:300])

            def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
                usage: dict[str, Any] = {}
                for generations in response.generations:
                    for generation in generations:
                        message = getattr(generation, "message", None)
                        found = getattr(message, "usage_metadata", None)
                        if found:
                            usage = dict(found)
                meter.record(model, usage)

        return _Handler()

    def record(self, model: str, usage: Mapping[str, Any]) -> None:
        row = {
            "at": datetime.now(UTC).isoformat(),
            "model": model,
            "input_tokens": int(usage.get("input_tokens") or 0),
            "cached_tokens": int((usage.get("input_token_details") or {}).get("cache_read") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "reasoning_tokens": int(
                (usage.get("output_token_details") or {}).get("reasoning") or 0
            ),
            "usage_missing": not usage,
            "usd": round(_price(model, usage), 6) if usage else 0.0,
        }
        with self._lock:
            self.calls.append(row)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row) + "\n")

    def total(self) -> dict[str, Any]:
        with self._lock:
            calls = list(self.calls)
        by_model: dict[str, dict[str, Any]] = {}
        for call in calls:
            entry = by_model.setdefault(
                call["model"],
                {"calls": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "usd": 0.0},
            )
            entry["calls"] += 1
            for key in ("input_tokens", "cached_tokens", "output_tokens"):
                entry[key] += call[key]
            entry["usd"] = round(entry["usd"] + call["usd"], 6)
        return {
            "calls": len(calls),
            "calls_without_usage": sum(1 for call in calls if call["usage_missing"]),
            "usd": round(sum(call["usd"] for call in calls), 6),
            "by_model": by_model,
        }


def stage_spend_so_far() -> float:
    """USD of every metered Stage 2 call plus the recovered adjustments (the ceiling check)."""

    files = (
        [*sorted(CALLS_ROOT.glob("*.jsonl")), ADJUSTMENTS] if CALLS_ROOT.exists() else [ADJUSTMENTS]
    )
    total = 0.0
    for path in files:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                total += float(json.loads(line).get("usd") or 0.0)
    return total


def record_spend(
    fixture: str, run_ids: list[str], meter: SpendMeter, **extra: Any
) -> dict[str, Any]:
    """Append one run's spend to the stage ledger before the next run starts (§0)."""

    entry = {
        "at": datetime.now(UTC).isoformat(),
        "fixture": fixture,
        "run_ids": run_ids,
        **meter.total(),
        **extra,
    }
    SPEND_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with SPEND_LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")
    return entry


def metered_factory(meter: SpendMeter) -> Any:
    """The production OpenAI factory with the meter attached to the model it constructs."""

    production = OpenAIExactModelFactory()

    def factory(binding: DeepAgentExecutionBinding, secrets: Any) -> BaseChatModel:
        model = production(binding, secrets)
        model.callbacks = [meter.handler(binding.model.model_name)]
        return model

    return factory


@dataclass(frozen=True)
class LiveTechnicalBinding(technical.TechnicalBinding):
    """The fixture binding with Sol as the parent and Luna as the sync child."""

    meter: SpendMeter = field(default_factory=SpendMeter)
    parent_model: DeepAgentModelComponent | None = None
    child_model: DeepAgentModelComponent | None = None

    def components(self, model_log: list[dict[str, Any]]) -> DeploymentCapabilityComponents:
        base = super().components(model_log)
        factory = metered_factory(self.meter)
        return replace(
            base,
            model_factories={
                self.binding.model.ref.digest: factory,
                self.child_model_ref.digest: factory,
            },
        )

    def profile_digests(self) -> dict[str, str]:
        assert self.parent_model is not None and self.child_model is not None
        return {
            "parent": f"{self.parent_model.model_name} {self.parent_model.ref.digest}",
            "child": f"{self.child_model.model_name} {self.child_model.ref.digest}",
        }


def live_technical_binding(meter: SpendMeter | None = None) -> LiveTechnicalBinding:
    base = technical.technical_binding()
    parent = live_component(PARENT_MODEL, PARENT_SETTINGS)
    child = live_component(CHILD_MODEL, CHILD_SETTINGS)
    children = tuple(
        item.model_copy(update={"model": child}) for item in base.binding.sync_subagents
    )
    binding = DeepAgentExecutionBinding.create(
        **{
            **base.binding.model_dump(mode="python", exclude={"binding_digest"}),
            "model": parent,
            "sync_subagents": children,
        }
    )
    return LiveTechnicalBinding(
        binding=binding,
        bundle=base.bundle,
        child_model_ref=child.ref,
        child_prompt_ref=base.child_prompt_ref,
        hook_bundle=base.hook_bundle,
        hook_component=base.hook_component,
        meter=meter or SpendMeter(),
        parent_model=parent,
        child_model=child,
    )


def worker_commit() -> str:
    head = PROJECT_ROOT / ".git" / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            return (PROJECT_ROOT / ".git" / ref[5:]).read_text(encoding="utf-8").strip()
        return ref
    except OSError:
        return "unknown"


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
