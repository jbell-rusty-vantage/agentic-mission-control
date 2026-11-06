"""W1 D20: the MC auditor's census and the judge's observations round-trip into KS documents.

``ks-evaluation-context-parity.json`` holds the auditor and judge evaluation contexts of the
KS-built registration parity report, rendered and schema-checked by the KS libraries
(``scripts/ks_evaluation_parity.mjs``). The Mission Control evaluator turns them, with scripted
model answers, into ``mc-evaluator-parity.json``: KS validates a byte-identical copy of that file
with its own ``SubmittedCensusSchema`` and ``VerificationObservationSchema`` (KS
``packages/host/src/knowledge-operation/mc-evaluator-parity.test.ts``), so a census KS would refuse
("the census is not a valid discovery", the W1 failure: spans without their basis) fails there, and
this test pins MC's output to that file. Regenerate with ``MC_REGENERATE_EVALUATOR_PARITY=1`` and
copy the file to KS when the evaluator's output legitimately changes.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from mission_control.adapters.deep_agents.evaluators import (
    AuditorAnswer,
    FoundClaim,
    JudgeAnswer,
    ModelEvaluatorRunner,
    Price,
    context_from_document,
)
from mission_control.contracts.knowledge_protocol import Ref, digest_canonical
from tests.unit.knowledge.test_independent_evaluators import (
    NOW,
    Invoker,
    bindings,
    subject,
    verdict,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "knowledge_protocol"
CONTEXTS = json.loads((FIXTURES / "ks-evaluation-context-parity.json").read_text(encoding="utf-8"))
GOLDEN = FIXTURES / "mc-evaluator-parity.json"
# The canonical digest KS's copy of the parity file is pinned to (line endings cannot move it).
PARITY_DIGEST = "sha256:ba0decdbf49dc6a8ca98f5e308b7aaa381fac987dfb86b1cf78738f1059740a7"
PRICES = {"claude-haiku-5-5": Price(1.0, 5.0), "gpt-5.6-terra": Price(2.0, 12.0)}


class Source:
    def __init__(self, role: str) -> None:
        document = CONTEXTS[role]
        self.context = context_from_document(document, Ref.model_validate(document["report"]), role)

    async def load(self, evaluator: Any, report: Ref) -> Any:
        return self.context


def utf16_slice(text: str, start: int, end: int) -> str:
    encoded = text.encode("utf-16-le")
    return encoded[start * 2 : end * 2].decode("utf-16-le")


async def evaluator_outputs() -> dict[str, Any]:
    auditor, judge = await bindings()
    audit = Invoker(
        AuditorAnswer(
            claims=[
                FoundClaim(quote="Mistral 7B has 7 billion parameters", assertion=0),
                FoundClaim(quote="27 billion", assertion=1),
                FoundClaim(quote="Gemma 2 27B is larger", assertion=2),
                FoundClaim(quote="a claim the body never makes"),
            ],
            rationale="every factual sentence of the body, quoted verbatim",
        )
    )
    census = (
        await ModelEvaluatorRunner(
            context=Source("auditor"), invoke=audit, prices=PRICES, clock=lambda: NOW
        ).evaluate(auditor, subject())
    ).census
    judged = Invoker(
        JudgeAnswer(
            verdicts=[
                verdict(assertion=0, cited_fragments=["frag-mistral-7b"]),
                verdict(assertion=1, cited_fragments=["frag-gemma-2-27b"]),
                verdict(
                    assertion=2,
                    support="qualified_support",
                    cited_fragments=["frag-gemma-2-27b"],
                    qualification="compares the largest models only",
                ),
            ]
        )
    )
    observations = (
        await ModelEvaluatorRunner(
            context=Source("judge"), invoke=judged, prices=PRICES, clock=lambda: NOW
        ).evaluate(judge, subject())
    ).observations
    return {"census": census, "observations": list(observations)}


async def test_the_census_spans_quote_the_exact_frozen_body() -> None:
    census = (await evaluator_outputs())["census"]
    text = CONTEXTS["auditor"]["body"]["text"]
    units = {unit["path"]: unit["span"] for unit in CONTEXTS["auditor"]["units"]}
    assert len(census["occurrences"]) == 3
    assert census["limitations"] == ["quote not found verbatim: a claim the body never makes"]
    for occurrence in census["occurrences"]:
        span = occurrence["span"]
        assert span["basis"] == "utf16-code-units-v1" and span["start"] < span["end"]
        quote = utf16_slice(text, span["start"], span["end"])
        assert occurrence["candidateAssertion"] == quote
        digest = "sha256:" + hashlib.sha256(quote.encode("utf-8")).hexdigest()
        assert occurrence["quoteDigest"] == digest
        unit = units[occurrence["blockPath"]]
        assert unit["start"] <= span["start"] and span["end"] <= unit["end"]
        assert occurrence["body"] == CONTEXTS["auditor"]["body"]["artifact"]
        assert occurrence["assertion"]["kind"] == "assertion"  # the exact handle, never a string
    mapped = {item["assertion"]["id"] for item in census["occurrences"]}
    assert mapped == {"asr-mistral-7b", "asr-gemma-2-27b", "asr-ratio"}


async def test_the_judge_reads_propositions_and_fragment_text() -> None:
    _auditor, judge = await bindings()
    invoke = Invoker(
        JudgeAnswer(
            verdicts=[verdict(assertion=i, cited_fragments=["frag-mistral-7b"]) for i in range(3)]
        )
    )
    prompts: list[str] = []

    async def capture(evaluator: Any, instructions: str, body: str, schema: Any) -> Any:
        prompts.append(body)
        return await invoke(evaluator, instructions, body, schema)

    await ModelEvaluatorRunner(
        context=Source("judge"), invoke=capture, prices=PRICES, clock=lambda: NOW
    ).evaluate(judge, subject())
    (prompt,) = prompts
    assert "0. Mistral 7B is a language model with 7 billion parameters." in prompt
    assert "[frag-mistral-7b] We introduce Mistral 7B" in prompt
    assert "'schemaVersion'" not in prompt  # no record dicts printed


async def test_mc_evaluator_output_is_the_ks_validated_parity_file() -> None:
    outputs = await evaluator_outputs()
    rendered = json.dumps(outputs, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    if os.environ.get("MC_REGENERATE_EVALUATOR_PARITY") == "1":
        GOLDEN.write_text(rendered, encoding="utf-8")
    assert GOLDEN.read_text(encoding="utf-8") == rendered
    assert digest_canonical(outputs) == PARITY_DIGEST


async def test_spans_after_astral_and_accented_characters_are_utf16_exact() -> None:
    """Review S1: an emoji is two UTF-16 code units, an accented letter one; KS slices by them."""

    from tests.unit.knowledge.test_independent_evaluators import context, ref

    text = "## Findings\n\n🧪 Café note: dosage 5 mg 💊 confirmed in the trial.\n"
    paragraph = (
        len(text[: text.index("🧪")].encode("utf-16-le")) // 2,
        len(text[: text.index("\n", 14)].encode("utf-16-le")) // 2,
    )
    body = ref("artifact", "body-astral", "sha256:" + hashlib.sha256(text.encode()).hexdigest())
    source = context(body_text=text, body_artifact=body, units=(("s1/p1", *paragraph),))
    auditor, _judge = await bindings()
    invoke = Invoker(
        AuditorAnswer(
            claims=[
                FoundClaim(quote="dosage 5 mg", assertion=0),
                FoundClaim(quote="confirmed in the trial", assertion=0),
            ],
            rationale="two claims after non-ASCII characters",
        )
    )
    census = (
        await ModelEvaluatorRunner(
            context=source, invoke=invoke, prices=PRICES, clock=lambda: NOW
        ).evaluate(auditor, subject())
    ).census
    for occurrence, quote in zip(
        census["occurrences"], ("dosage 5 mg", "confirmed in the trial"), strict=True
    ):
        at = text.index(quote)
        expected = len(text[:at].encode("utf-16-le")) // 2
        span = occurrence["span"]
        assert span["start"] == expected and span["end"] == expected + len(quote)
        assert utf16_slice(text, span["start"], span["end"]) == quote
        assert span["start"] > at  # the emoji moved the UTF-16 offset past the code-point index
