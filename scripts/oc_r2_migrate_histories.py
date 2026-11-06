"""OC-R2 one-off: rewrite captured Temporal history payloads from the three removed lane slots to
`lane_binding` + `lane_dispatch` (direct cutover; histories disposable, SV-D11).

Each JSON payload (`{"metadata": ..., "data": <base64 JSON>}`) is decoded; every object carrying
`deep_agent_binding`, `cursor_binding` or `provider_binding` has the typed binding validated with
its own contract, sealed by that contract (`.seal()`) and its dispatch stated
(`.lane_dispatch()`), exactly as the launch author and the families now do. Everything else in
the history (events, commands, markers, timestamps) is untouched, so a replay still proves the
recorded command sequence. Kept for reproducibility of the OC-R2 cutover; usage:
``uv run python scripts/oc_r2_migrate_histories.py DIR...`` (the two history directories).
"""

import base64
import json
import pathlib
import sys

from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import DeepAgentExecutionBinding
from mission_control.domain.execution.lanes import CursorExecutionBinding

SLOTS = {
    "deep_agent_binding": DeepAgentExecutionBinding,
    "cursor_binding": CursorExecutionBinding,
    "provider_binding": ProviderExecutionBinding,
}


def migrate(node):
    changed = False
    if isinstance(node, dict):
        if any(key in node for key in SLOTS):
            sealed = None
            for key, model in SLOTS.items():
                value = node.pop(key, None)
                if value is None:
                    continue
                if sealed is not None:
                    raise ValueError("an object carries two typed lane bindings")
                binding = model.model_validate(value)
                sealed = binding
            if sealed is not None:
                node["lane_binding"] = sealed.seal().model_dump(mode="json")
                generation = 1
                if isinstance(sealed, DeepAgentExecutionBinding):
                    dispatch = sealed.lane_dispatch()
                else:
                    dispatch = sealed.lane_dispatch(generation)
                node["lane_dispatch"] = dispatch.model_dump(mode="json")
            changed = True
        for value in node.values():
            changed = migrate(value) or changed
        # An operation workflow request: the dispatch follows the attempt's generation (the
        # families now state it; a Deep Agents binding already carries the same one).
        operation = node.get("operation")
        generation = node.get("execution_generation")
        if (
            isinstance(operation, dict)
            and isinstance(operation.get("lane_dispatch"), dict)
            and isinstance(generation, int)
        ):
            operation["lane_dispatch"]["execution_generation"] = generation
    elif isinstance(node, list):
        for item in node:
            changed = migrate(item) or changed
    return changed


def rewrite_payloads(node):
    count = 0
    if isinstance(node, dict):
        data = node.get("data")
        if isinstance(data, str) and "metadata" in node:
            try:
                text = base64.b64decode(data).decode("utf-8")
                document = json.loads(text)
            except (ValueError, UnicodeDecodeError):
                document = None
            if document is not None and migrate(document):
                encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=False)
                node["data"] = base64.b64encode(encoded.encode("utf-8")).decode("ascii")
                count += 1
        for value in node.values():
            count += rewrite_payloads(value)
    elif isinstance(node, list):
        for item in node:
            count += rewrite_payloads(item)
    return count


for root in sys.argv[1:]:
    for path in sorted(pathlib.Path(root).rglob("*.json")):
        raw = path.read_bytes()
        crlf = b"\r\n" in raw
        document = json.loads(raw.decode("utf-8"))
        count = rewrite_payloads(document)
        if count:
            text = json.dumps(document, indent=2, ensure_ascii=False)
            if raw.endswith(b"\n"):
                text += "\n"
            if crlf:
                text = text.replace("\n", "\r\n")
            path.write_bytes(text.encode("utf-8"))
        print(f"{path}: {count} payloads")
