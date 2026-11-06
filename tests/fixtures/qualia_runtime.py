"""Live Qualia fixture composition; actual model calls and finite shared spend custody.

This module does not select a production installation or grant report-use authority.
The ordinary manifest author, admitted bindings and output service remain authoritative.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from scripts.overnight_evidence import redact

from mission_control.adapters.deep_agents.materializer import OpenAIExactModelFactory
from mission_control.adapters.temporal.deployment_composition import DeploymentCapabilityComponents
from mission_control.application.authoring.manifest_launch_inputs import ServedModel
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.execution.contracts import DeepAgentExecutionBinding
from mission_control.domain.resolution.profiles import ModelProfile


class SpendLedger:
    """Conservative model spend: charge all inputs at the cache-write rate.

    Runtime model requests reserve USD 2 before dispatch. Request messages and model
    parameters are bounded to 700k serialized bytes and 16k output tokens; even
    charging one input token per byte, the reservation exceeds that cost on
    both selected Standard models. Failed requests retain their reservation.
    Web reservations and margin are separate, within USD 40 held outside this ledger.
    """

    def __init__(self, root: Path, *, limit: float = 60.0) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "model-usage.jsonl"
        self.limit = limit
        self.lock = threading.RLock()
        self.reservations: dict[str, float] = {}
        self.spent = 0.0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row["event"] == "reserved":
                    self.reservations[row["call_id"]] = row["usd"]
                elif row["event"] == "completed":
                    self.reservations.pop(row["call_id"], None)
                    self.spent += row["estimated_usd_upper_bound"]

    def append(self, row: dict[str, Any]) -> None:
        row = {"at": datetime.now(UTC).isoformat(), **row}
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(redact(row), ensure_ascii=False) + "\n")

    def reserve(self, call_id: str, messages: Any, coordinates: dict[str, Any]) -> None:
        # A byte bound is intentionally conservative: no character/token heuristic
        # can silently admit an arbitrarily large request.
        serialized = json.dumps(messages, default=str, ensure_ascii=False).encode("utf-8")
        if len(serialized) > 700_000:
            raise ValueError("Qualia fixture model request byte budget exceeded (700000)")
        with self.lock:
            if self.spent + sum(self.reservations.values()) + 2 > self.limit:
                raise ValueError("Qualia fixture shared model dollar budget exhausted")
            self.reservations[call_id] = 2.0
            self.append(
                {
                    "event": "reserved",
                    "call_id": call_id,
                    "usd": 2.0,
                    "request_bytes": len(serialized),
                    **coordinates,
                }
            )

    def complete(self, call_id: str, response: Any, coordinates: dict[str, Any]) -> None:
        usage: dict[str, Any] = {}
        outputs = []
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                if message is not None:
                    usage = getattr(message, "usage_metadata", None) or usage
                    outputs.append(message.model_dump(mode="json"))
        if not usage:
            self.append({"event": "usage_missing", "call_id": call_id, **coordinates})
            return  # retain full reservation when the provider omitted usage
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        factor = 1.0 if coordinates["model"] == "gpt-6.1-sol" else 0.5
        charge = factor * (input_tokens * 2.5 + output_tokens * 10) / 1_000_000
        with self.lock:
            self.reservations.pop(call_id, None)
            self.spent += charge
            self.append(
                {
                    "event": "completed",
                    "call_id": call_id,
                    "usage": usage,
                    "estimated_usd_upper_bound": charge,
                    "outputs": outputs,
                    **coordinates,
                }
            )


class LiveModelObserver(BaseCallbackHandler):
    raise_error = True

    def __init__(self, ledger: SpendLedger, coordinates: dict[str, Any]) -> None:
        self.ledger, self.coordinates = ledger, coordinates

    def on_chat_model_start(
        self, serialized: Any, messages: Any, *, run_id: Any, **kwargs: Any
    ) -> None:
        del serialized
        self.ledger.reserve(
            str(run_id),
            {
                "messages": messages,
                "parameters": kwargs.get("invocation_params", {}),
            },
            self.coordinates,
        )

    def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        del kwargs
        self.ledger.complete(str(run_id), response, self.coordinates)

    def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        del kwargs
        self.ledger.append(
            {
                "event": "failed",
                "call_id": str(run_id),
                "error_type": type(error).__name__,
                **self.coordinates,
            }
        )


def model_profile(model_id: str = "gpt-6.1-sol", *, prefix: str = "qualia") -> ModelProfile:
    if model_id not in {"gpt-6.1-sol", "gpt-6.1-terra"}:
        raise ValueError("model outside owner-authorized selection")
    factor = 1.0 if model_id == "gpt-6.1-sol" else 0.5
    return ModelProfile(
        profile=f"{prefix}." + model_id.rsplit("-", 1)[-1],
        vendor="openai",
        model_id=model_id,
        context_window_tokens=1_050_000,
        max_input_tokens=90_000,
        cost_per_million_input=2.5 * factor,
        cost_per_million_output=10 * factor,
        supports=("structured_output", "tool_use"),
        structured_output="tool_auto",
        api_surface="responses",
        data_class_ceiling="internal",
    )


def live_technical_binding(technical: Any, profile: ModelProfile) -> Any:
    ref = ExactDefinitionRef(
        kind=DefinitionKind.MODEL,
        logical_id="model.qualia." + profile.model_id,
        revision=1,
        digest=sha256_digest(
            {
                "profile": profile.model_dump(mode="json"),
                "transport": "OpenAI Responses via ChatOpenAI",
            }
        ),
    )
    model = technical.binding.model.model_copy(
        update={
            "ref": ref,
            "provider": "openai",
            "model_name": profile.model_id,
            "structured_output": "tool_auto",
            "settings": {
                "use_responses_api": True,
                "reasoning_effort": "low",
                "max_completion_tokens": 16_000,
                "service_tier": "default",
            },
        }
    )
    bound = DeepAgentExecutionBinding.create(
        **{
            **technical.binding.model_dump(mode="python", exclude={"binding_digest"}),
            "model": model,
        }
    )
    return replace(technical, binding=bound)


def live_components(technical: Any, ledger: SpendLedger, *, tools: Any, skills: Any) -> Any:
    """Real exact factory; synthetic child/MCP components are deliberately not registered."""

    def factory(bound: Any, secrets: Any) -> Any:
        model = OpenAIExactModelFactory()(bound, secrets)
        model.callbacks = [
            LiveModelObserver(
                ledger,
                {
                    "run_id": bound.run_id,
                    "operation_id": bound.operation_id,
                    "model": bound.model.model_name,
                },
            )
        ]
        return model

    model = technical.binding.model
    return DeploymentCapabilityComponents(
        model_factories={model.ref.digest: factory},
        model_identities={model.ref.digest: ServedModel(model.provider, model.model_name)},
        tools=tools,
        skill_bundles=skills,
    )


def evaluator_model(ledger: SpendLedger, *, role: str, model_id: str) -> ChatOpenAI:
    model_profile(model_id)  # enforce authorization
    return ChatOpenAI(
        model=model_id,
        api_key=SecretStr(os.environ["OPENAI_API_KEY"]),
        use_responses_api=True,
        reasoning_effort="medium",
        max_completion_tokens=16_000,
        max_retries=0,
        service_tier="default",
        callbacks=[LiveModelObserver(ledger, {"role": role, "model": model_id})],
    )
