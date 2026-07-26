"""Subsumed-variable analysis for ARM pseudocode.

Reports which output variables of a ``decode`` block are spliced verbatim
(through bit concatenation and width-preserving extension calls) into
**another** output variable and read nowhere else.  Such a variable is a
bit-slice of that other output and can be dropped losslessly.

``extract_subsumed_variables`` is the public API.
"""

from __future__ import annotations

from typing import Callable, Mapping

from ..ast_nodes import (
    ArrayAccess,
    Assignment,
    BinaryOp,
    BitIndex,
    BitLiteral,
    BitRange,
    BitStringLiteral,
    CaseOf,
    DestructureAssignment,
    Expression,
    FieldAccess,
    ForLoop,
    FunctionCall,
    HexLiteral,
    Identifier,
    IfExpr,
    IfThen,
    InExpr,
    IntegerLiteral,
    PatternMatch,
    Program,
    RegisterAccess,
    SetLiteral,
    Statement,
    StatementCall,
    TupleLiteral,
    UnaryOp,
)
from ..known_types import ArmType, UnknownTypeError, width_of
from ..type_inference import TypeInferencer
from ._collect import _collect_definitions

# Functions whose first argument propagates concat leaves verbatim.
_PROPAGATING_FUNCTIONS = frozenset({"SignExtend", "ZeroExtend"})


def _is_output(name: str, output_set: frozenset[str]) -> bool:
    return name in output_set


def _mark_concat_leaves(
    expr: Expression,
    target_name: str,
    check_id: Callable[[str, bool, str | None], None],
) -> None:
    """Mark ``Identifier`` leaves of a concat chain as propagating to *target_name*."""
    if isinstance(expr, BinaryOp) and expr.op == ":":
        _mark_concat_leaves(expr.left, target_name, check_id)
        _mark_concat_leaves(expr.right, target_name, check_id)
    elif isinstance(expr, Identifier):
        if expr.name != target_name:
            check_id(expr.name, True, target_name)
    # Literal leaves — nothing to track.


def _walk_expr_generic(
    expr: Expression,
    check_id: Callable[[str, bool, str | None], None],
) -> None:
    """Visit every identifier in *expr*, marking each read as *consuming*."""
    if isinstance(expr, Identifier):
        check_id(expr.name, False, None)
    elif isinstance(
        expr,
        (
            IntegerLiteral,
            HexLiteral,
            BitLiteral,
            BitStringLiteral,
            str,
        ),
    ):
        return
    elif isinstance(expr, BinaryOp):
        _walk_expr_generic(expr.left, check_id)
        _walk_expr_generic(expr.right, check_id)
    elif isinstance(expr, UnaryOp):
        _walk_expr_generic(expr.operand, check_id)
    elif isinstance(expr, FunctionCall):
        for arg in expr.args:
            _walk_expr_generic(arg, check_id)
    elif isinstance(expr, IfExpr):
        _walk_expr_generic(expr.condition, check_id)
        _walk_expr_generic(expr.then_value, check_id)
        _walk_expr_generic(expr.else_value, check_id)
    elif isinstance(expr, InExpr):
        _walk_expr_generic(expr.left, check_id)
        for elem in expr.set.elements:
            _walk_expr_generic(elem, check_id)
    elif isinstance(expr, PatternMatch):
        _walk_expr_generic(expr.expr, check_id)
    elif isinstance(expr, SetLiteral):
        for elem in expr.elements:
            _walk_expr_generic(elem, check_id)
    elif isinstance(expr, TupleLiteral):
        for elem in expr.elements:
            _walk_expr_generic(elem, check_id)
    elif isinstance(expr, ArrayAccess):
        for arg in expr.args:
            _walk_expr_generic(arg, check_id)
    elif isinstance(expr, RegisterAccess):
        _walk_expr_generic(expr.index, check_id)
    elif isinstance(expr, BitIndex):
        check_id(expr.name, False, None)
        _walk_expr_generic(expr.index, check_id)
    elif isinstance(expr, BitRange):
        check_id(expr.name, False, None)
        _walk_expr_generic(expr.high, check_id)
        _walk_expr_generic(expr.low, check_id)
    elif isinstance(expr, FieldAccess):
        pass


def _walk_stmt(
    stmt: Statement,
    check_id: Callable[[str, bool, str | None], None],
    inferencer: TypeInferencer,
) -> None:
    """Track propagating reads on assignments, consuming reads elsewhere."""
    match stmt:
        case Assignment():
            if isinstance(stmt.target, str):
                _walk_assignment_rhs(stmt.value, stmt.target, check_id, inferencer)
            else:
                _walk_expr_generic(stmt.value, check_id)
        case DestructureAssignment():
            _walk_expr_generic(stmt.value, check_id)
        case IfThen():
            _walk_expr_generic(stmt.condition, check_id)
            _walk_stmts(stmt.then_body, check_id, inferencer)
            if stmt.else_body:
                _walk_stmts(stmt.else_body, check_id, inferencer)
        case ForLoop():
            _walk_expr_generic(stmt.start, check_id)
            _walk_expr_generic(stmt.end, check_id)
            _walk_stmts(stmt.body, check_id, inferencer)
        case StatementCall():
            for arg in stmt.args:
                _walk_expr_generic(arg, check_id)
        case CaseOf():
            _walk_expr_generic(stmt.expr, check_id)
            for clause in stmt.clauses:
                _walk_expr_generic(clause.pattern, check_id)
                _walk_stmts(clause.body, check_id, inferencer)
            if stmt.else_body:
                _walk_stmts(stmt.else_body, check_id, inferencer)
        case _:
            # Unpredictable, Undefined, SeeStmt, Comment, WhenClause —
            # no expressions to walk.
            pass


