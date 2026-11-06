"""Retrieve immutable goal verifier checks without promoting them to mission acceptance."""

import json
from dataclasses import asdict

import asyncpg
from pydantic import TypeAdapter

from mission_control.adapters.postgres.documents import PostgresDocumentStore
from mission_control.contracts.run_evidence import (
    GoalCompletionEvidencePage,
    GoalValidationEvidence,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.programs.completion import CompletionValidation
from mission_control.domain.programs.contracts import GoalVerificationResult


class PostgresGoalCompletionEvidenceReader:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._documents = PostgresDocumentStore(pool)

    async def read(
        self, scope: str, run_id: str, after: str | None, limit: int
    ) -> GoalCompletionEvidencePage:
        if not 1 <= limit <= 100:
            raise ValueError("invalid goal completion page limit")
        decisions = []
        documents = await self._documents.list(request_scope=scope, contract="goal.verification/1")
        for document in sorted(documents, key=lambda item: (item.recorded_at, item.identity)):
            bound_run, verification_id = json.loads(document.identity)
            if bound_run != run_id or "completion_validation" not in document.payload:
                continue
            verification = TypeAdapter(GoalVerificationResult).validate_python(
                document.payload["verification"]
            )
            payload = asdict(verification)
            digest = payload.pop("verification_digest")
            if (
                verification.executor_identity.iteration.run_id != run_id
                or verification.verification_id != verification_id
                or sha256_digest(payload) != digest
            ):
                raise ValueError("goal validation identity/digest mismatch")
            decisions.append(
                GoalValidationEvidence(
                    run_id=run_id,
                    document_digest=document.digest,
                    request_digest=document.payload["request_digest"],
                    verification=verification,
                    validation=CompletionValidation.model_validate(
                        document.payload["completion_validation"]
                    ),
                )
            )
        if after is not None:
            matches = [
                i for i, item in enumerate(decisions) if item.verification.verification_id == after
            ]
            if not matches:
                raise ValueError("goal completion cursor is not in this run")
            decisions = decisions[matches[0] + 1 :]
        return GoalCompletionEvidencePage(
            run_id=run_id,
            status="recorded" if decisions else "not_recorded",
            decisions=tuple(decisions[:limit]),
            next_verification_id=decisions[limit - 1].verification.verification_id
            if len(decisions) > limit
            else None,
        )
