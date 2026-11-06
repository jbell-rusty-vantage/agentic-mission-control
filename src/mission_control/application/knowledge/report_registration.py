"""Host-canonicalized report registration (W1 D1; OUTPUT-CONTRACTS §4, ADR-0059/0060).

KS ``report.register`` (``research-report/v2``) matches support sets, premises, claims and
citations to the records they name by ``recordRef`` digest (the ``kop-canonical-json.v1``
SHA-256 of the whole record), binds the exact qualifiers by ``qualifiersDigest`` and a
``text_quote`` fragment by the digest and byte size of its exact selected bytes. A model cannot
compute those digests, and it never supplies an origin. So the producer submits **content
only** and the host computes every digest KS requires before the effect is journaled:

* every record of the registration (task, fragments, assertions, support sets) is completed
  with its schema version and the invocation's tenant and binding (a different one refuses);
* every assertion's ``producer`` is the host-built originating origin (model-supplied: refused);
* a ``text_quote`` fragment's ``selectedDigest``/``selectedSize`` are over the exact UTF-8 bytes
  of its quote (no normalization); any other selector names bytes the host does not hold, so
  its digest and size must be given;
* a reference to a record of the same registration may be its id alone (or a partial ref): the
  host resolves it to the record's exact ``Ref`` after that record is complete (premises in
  dependency order; a cycle refuses). A support set's ``qualifiersDigest`` is computed from its
  assertion's exact qualifiers;
* a reference to a record outside the registration (artifacts, rubric, policy, an earlier
  report's assertion) must be complete: the host fills only tenant and binding, and one naming
  another tenant or binding refuses ``RECORD_SCOPE_MISMATCH``.

A report predecessor may be the public receipt pair ``{handle, digest}``: the host parses
its exact report identity and binds its scope, preserving complete scoped Ref inputs too.
This normalization grants no lineage authority; the binding must validate the exact predecessor.

A digest the model did supply is checked, never trusted: a mismatch refuses
``REF_DIGEST_MISMATCH`` / ``SELECTED_DIGEST_MISMATCH``. Claims stay model-authored: nothing here
writes a proposition, quote, value or body text. The function is pure: the same content, scope
and producer always give the same bytes (so a retried effect carries the same digest).
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any, Final

from pydantic import ValidationError

from mission_control.contracts.knowledge_protocol import (
    Origin,
    Ref,
    canonical_json,
    digest_bytes,
    digest_canonical,
)

TASK_SCHEMA: Final = "research-core.task.v2"
FRAGMENT_SCHEMA: Final = "research-core.fragment.v2"
ASSERTION_SCHEMA: Final = "research-core.assertion.v2"
SUPPORT_SET_SCHEMA: Final = "research-core.support_set.v2"
STRUCTURED_BODY_SCHEMA: Final = "research-core.structured_body.v2"
SECTIONS: Final = ("task", "fragments", "assertions", "supportSets", "report")
_SCHEMAS: Final = {
    "task": TASK_SCHEMA,
    "fragment": FRAGMENT_SCHEMA,
    "assertion": ASSERTION_SCHEMA,
    "support_set": SUPPORT_SET_SCHEMA,
}
_REF_FIELDS: Final = ("kind", "id", "version", "digest", "tenant", "binding")


class RegistrationRefused(ValueError):
    """The submitted report content cannot be registered exactly (typed, never prose control)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _refuse(code: str, message: str) -> RegistrationRefused:
    return RegistrationRefused(code, message)


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _refuse("REGISTRATION_MALFORMED", f"{where} must be an object")
    return value