def _walk_stmts(
    stmts: list[Statement],
    check_id: Callable[[str, bool, str | None], None],
    inferencer: TypeInferencer,
) -> None:
    for s in stmts:
        _walk_stmt(s, check_id, inferencer)


def _walk_assignment_rhs(
    expr: Expression,
    target_name: str,
    check_id: Callable[[str, bool, str | None], None],
    inferencer: TypeInferencer,
) -> None:
    """Walk the RHS of an assignment.

    If the RHS is a concat chain (possibly wrapped in width-preserving
    SignExtend / ZeroExtend), mark all concat-leaf ``Identifier`` reads
    as *propagating* to *target_name*.  Otherwise, walk generically
    (all reads consuming).
    """
    effective = expr
    if isinstance(effective, FunctionCall) and effective.name in _PROPAGATING_FUNCTIONS:
        if len(effective.args) >= 2 and isinstance(effective.args[1], IntegerLiteral):
            inner = effective.args[0]
            try:
                inner_width = inferencer.width_of_expr(inner)
            except UnknownTypeError:
                _walk_expr_generic(effective, check_id)
                return
            if effective.args[1].value < inner_width:
                _walk_expr_generic(effective, check_id)
                return
            effective = inner
        else:
            _walk_expr_generic(effective, check_id)
            return

    if isinstance(effective, BinaryOp) and effective.op == ":":
        _mark_concat_leaves(effective, target_name, check_id)
    else:
        _walk_expr_generic(effective, check_id)


def _subsumed_variables(
    program: Program,
    input_types: Mapping[str, str | ArmType] | None = None,
) -> list[str]:
    """Return the output variables of *program* that are subsumed by another output.

    Args:
        program: A parsed pseudocode program.
        input_types: Types for input variables, overriding the known table.

    Returns:
        Variable names in declaration / first-assignment order.
    """
    inferencer = TypeInferencer(input_types)
    inferencer.infer(program)

    defined = _collect_definitions(program)
    output_set = frozenset(defined)

    # Per-variable bookkeeping.
    consuming: set[str] = set()
    propagating: dict[str, set[str]] = {}  # leaf → target names
    has_any_read: set[str] = set()

    def _check_id(name: str, is_prop: bool, target: str | None) -> None:
        if name not in output_set:
            return
        has_any_read.add(name)
        if is_prop and target is not None:
            propagating.setdefault(name, set()).add(target)
        else:
            consuming.add(name)

    _walk_stmts(program.statements, _check_id, inferencer)

    # Fixed-point resolution.
    # Batch-discard per iteration so that chains (a → b → c) resolve
    # correctly: if both a and b are subsumable in the same round, both
    # are removed rather than b being removed first and a then failing
    # its targets-all-in-kept check.
    kept = set(defined)
    changed = True
    while changed:
        changed = False
        subsumed_this_round: list[str] = []
        for name in kept:
            if name in consuming or name not in has_any_read:
                continue
            targets = propagating.get(name, set())
            if (
                targets
                and all(t in kept for t in targets)
                and target_width_check(name, targets, inferencer)
            ):
                subsumed_this_round.append(name)
        if subsumed_this_round:
            kept.difference_update(subsumed_this_round)
            changed = True

    return [name for name in defined if name not in kept]


def target_width_check(
    name: str,
    targets: set[str],
    inferencer: TypeInferencer,
) -> bool:
    """Verify that *name* is not truncated in any target chain.

    If *name* has type ``bitsW`` and a target has type ``bitsT`` with
    ``T < W``, the value cannot be fully recovered from the target.
    """
    try:
        leaf_type = inferencer.lookup(name)
    except Exception:  # noqa: BLE001
        return False
    leaf_width = width_of(leaf_type, name)
    for target in targets:
        try:
            t_type = inferencer.lookup(target)
        except Exception:  # noqa: BLE001
            return False
        t_width = width_of(t_type, target)
        if t_width < leaf_width:
            return False
    return True


def extract_subsumed_variables(
    program: Program,
    input_types: Mapping[str, str | ArmType] | None = None,
) -> list[str]:
    """Return a list of output variable names that are subsumed by another
    retained output variable.

    A variable is **subsumed** when it is spliced verbatim (through the ``:``
    concatenation operator and width-preserving ``SignExtend`` / ``ZeroExtend``
    calls) into another output and never read in any other position.  Such a
    variable is a bit-slice of the retaining variable and can be omitted from
    a generated instruction struct without losing information.

    Args:
        program: A parsed pseudocode Program AST.
        input_types: Types for input variables, overriding the known table.

    Returns:
        A list of variable name strings.
    """
    return _subsumed_variables(program, input_types)
