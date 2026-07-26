"""Shared AST-walking helpers for variable analysis.

These functions walk the AST and collect various sets of variables
(definitions, reads, inputs, etc.) used by the analysis modules.

All names are private (leading underscore) — public APIs live in the
individual analysis modules.
"""

from __future__ import annotations

from ..ast_nodes import (
    ArrayAccess,
    Assignment,
    BinaryOp,
    BitIndex,
    BitRange,
    CaseOf,
    DestructureAssignment,
    Expression,
    FieldAccess,
    ForLoop,
    FunctionCall,
    Identifier,
    IfExpr,
    IfThen,
    InExpr,
    IntegerLiteral,
    PatternMatch,
    Program,
    RegisterAccess,
    Statement,
    StatementCall,
    TupleLiteral,
    UnaryOp,
    WhenClause,
)


def _render_register(reg: RegisterAccess) -> str:
    """Render a register access to a readable name string."""
    if isinstance(reg.index, Identifier):
        return f"R[{reg.index.name}]"
    if isinstance(reg.index, IntegerLiteral):
        return f"R[{reg.index.value}]"
    return "R[...]"


def _collect_definitions(program: Program) -> list[str]:
    """Walk the AST and collect names of all defined variables."""
    seen: set[str] = set()
    result: list[str] = []

    def visit_stmts(stmts: list[Statement]) -> None:
        for stmt in stmts:
            if isinstance(stmt, Assignment):
                if isinstance(stmt.target, str):
                    name = stmt.target
                elif isinstance(stmt.target, RegisterAccess):
                    name = _render_register(stmt.target)
                elif isinstance(stmt.target, FieldAccess):
                    name = f"{stmt.target.base}.{stmt.target.field}"
                elif isinstance(stmt.target, BitIndex):
                    name = stmt.target.name
                else:
                    continue
                if name not in seen:
                    seen.add(name)
                    result.append(name)
            elif isinstance(stmt, DestructureAssignment):
                for target in stmt.targets:
                    if target is None:
                        continue
                    if target not in seen:
                        seen.add(target)
                        result.append(target)
            elif isinstance(stmt, ForLoop):
                if stmt.variable not in seen:
                    seen.add(stmt.variable)
                    result.append(stmt.variable)
                visit_stmts(stmt.body)
            elif isinstance(stmt, IfThen):
                visit_stmts(stmt.then_body)
                if stmt.else_body:
                    visit_stmts(stmt.else_body)
            elif isinstance(stmt, CaseOf):
                visit_stmts([s for clause in stmt.clauses for s in clause.body])
                if stmt.else_body:
                    visit_stmts(stmt.else_body)
            elif isinstance(stmt, WhenClause):
                pass

    visit_stmts(program.statements)
    return result


def _collect_reads_expr(expr: Expression, reads: set[str]) -> None:
    """Collect all identifier references from an expression."""
    if isinstance(expr, Identifier):
        reads.add(expr.name)
    elif isinstance(expr, FieldAccess):
        reads.add(f"{expr.base}.{expr.field}")
    elif isinstance(expr, RegisterAccess):
        _collect_reads_expr(expr.index, reads)
    elif isinstance(expr, FunctionCall):
        for arg in expr.args:
            _collect_reads_expr(arg, reads)
    elif isinstance(expr, ArrayAccess):
        for arg in expr.args:
            _collect_reads_expr(arg, reads)
    elif isinstance(expr, BinaryOp):
        _collect_reads_expr(expr.left, reads)
        _collect_reads_expr(expr.right, reads)
    elif isinstance(expr, UnaryOp):
        _collect_reads_expr(expr.operand, reads)
    elif isinstance(expr, InExpr):
        _collect_reads_expr(expr.left, reads)
        for elem in expr.set.elements:
            _collect_reads_expr(elem, reads)
    elif isinstance(expr, TupleLiteral):
        for elem in expr.elements:
            _collect_reads_expr(elem, reads)
    elif isinstance(expr, BitIndex):
        reads.add(expr.name)
        _collect_reads_expr(expr.index, reads)
    elif isinstance(expr, BitRange):
        reads.add(expr.name)
        _collect_reads_expr(expr.high, reads)
        _collect_reads_expr(expr.low, reads)
    elif isinstance(expr, IfExpr):
        _collect_reads_expr(expr.condition, reads)
        _collect_reads_expr(expr.then_value, reads)
        _collect_reads_expr(expr.else_value, reads)
    elif isinstance(expr, PatternMatch):
        _collect_reads_expr(expr.expr, reads)


def _collect_reads(program: Program) -> set[str]:
    """Walk the AST and collect all variable references (reads)."""
    reads: set[str] = set()

    def visit_stmts(stmts: list[Statement]) -> None:
        for stmt in stmts:
            if isinstance(stmt, Assignment):
                if isinstance(stmt.target, RegisterAccess):
                    _collect_reads_expr(stmt.target.index, reads)
                elif isinstance(stmt.target, BitIndex):
                    reads.add(stmt.target.name)
                    _collect_reads_expr(stmt.target.index, reads)
                _collect_reads_expr(stmt.value, reads)
            elif isinstance(stmt, DestructureAssignment):
                _collect_reads_expr(stmt.value, reads)
            elif isinstance(stmt, StatementCall):
                for arg in stmt.args:
                    _collect_reads_expr(arg, reads)
            elif isinstance(stmt, ForLoop):
                _collect_reads_expr(stmt.start, reads)
                _collect_reads_expr(stmt.end, reads)
                visit_stmts(stmt.body)
            elif isinstance(stmt, IfThen):
                _collect_reads_expr(stmt.condition, reads)
                visit_stmts(stmt.then_body)
                if stmt.else_body:
                    visit_stmts(stmt.else_body)
            elif isinstance(stmt, CaseOf):
                _collect_reads_expr(stmt.expr, reads)
                visit_stmts([s for clause in stmt.clauses for s in clause.body])
                if stmt.else_body:
                    visit_stmts(stmt.else_body)
            elif isinstance(stmt, WhenClause):
                _collect_reads_expr(stmt.pattern, reads)
                visit_stmts(stmt.body)

    visit_stmts(program.statements)
    return reads


def _collect_input_variables(program: Program) -> list[str]:
    """Collect variables that are read but never defined in the code."""
    defined = set(_collect_definitions(program))
    reads = _collect_reads(program)
    return sorted(reads - defined)


def _collect_assignment_rhs_reads(program: Program) -> set[str]:
    """Collect variables referenced on the right-hand side of assignments."""
    result: set[str] = set()

    def visit_stmts(stmts: list[Statement]) -> None:
        for stmt in stmts:
            if isinstance(stmt, Assignment):
                _collect_reads_expr(stmt.value, result)
            elif isinstance(stmt, DestructureAssignment):
                _collect_reads_expr(stmt.value, result)
            elif isinstance(stmt, IfThen):
                visit_stmts(stmt.then_body)
                if stmt.else_body:
                    visit_stmts(stmt.else_body)
            elif isinstance(stmt, ForLoop):
                visit_stmts(stmt.body)
            elif isinstance(stmt, CaseOf):
                for clause in stmt.clauses:
                    visit_stmts(clause.body)
                if stmt.else_body:
                    visit_stmts(stmt.else_body)

    visit_stmts(program.statements)
    return result


def _collect_unassigned_input_variables(program: Program) -> list[str]:
    """Collect input variables that never appear on the RHS of any assignment."""
    input_vars = set(_collect_input_variables(program))
    rhs_reads = _collect_assignment_rhs_reads(program)
    return sorted(input_vars - rhs_reads)
