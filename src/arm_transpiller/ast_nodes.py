from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Node: ...


# --- Expressions ---


@dataclass(frozen=True)
class Expression(Node): ...


@dataclass(frozen=True)
class IntegerLiteral(Expression):
    value: int


@dataclass(frozen=True)
class HexLiteral(Expression):
    value: int


@dataclass(frozen=True)
class BitLiteral(Expression):
    value: int  # 0 or 1


@dataclass(frozen=True)
class BitStringLiteral(Expression):
    value: str  # raw bit string, e.g. "01", "1010"


@dataclass(frozen=True)
class StringLiteral(Expression):
    value: str  # raw string content, e.g. "Related instructions", "Some text"


@dataclass(frozen=True)
class Identifier(Expression):
    name: str


@dataclass(frozen=True)
class RegisterAccess(Expression):
    index: Expression


@dataclass(frozen=True)
class FunctionCall(Expression):
    name: str
    args: list[Expression] = field(default_factory=list)


@dataclass(frozen=True)
class BitfieldConcat(Expression):
    left: Expression
    right: Expression


@dataclass(frozen=True)
class FieldAccess(Expression):
    base: str
    field: str


@dataclass(frozen=True)
class SetLiteral(Expression):
    elements: list[Expression] = field(default_factory=list)


@dataclass(frozen=True)
class Range(Expression):
    start: int
    end: int


@dataclass(frozen=True)
class TupleLiteral(Expression):
    elements: list[Expression] = field(default_factory=list)


@dataclass(frozen=True)
class BinaryOp(Expression):
    left: Expression
    op: str
    right: Expression


@dataclass(frozen=True)
class UnaryOp(Expression):
    op: str
    operand: Expression


@dataclass(frozen=True)
class InExpr(Expression):
    left: Expression
    set: SetLiteral


@dataclass(frozen=True)
class BitIndex(Expression):
    name: str
    index: Expression


@dataclass(frozen=True)
class BitRange(Expression):
    name: str
    high: Expression
    low: Expression


@dataclass(frozen=True)
class IfExpr(Expression):
    condition: Expression
    then_value: Expression
    else_value: Expression


@dataclass(frozen=True)
class PatternMatch(Expression):
    expr: Expression
    pattern: str  # e.g. "10x"


@dataclass(frozen=True)
class ArrayAccess(Expression):
    name: str
    args: list[Expression] = field(default_factory=list)


# --- Statements ---


@dataclass(frozen=True)
class Statement(Node): ...


@dataclass(frozen=True)
class Program(Node):
    statements: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class Assignment(Statement):
    target: str | RegisterAccess | FieldAccess | BitIndex
    value: Expression
    arch_visible: bool = True  # True for =, False for :=


@dataclass(frozen=True)
class DestructureAssignment(Statement):
    targets: list[str | None]  # None = wildcard (-)
    value: Expression


@dataclass(frozen=True)
class IfThen(Statement):
    condition: Expression
    then_body: list[Statement] = field(default_factory=list)
    else_body: list[Statement] | None = None


@dataclass(frozen=True)
class Unpredictable(Statement): ...


@dataclass(frozen=True)
class Undefined(Statement): ...


@dataclass(frozen=True)
class StatementCall(Statement):
    name: str
    args: list[Expression] = field(default_factory=list)


@dataclass(frozen=True)
class ForLoop(Statement):
    variable: str
    start: Expression
    end: Expression
    body: list[Statement] = field(default_factory=list)


@dataclass(frozen=True)
class Comment(Statement):
    text: str
    trailing: bool = False


@dataclass(frozen=True)
class SeeStmt(Statement):
    instruction: str


@dataclass(frozen=True)
class WhenClause(Statement):
    pattern: Expression
    body: list[Statement] = field(default_factory=list)
    comment: str | None = None


@dataclass(frozen=True)
class CaseOf(Statement):
    expr: Expression
    clauses: list[WhenClause] = field(default_factory=list)
    else_body: list[Statement] | None = None