def _records(content: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    value = content.get(name, [])
    if not isinstance(value, list):
        raise _refuse("REGISTRATION_MALFORMED", f"{name} must be a list")
    return [_object(item, f"{name}[{index}]") for index, item in enumerate(value)]


class _Scope:
    def __init__(self, tenant: str, binding: str) -> None:
        self.tenant = tenant
        self.binding = binding

    def identify(self, record: dict[str, Any], kind: str, where: str) -> str:
        """Complete the record's identity (schema version, tenant, binding); return its id."""

        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            raise _refuse("REGISTRATION_MALFORMED", f"{where} needs an id")
        schema = _SCHEMAS[kind]
        if record.setdefault("schemaVersion", schema) != schema:
            raise _refuse("REGISTRATION_MALFORMED", f"{where} is not a {schema} record")
        for field, value in (("tenant", self.tenant), ("binding", self.binding)):
            if record.setdefault(field, value) != value:
                raise _refuse(
                    "RECORD_SCOPE_MISMATCH", f"{where} names another {field} than this invocation"
                )
        return record_id

    def external(self, value: Any, kind: str, where: str) -> dict[str, Any]:
        """A reference to a record outside this registration: complete but for its scope."""

        ref = _object(copy.deepcopy(value), where)
        ref.setdefault("kind", kind)
        for field, scoped in (("tenant", self.tenant), ("binding", self.binding)):
            # A reference never widens scope: another tenant or binding refuses here, not at KS.
            if ref.setdefault(field, scoped) != scoped:
                raise _refuse(
                    "RECORD_SCOPE_MISMATCH", f"{where} names another {field} than this invocation"
                )
        missing = [field for field in _REF_FIELDS if not isinstance(ref.get(field), str)]
        if missing:
            raise _refuse(
                "REF_UNRESOLVED",
                f"{where} names no record of this registration and is incomplete "
                f"(missing {', '.join(missing)})",
            )
        if ref["kind"] != kind:
            raise _refuse("REGISTRATION_MALFORMED", f"{where} must reference a {kind}")
        return ref

    def predecessor(self, value: Any) -> dict[str, Any]:
        """Normalize the public receipt pair; scope stays host-owned, KS validates lineage."""
        given = _object(value, "report supersedes")
        if "handle" in given:
            if set(given) != {"handle", "digest"}:
                raise _refuse(
                    "REGISTRATION_MALFORMED", "supersedes receipt needs only handle and digest"
                )
            handle = given["handle"]
            if not isinstance(handle, str) or not handle.startswith("kh:"):
                raise _refuse("REF_UNRESOLVED", "supersedes must name an exact report handle")
            try:
                binding, kind, versioned = handle[3:].split("/")
                record_id, version = versioned.rsplit("@", 1)
            except ValueError:
                raise _refuse(
                    "REF_UNRESOLVED", "supersedes must name an exact report handle"
                ) from None
            given = {
                "binding": binding,
                "kind": kind,
                "id": record_id,
                "version": version,
                "digest": given["digest"],
            }
        scoped = self.external(given, "report", "report supersedes")
        try:
            return Ref.model_validate(scoped).model_dump(mode="json")
        except ValidationError:
            raise _refuse(
                "REF_UNRESOLVED", "supersedes needs an exact report reference and digest"
            ) from None


class _Registration:
    def __init__(self, content: Mapping[str, Any], scope: _Scope, producer: Origin) -> None:
        self.scope = scope
        self.producer = producer.model_dump(mode="json")
        self.fragments = self._index(_records(content, "fragments"), "fragment")
        self.assertions = self._index(_records(content, "assertions"), "assertion")
        self.support_sets = _records(content, "supportSets")
        self.task = _object(content.get("task"), "task")
        self.report = _object(content.get("report"), "report")
        self.resolved: dict[str, dict[str, Any]] = {}
        self.resolving: set[str] = set()

    def _index(self, records: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for position, record in enumerate(records):
            record_id = self.scope.identify(record, kind, f"{kind}[{position}]")
            if record_id in indexed:
                raise _refuse("REGISTRATION_MALFORMED", f"duplicate {kind} id {record_id}")
            indexed[record_id] = record
        return indexed

    # ------------------------------------------------------------------ references

    def ref(
        self,
        value: Any,
        kind: str,
        where: str,
        local: Mapping[str, dict[str, Any]],
        complete: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        """The exact Ref ``value`` names: a local record's computed ref, or a complete external
        one. A digest/version/scope the model supplied must equal the computed one."""

        given: dict[str, Any] = {"id": value} if isinstance(value, str) else _object(value, where)
        if given.get("kind", kind) != kind:
            raise _refuse("REGISTRATION_MALFORMED", f"{where} must reference a {kind}")
        record_id = given.get("id")
        if not isinstance(record_id, str) or record_id not in local:
            return self.scope.external(given, kind, where)
        record = complete(record_id)
        computed = {
            "kind": kind,
            "id": record_id,
            "version": record["schemaVersion"],
            "digest": digest_canonical(record),
            "tenant": record["tenant"],
            "binding": record["binding"],
        }
        codes = {"digest": "REF_DIGEST_MISMATCH", "tenant": "RECORD_SCOPE_MISMATCH"}
        codes["binding"] = codes["tenant"]
        for field in _REF_FIELDS:
            if field in given and given[field] != computed[field]:
                raise _refuse(
                    codes.get(field, "REGISTRATION_MALFORMED"),
                    f"{where} {field} differs from the exact {kind} {record_id}",
                )
        return computed

    def fragment_ref(self, value: Any, where: str) -> dict[str, Any]:
        return self.ref(value, "fragment", where, self.fragments, self.fragments.__getitem__)

    def assertion_ref(self, value: Any, where: str) -> dict[str, Any]:
        return self.ref(value, "assertion", where, self.assertions, self.assertion)

    # ------------------------------------------------------------------ records

    def complete_fragments(self) -> None:
        for record_id, fragment in self.fragments.items():
            where = f"fragment {record_id}"
            for field in ("capture", "representation"):
                if field in fragment:
                    fragment[field] = self.scope.external(
                        fragment[field], "artifact", f"{where} {field}"
                    )
            selector = _object(fragment.get("selector"), f"{where} selector")
            if selector.get("kind") == "text_quote":
                quote = selector.get("value")
                if not isinstance(quote, str):
                    raise _refuse("REGISTRATION_MALFORMED", f"{where} quotes no text")
                exact = quote.encode("utf-8")
                for field, computed in (
                    ("selectedDigest", digest_bytes(exact)),
                    ("selectedSize", len(exact)),
                ):
                    if fragment.setdefault(field, computed) != computed:
                        raise _refuse(
                            "SELECTED_DIGEST_MISMATCH",
                            f"{where} {field} is not over its exact quoted bytes",
                        )
            elif not (
                isinstance(fragment.get("selectedDigest"), str)
                and isinstance(fragment.get("selectedSize"), int)
            ):
                raise _refuse(
                    "SELECTED_DIGEST_REQUIRED",
                    f"{where} selects bytes the host does not hold; give their digest and size",
                )

    def assertion(self, record_id: str) -> dict[str, Any]:
        """The complete assertion (producer and premises resolved), in dependency order."""

        if record_id in self.resolved:
            return self.resolved[record_id]
        if record_id in self.resolving:
            raise _refuse("REF_CYCLE", f"assertion {record_id} is its own (indirect) premise")
        self.resolving.add(record_id)
        record = self.assertions[record_id]
        if "producer" in record:
            raise _refuse(
                "PRODUCER_HOST_OWNED",
                f"assertion {record_id} names a producer; the host binds the origin",
            )
        record["producer"] = copy.deepcopy(self.producer)
        premises = record.get("premises", [])
        if not isinstance(premises, list):
            raise _refuse("REGISTRATION_MALFORMED", f"assertion {record_id} premises is no list")
        record["premises"] = [
            self.assertion_ref(item, f"assertion {record_id} premise[{index}]")
            for index, item in enumerate(premises)
        ]
        self.resolving.discard(record_id)
        self.resolved[record_id] = record
        return record

    def complete_support_sets(self) -> None:
        for position, support in enumerate(self.support_sets):
            record_id = self.scope.identify(support, "support_set", f"supportSet[{position}]")
            where = f"supportSet {record_id}"
            target = self.assertion_ref(support.get("assertion"), f"{where} assertion")
            support["assertion"] = target
            if target["id"] in self.assertions:
                qualifiers = self.assertions[target["id"]].get("qualifiers")
                computed = digest_canonical(qualifiers)
                if support.setdefault("qualifiersDigest", computed) != computed:
                    raise _refuse(
                        "REF_DIGEST_MISMATCH",
                        f"{where} qualifiersDigest is not over its assertion's qualifiers",
                    )
            elif not isinstance(support.get("qualifiersDigest"), str):
                raise _refuse("REF_UNRESOLVED", f"{where} needs the external qualifiersDigest")
            required = support.get("required", [])
            if not isinstance(required, list):
                raise _refuse("REGISTRATION_MALFORMED", f"{where} required is no list")
            for index, premise in enumerate(required):
                entry = _object(premise, f"{where} required[{index}]")
                entry["evidence"] = [
                    self.fragment_ref(item, f"{where} required[{index}] evidence")
                    for item in _list(entry.get("evidence", []), where)
                ]
                entry["derivedFrom"] = [
                    self.assertion_ref(item, f"{where} required[{index}] derivedFrom")
                    for item in _list(entry.get("derivedFrom", []), where)
                ]
            support["contrary"] = [
                self.fragment_ref(item, f"{where} contrary")
                for item in _list(support.get("contrary", []), where)
            ]

    def complete_task(self) -> None:
        self.scope.identify(self.task, "task", "task")
        for field, kind in (
            ("originalTask", "artifact"),
            ("rubric", "rubric"),
            ("policy", "policy"),
        ):
            if field in self.task:
                self.task[field] = self.scope.external(self.task[field], kind, f"task {field}")

    def complete_body(self) -> None:
        body = _object(self.report.get("structuredBody"), "report structuredBody")
        if body.setdefault("schemaVersion", STRUCTURED_BODY_SCHEMA) != STRUCTURED_BODY_SCHEMA:
            raise _refuse("REGISTRATION_MALFORMED", "the structured body is not v2")
        for section in _list(body.get("sections", []), "sections"):
            section = _object(section, "section")
            self.inlines(section.get("heading", []))
            for block in _list(section.get("blocks", []), "blocks"):
                block = _object(block, "block")
                if "inlines" in block:
                    self.inlines(block["inlines"])
                for item in _list(block.get("items", []), "items"):
                    self.inlines(item)
                for cell in _list(block.get("header", []), "header"):
                    self.inlines(cell)
                for row in _list(block.get("rows", []), "rows"):
                    for cell in _list(row, "row"):
                        self.inlines(cell)
                if block.get("caption") is not None:
                    self.inlines(block["caption"])

    def inlines(self, value: Any) -> None:
        for inline in _list(value, "inlines"):
            inline = _object(inline, "inline")
            if inline.get("type") == "claim":
                inline["assertion"] = self.assertion_ref(
                    inline.get("assertion"), f"claim {inline.get('occurrenceId')}"
                )
            elif inline.get("type") == "citation":
                inline["fragment"] = self.fragment_ref(
                    inline.get("fragment"), f"citation {inline.get('label')}"
                )

    def payload(self) -> dict[str, Any]:
        self.complete_fragments()
        for record_id in self.assertions:
            self.assertion(record_id)
        self.complete_support_sets()
        self.complete_task()
        self.complete_body()
        if self.report.get("supersedes") is not None:
            self.report["supersedes"] = self.scope.predecessor(self.report["supersedes"])
        return {
            "task": self.task,
            "fragments": list(self.fragments.values()),
            "assertions": list(self.assertions.values()),
            "supportSets": self.support_sets,
            "report": self.report,
        }


def _list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise _refuse("REGISTRATION_MALFORMED", f"{where} must be a list")
    return value


def canonical_registration(
    content: Mapping[str, Any], *, tenant: str, binding: str, producer: Origin
) -> dict[str, Any]:
    """The exact ``research-report/v2`` payload of the model's ``content`` (see module doc).

    Raises :class:`RegistrationRefused` (typed) for content that cannot be registered exactly.
    """

    unknown = sorted(set(content) - set(SECTIONS))
    if unknown:
        raise _refuse(
            "REGISTRATION_MALFORMED", "unknown registration fields: " + ", ".join(unknown)
        )
    try:
        canonical_json(dict(content))  # integers only, no lone surrogates: or no digest exists
    except (TypeError, ValueError) as error:
        raise _refuse(
            "REGISTRATION_MALFORMED", f"the content is not canonical JSON: {error}"
        ) from None
    working = copy.deepcopy(dict(content))
    return _Registration(working, _Scope(tenant, binding), producer).payload()


__all__ = [
    "ASSERTION_SCHEMA",
    "FRAGMENT_SCHEMA",
    "STRUCTURED_BODY_SCHEMA",
    "SUPPORT_SET_SCHEMA",
    "TASK_SCHEMA",
    "RegistrationRefused",
    "canonical_registration",
]
