"""Watcher conditions: the closed expression AST of ADR-0010 over observed facts (SPEC-04 §5.1).

A watcher's ``where`` and ``while`` are authored as short expressions such as
``event.conclusion == 'failure' and startswith(event.head_branch, run.branch_prefix)``. They
are parsed once, at validation, into :class:`WatcherCondition`, a closed typed tree with no
names, calls or attribute access beyond the grammar below; the Watcher Evaluator only ever
walks that tree. There is no ``eval`` and no free-form code, so a condition is replayable,
auditable and immune to injected text in the facts it reads.

Grammar (keywords are lower case; strings are single- or double-quoted)::

    condition  := or
    or         := and ("or" and)*
    and        := not ("and" not)*
    not        := "not" not | comparison
    comparison := value op value | call | "(" condition ")"
    op         := "==" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not in"
    call       := "exists(" path ")" | "startswith(" value "," value ")"
    value      := path | string | number | "true" | "false" | "null" | "[" literals "]"
    path       := ("event" | "run" | "unit" | "watcher") ("." name)*

Evaluation is total: a missing path reads ``null``; ordering compares two numbers or two
strings and is otherwise false; ``in`` needs a list on its right. Numbers compare exactly as
decimals (booleans are never numbers).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONDITION_ROOTS: Final = frozenset({"event", "run", "unit", "watcher"})
MAX_CONDITION_CHARS: Final = 2048
MAX_CONDITION_NODES: Final = 64
MAX_CONDITION_DEPTH: Final = 12
MAX_LIST_ITEMS: Final = 32
_NAME: Final = r"[A-Za-z_][A-Za-z0-9_]*"
PATH_PATTERN: Final = rf"^(?:event|run|unit|watcher)(?:\.{_NAME})*$"
_PATH = re.compile(PATH_PATTERN)
_NUMBER = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")

ConditionOp = Literal[
    "all",
    "any",
    "not",
    "eq",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
    "in",
    "not_in",
    "exists",
    "starts_with",
]
_LOGICAL: Final = frozenset({"all", "any", "not"})
_COMPARATORS: Final = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}


class ConditionSyntaxError(ValueError):
    """A condition text outside the closed grammar; ``position`` is the character offset."""

    def __init__(self, message: str, position: int) -> None:
        super().__init__(f"{message} (at character {position})")
        self.position = position


class ConditionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConditionValue(ConditionContract):
    """One operand: a fact path or a literal. Numbers keep their exact decimal text."""

    kind: Literal["path", "string", "number", "boolean", "null", "list"]
    text: str | None = Field(default=None, max_length=MAX_CONDITION_CHARS)
    flag: bool | None = None
    items: tuple[ConditionValue, ...] = Field(default=(), max_length=MAX_LIST_ITEMS)

    @model_validator(mode="after")
    def _shape(self) -> ConditionValue:
        texted = self.kind in {"path", "string", "number"}
        if texted != (self.text is not None):
            raise ValueError(f"a {self.kind} value {'needs' if texted else 'takes no'} text")
        if (self.kind == "boolean") != (self.flag is not None):
            raise ValueError("only a boolean value carries flag")
        if self.kind != "list" and self.items:
            raise ValueError("only a list value carries items")
        if self.kind == "path" and not _PATH.fullmatch(self.text or ""):
            raise ValueError(f"path {self.text!r} is not rooted at event, run, unit or watcher")
        if self.kind == "number" and not _NUMBER.fullmatch(self.text or ""):
            raise ValueError(f"number {self.text!r} is not a plain decimal")
        if any(item.kind in {"path", "list"} for item in self.items):
            raise ValueError("list items are literals")
        return self


class WatcherCondition(ConditionContract):
    """Closed typed condition AST (ADR-0010): logical nodes over comparisons of values."""

    op: ConditionOp
    operands: tuple[WatcherCondition, ...] = ()
    values: tuple[ConditionValue, ...] = ()

    @model_validator(mode="after")
    def _shape(self) -> WatcherCondition:
        if self.op in _LOGICAL:
            expected = 1 if self.op == "not" else None
            if self.values or not self.operands:
                raise ValueError(f"{self.op} combines conditions only")
            if expected is not None and len(self.operands) != expected:
                raise ValueError("not negates exactly one condition")
            if self.op != "not" and len(self.operands) < 2:
                raise ValueError(f"{self.op} combines at least two conditions")
        else:
            arity = 1 if self.op == "exists" else 2
            if self.operands or len(self.values) != arity:
                raise ValueError(f"{self.op} takes {arity} value(s)")
            if self.op == "exists" and self.values[0].kind != "path":
                raise ValueError("exists takes a path")
        return self

    def paths(self) -> tuple[str, ...]:
        """Every fact path the condition reads, in order of appearance."""

        found = [value.text for value in self.values if value.kind == "path" and value.text]
        for operand in self.operands:
            found.extend(operand.paths())
        return tuple(found)


# --- Parsing -------------------------------------------------------------------------------

_TOKEN = re.compile(
    r"""
    (?P<space>\s+)
  | (?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<number>-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?![A-Za-z0-9_]))
  | (?P<op>==|!=|<=|>=|<|>)
  | (?P<punct>[()\[\],])
  | (?P<word>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
    """,
    re.VERBOSE,
)
_KEYWORDS: Final = frozenset({"and", "or", "not", "in", "true", "false", "null"})
_CALLS: Final = frozenset({"exists", "startswith"})


def _tokens(text: str) -> list[tuple[str, str, int]]:
    position = 0
    tokens: list[tuple[str, str, int]] = []
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise ConditionSyntaxError(f"unexpected character {text[position]!r}", position)
        kind = match.lastgroup
        assert kind is not None
        if kind != "space":
            tokens.append((kind, match.group(), position))
        position = match.end()
    tokens.append(("end", "", len(text)))
    return tokens


def _unquote(token: str, position: int) -> str:
    body = token[1:-1]
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\":
            index += 1
            escaped = body[index]
            if escaped not in {"\\", "'", '"'}:
                raise ConditionSyntaxError(f"unsupported escape \\{escaped}", position + index)
            out.append(escaped)
        else:
            out.append(char)
        index += 1
    return "".join(out)


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokens(text)
        self.index = 0
        self.nodes = 0

    # -- token helpers ------------------------------------------------------------------

    def peek(self, offset: int = 0) -> tuple[str, str, int]:
        return self.tokens[min(self.index + offset, len(self.tokens) - 1)]

    def take(self) -> tuple[str, str, int]:
        token = self.peek()
        self.index += 1
        return token

    def is_word(self, word: str, offset: int = 0) -> bool:
        kind, value, _ = self.peek(offset)
        return kind == "word" and value == word

    def expect(self, kind: str, value: str) -> None:
        got_kind, got, position = self.take()
        if (got_kind, got) != (kind, value):
            raise ConditionSyntaxError(f"expected {value!r}, found {got or 'the end'!r}", position)

    def node(self, depth: int, **fields: Any) -> WatcherCondition:
        self.nodes += 1
        if self.nodes > MAX_CONDITION_NODES:
            raise ConditionSyntaxError(
                f"a condition has at most {MAX_CONDITION_NODES} nodes", self.peek()[2]
            )
        self.within_depth(depth)
        return WatcherCondition(**fields)

    def within_depth(self, depth: int) -> None:
        if depth > MAX_CONDITION_DEPTH:
            raise ConditionSyntaxError(
                f"a condition nests at most {MAX_CONDITION_DEPTH} levels", self.peek()[2]
            )

    # -- grammar ------------------------------------------------------------------------

    def parse(self) -> WatcherCondition:
        condition = self.disjunction(1)
        kind, value, position = self.peek()
        if kind != "end":
            raise ConditionSyntaxError(f"unexpected {value!r}", position)
        return condition

    def disjunction(self, depth: int) -> WatcherCondition:
        operands = [self.conjunction(depth + 1)]
        while self.is_word("or"):
            self.take()
            operands.append(self.conjunction(depth + 1))
        if len(operands) == 1:
            return operands[0]
        return self.node(depth, op="any", operands=tuple(operands))

    def conjunction(self, depth: int) -> WatcherCondition:
        operands = [self.negation(depth + 1)]
        while self.is_word("and"):
            self.take()
            operands.append(self.negation(depth + 1))
        if len(operands) == 1:
            return operands[0]
        return self.node(depth, op="all", operands=tuple(operands))

    def negation(self, depth: int) -> WatcherCondition:
        # Every recursion (`not`, parentheses) passes here: refuse depth before descending, so
        # a deeply nested text is a syntax error, never a RecursionError.
        self.within_depth(depth)
        if self.is_word("not"):
            self.take()
            return self.node(depth, op="not", operands=(self.negation(depth + 1),))
        return self.comparison(depth)

    def comparison(self, depth: int) -> WatcherCondition:
        kind, value, position = self.peek()
        if kind == "punct" and value == "(":
            self.take()
            inner = self.disjunction(depth + 1)
            self.expect("punct", ")")
            return inner
        if kind == "word" and value in _CALLS and self.peek(1)[1] == "(":
            return self.call(depth)
        left = self.value()
        op_kind, op_value, op_position = self.peek()
        if op_kind == "op":
            self.take()
            op = _COMPARATORS[op_value]
        elif self.is_word("in"):
            self.take()
            op = "in"
        elif self.is_word("not") and self.is_word("in", 1):
            self.take()
            self.take()
            op = "not_in"
        else:
            raise ConditionSyntaxError(
                "a condition compares two values (==, !=, <, <=, >, >=, in, not in)",
                op_position if op_kind != "end" else position,
            )
        right = self.value()
        return self.node(depth, op=op, values=(left, right))

    def call(self, depth: int) -> WatcherCondition:
        _, name, position = self.take()
        self.expect("punct", "(")
        if name == "exists":
            path = self.value()
            if path.kind != "path":
                raise ConditionSyntaxError("exists takes a path", position)
            self.expect("punct", ")")
            return self.node(depth, op="exists", values=(path,))
        subject = self.value()
        self.expect("punct", ",")
        prefix = self.value()
        self.expect("punct", ")")
        return self.node(depth, op="starts_with", values=(subject, prefix))

    def value(self) -> ConditionValue:
        kind, value, position = self.take()
        if kind == "string":
            return ConditionValue(kind="string", text=_unquote(value, position))
        if kind == "number":
            return ConditionValue(kind="number", text=value)
        if kind == "punct" and value == "[":
            return self.list_value(position)
        if kind == "word":
            if value in {"true", "false"}:
                return ConditionValue(kind="boolean", flag=value == "true")
            if value == "null":
                return ConditionValue(kind="null")
            if value in _KEYWORDS or value in _CALLS:
                raise ConditionSyntaxError(f"{value!r} is not a value", position)
            if not _PATH.fullmatch(value):
                raise ConditionSyntaxError(
                    f"{value!r} is not a fact path; paths start with event., run., unit. "
                    "or watcher.",
                    position,
                )
            return ConditionValue(kind="path", text=value)
        raise ConditionSyntaxError(f"expected a value, found {value or 'the end'!r}", position)

    def list_value(self, position: int) -> ConditionValue:
        items: list[ConditionValue] = []
        if self.peek()[1] != "]":
            while True:
                item = self.value()
                if item.kind in {"path", "list"}:
                    raise ConditionSyntaxError("list items are literals", position)
                items.append(item)
                if self.peek()[1] != ",":
                    break
                self.take()
        self.expect("punct", "]")
        if len(items) > MAX_LIST_ITEMS:
            raise ConditionSyntaxError(f"a list holds at most {MAX_LIST_ITEMS} items", position)
        return ConditionValue(kind="list", items=tuple(items))


def parse_condition(text: str) -> WatcherCondition:
    """Parse one authored condition into the closed AST, or raise ConditionSyntaxError."""

    if not text.strip():
        raise ConditionSyntaxError("a condition is not empty", 0)
    if len(text) > MAX_CONDITION_CHARS:
        raise ConditionSyntaxError(
            f"a condition is at most {MAX_CONDITION_CHARS} characters", MAX_CONDITION_CHARS
        )
    return _Parser(text).parse()


# --- Evaluation ----------------------------------------------------------------------------

_MISSING: Final = object()


def read_path(context: Mapping[str, Any], path: str) -> Any:
    """The fact at a dotted path, or None when any segment is absent or not a mapping."""

    current: Any = context
    for segment in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(segment, _MISSING)
        if current is _MISSING:
            return None
    return current


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | Decimal):
        return Decimal(value)
    if isinstance(value, float):
        try:
            return Decimal(repr(value))
        except InvalidOperation:  # pragma: no cover - repr of a finite float is decimal
            return None
    return None


def _resolve(value: ConditionValue, context: Mapping[str, Any]) -> Any:
    if value.kind == "path":
        return read_path(context, value.text or "")
    if value.kind == "string":
        return value.text
    if value.kind == "number":
        return Decimal(value.text or "0")
    if value.kind == "boolean":
        return value.flag
    if value.kind == "null":
        return None
    return tuple(_resolve(item, context) for item in value.items)


def _equal(left: Any, right: Any) -> bool:
    left_number, right_number = _number(left), _number(right)
    if left_number is not None or right_number is not None:
        return left_number is not None and left_number == right_number
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if left is None or right is None:
        return left is right
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return False


def _order(op: str, left: Any, right: Any) -> bool:
    left_number, right_number = _number(left), _number(right)
    if left_number is not None and right_number is not None:
        return _compare(op, left_number, right_number)
    if isinstance(left, str) and isinstance(right, str):
        return _compare(op, left, right)
    return False


def _compare[T: (Decimal, str)](op: str, a: T, b: T) -> bool:
    return {"lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[op]


def _members(value: Any) -> Sequence[Any] | None:
    if isinstance(value, tuple | list):
        return value
    return None


def evaluate_condition(condition: WatcherCondition, context: Mapping[str, Any]) -> bool:
    """Deterministic, total evaluation of a condition over ``{event, run, unit, watcher}``."""

    op = condition.op
    if op == "all":
        return all(evaluate_condition(item, context) for item in condition.operands)
    if op == "any":
        return any(evaluate_condition(item, context) for item in condition.operands)
    if op == "not":
        return not evaluate_condition(condition.operands[0], context)
    values = [_resolve(value, context) for value in condition.values]
    if op == "exists":
        return values[0] is not None
    left, right = values
    if op == "eq":
        return _equal(left, right)
    if op == "ne":
        return not _equal(left, right)
    if op in {"lt", "le", "gt", "ge"}:
        return _order(op, left, right)
    if op == "starts_with":
        return isinstance(left, str) and isinstance(right, str) and left.startswith(right)
    members = _members(right)
    if members is None:
        return False
    found = any(_equal(left, item) for item in members)
    return found if op == "in" else not found


__all__ = [
    "CONDITION_ROOTS",
    "MAX_CONDITION_CHARS",
    "PATH_PATTERN",
    "ConditionSyntaxError",
    "ConditionValue",
    "WatcherCondition",
    "evaluate_condition",
    "parse_condition",
    "read_path",
]
