"""Side-effect detection for ARM pseudocode.

Detects UNPREDICTABLE, UNDEFINED, and SEE side-effects in pseudocode,
including those from runtime-function calls (e.g. ``ThumbExpandImm``).

``extract_side_effects`` is the high-level API.
"""

from __future__ import annotations

from ..ast_nodes import (
    Assignment,
    BinaryOp,
    CaseOf,
    DestructureAssignment,
    Expression,
    ForLoop,
    FunctionCall,
    IfExpr,
    IfThen,
    InExpr,
    PatternMatch,
    Program,
    SeeStmt,
    Statement,
    StatementCall,
    TupleLiteral,
    UnaryOp,
    Undefined,
    Unpredictable,
    WhenClause,
)

_RUNTIME_FN_SIDEEFFECTS: dict[str, list[str]] = {
    "ThumbExpandImm": ["unpredictable"],
    "ThumbExpandImm_C": ["unpredictable"],
}


def _collect_sideeffects(program: Program) -> dict[str, bool]:
    """Walk the AST and detect side-effect statements and runtime-function calls."""
    result: dict[str, bool] = {
        "unpredictable": False,
        "undefined": False,
        "see": False,
    }

    def check_call(name: str) -> None:
        for effect in _RUNTIME_FN_SIDEEFFECTS.get(name, []):
            result[effect] = True

    def visit_expr(expr: Expression) -> None:
        if isinstance(expr, FunctionCall):
            check_call(expr.name)
            for arg in expr.args:
                visit_expr(arg)
        elif isinstance(expr, BinaryOp):
            visit_expr(expr.left)
            visit_expr(expr.right)
        elif isinstance(expr, UnaryOp):
            visit_expr(expr.operand)
        elif isinstance(expr, InExpr):
            visit_expr(expr.left)
            for elem in expr.set.elements:
                visit_expr(elem)
        elif isinstance(expr, TupleLiteral):
            for elem in expr.elements:
                visit_expr(elem)
        elif isinstance(expr, IfExpr):
            visit_expr(expr.condition)
            visit_expr(expr.then_value)
            visit_expr(expr.else_value)
        elif isinstance(expr, PatternMatch):
            visit_expr(expr.expr)

    def visit_stmts(stmts: list[Statement]) -> None:
        for stmt in stmts:
            if isinstance(stmt, Unpredictable):
                result["unpredictable"] = True
            elif isinstance(stmt, Undefined):
                result["undefined"] = True
            elif isinstance(stmt, SeeStmt):
                result["see"] = True
            elif isinstance(stmt, StatementCall):
                check_call(stmt.name)
                for arg in stmt.args:
                    visit_expr(arg)
            elif isinstance(stmt, Assignment):
                visit_expr(stmt.value)
            elif isinstance(stmt, DestructureAssignment):
                visit_expr(stmt.value)
            elif isinstance(stmt, IfThen):
                visit_expr(stmt.condition)
                visit_stmts(stmt.then_body)
                if stmt.else_body:
                    visit_stmts(stmt.else_body)
            elif isinstance(stmt, ForLoop):
                visit_expr(stmt.start)
                visit_expr(stmt.end)
                visit_stmts(stmt.body)
            elif isinstance(stmt, CaseOf):
                visit_expr(stmt.expr)
                for clause in stmt.clauses:
                    visit_expr(clause.pattern)
                    visit_stmts(clause.body)
                if stmt.else_body:
                    visit_stmts(stmt.else_body)
            elif isinstance(stmt, WhenClause):
                visit_expr(stmt.pattern)
                visit_stmts(stmt.body)

    visit_stmts(program.statements)
    return result


def extract_side_effects(program: Program) -> dict[str, bool]:
    """Detect side-effects (UNPREDICTABLE, UNDEFINED, SEE) in ARM pseudocode.

    Args:
        program: A parsed pseudocode Program AST.

    Returns:
        A dict with boolean flags for each side-effect type.
    """
    return _collect_sideeffects(program)
