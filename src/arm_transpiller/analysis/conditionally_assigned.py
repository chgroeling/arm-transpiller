"""Conditionally-assigned-variable analysis for ARM pseudocode.

Reports which output variables of a ``decode`` block are **not** assigned on
every path through the block — useful for consumers that must pre-initialise
them before the transpiled code runs.

``extract_conditionally_assigned`` is the high-level API,
matching the existing ``extract_*`` family.
"""

from __future__ import annotations

from typing import Mapping

from ..ast_nodes import (
    Assignment,
    BitStringLiteral,
    CaseOf,
    DestructureAssignment,
    Expression,
    ForLoop,
    HexLiteral,
    IfThen,
    IntegerLiteral,
    Program,
    Range,
    SeeStmt,
    Statement,
    Undefined,
    Unpredictable,
    WhenClause,
)
from ..known_types import ArmType, ScalarType
from ..type_inference import TypeInferencer
from ._collect import _collect_definitions


def _targets(stmt: Assignment | DestructureAssignment) -> set[str]:
    """Return the plain-string variable names *stmt* binds."""
    if isinstance(stmt, Assignment):
        if isinstance(stmt.target, str):
            return {stmt.target}
        return set()
    return {t for t in stmt.targets if t is not None}


def _exhaustive(
    clauses: list[WhenClause],
    selector_type: ArmType | None,
) -> bool:
    """Decide whether *clauses* cover every value of the case selector.

    Uses *selector_type* (inferred from the selector expression) when available
    to make an exact decision; falls back to a heuristic on literal shapes
    otherwise.
    """
    if not clauses:
        return False

    patterns = [c.pattern for c in clauses]

    if selector_type is not None and isinstance(selector_type, ScalarType):
        width = selector_type.width
        domain_size = 1 << width
        values = _pattern_values(patterns)
        if values is not None and len(values) == domain_size:
            return True

    if all(isinstance(p, BitStringLiteral) for p in patterns):
        bsl_patterns: list[BitStringLiteral] = [
            p for p in patterns if isinstance(p, BitStringLiteral)
        ]
        vals = {p.value for p in bsl_patterns}
        widths = {len(p.value) for p in bsl_patterns}
        if len(widths) == 1:
            return len(vals) == len(patterns) == (1 << widths.pop())

    return False


def _pattern_values(patterns: list[Expression]) -> set[int] | None:
    """Return the set of integer values covered by *patterns*.

    Returns ``None`` when any pattern cannot be reduced to a concrete value.
    """
    values: set[int] = set()
    for p in patterns:
        match p:
            case BitStringLiteral():
                values.add(int(p.value, 2))
            case IntegerLiteral():
                values.add(p.value)
            case HexLiteral():
                values.add(p.value)
            case Range():
                for v in range(p.start, p.end + 1):
                    values.add(v)
            case _:
                return None
    return values


def _merge_two(
    a: set[str] | None,
    b: set[str] | None,
) -> set[str] | None:
    """Intersect two branch results; ``None`` is identity (universal set)."""
    if a is None and b is None:
        return None
    if a is None:
        return b
    if b is None:
        return a
    return a & b


def _merge_all(results: list[set[str] | None]) -> set[str] | None:
    """Intersect multiple branch results, skipping ``None`` entries."""
    non_terminal = [r for r in results if r is not None]
    if not non_terminal:
        return None
    return set.intersection(*non_terminal)


def _body_definitely_assigned(
    body: list[Statement],
    inferencer: TypeInferencer,
) -> set[str] | None:
    """Build the set of names *body* assigns on every execution path.

    Returns ``None`` when the body contains a terminal statement
    (UNPREDICTABLE / UNDEFINED / SEE) and no other statement beyond it
    would affect the result.
    """
    assigned: set[str] = set()
    for stmt in body:
        match stmt:
            case Assignment():
                assigned.update(_targets(stmt))
            case DestructureAssignment():
                assigned.update(_targets(stmt))
            case IfThen() if stmt.else_body is not None:
                then_res = _body_definitely_assigned(stmt.then_body, inferencer)
                else_res = _body_definitely_assigned(stmt.else_body, inferencer)
                merged = _merge_two(then_res, else_res)
                if merged is not None:
                    assigned |= merged
            case IfThen():
                pass
            case CaseOf():
                results = [
                    _body_definitely_assigned(clause.body, inferencer)
                    for clause in stmt.clauses
                ]
                if stmt.else_body is not None:
                    results.append(
                        _body_definitely_assigned(stmt.else_body, inferencer)
                    )
                else:
                    sel_type = _selector_type(stmt.expr, inferencer)
                    if not _exhaustive(stmt.clauses, sel_type):
                        results = []
                if results:
                    merged = _merge_all(results)
                    if merged is not None:
                        assigned |= merged
            case ForLoop():  # pragma: no cover
                pass
            case Unpredictable() | Undefined() | SeeStmt():
                return None
            case _:
                pass

    return assigned


def _selector_type(
    expr: Expression,
    inferencer: TypeInferencer,
) -> ArmType | None:
    """Return the inferred type of a case selector, or ``None`` on failure."""
    try:
        return inferencer.try_type_of(expr)
    except Exception:  # noqa: BLE001
        return None


def _is_local_variable(name: str) -> bool:
    """Return True when *name* looks like a plain local (no brackets, no dots)."""
    return "[" not in name and "." not in name


def _conditionally_assigned_vars(
    program: Program,
    input_types: Mapping[str, str | ArmType] | None = None,
) -> list[str]:
    """Return the output variables of *program* not assigned on every path.

    Args:
        program: A parsed pseudocode program.
        input_types: Types for input variables, overriding the known table.

    Returns:
        Variable names in declaration / first-assignment order.
    """
    inferencer = TypeInferencer(input_types)
    inferencer.infer(program)

    definitely = _body_definitely_assigned(program.statements, inferencer)
    defined = _collect_definitions(program)

    da_set: set[str] = definitely if definitely is not None else set()
    return [name for name in defined if _is_local_variable(name) and name not in da_set]


def extract_conditionally_assigned(
    program: Program,
    input_types: Mapping[str, str | ArmType] | None = None,
) -> list[str]:
    """Return a list of variable names that are **not** assigned on every
    execution path through the block.

    The result is always a subset of :func:`extract_output_variables`.
    Callers that pre-initialise generated-instruction members before a decode
    block runs can use this list to determine which members to zero-fill.

    Args:
        program: A parsed pseudocode Program AST.
        input_types: Types for input variables, overriding the known table.

    Returns:
        A list of variable name strings.
    """
    return _conditionally_assigned_vars(program, input_types)
