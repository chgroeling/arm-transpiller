from __future__ import annotations

from typing import Mapping

from ..ast_nodes import (
    ArrayAccess,
    Assignment,
    BinaryOp,
    BitIndex,
    BitLiteral,
    BitRange,
    BitStringLiteral,
    CaseOf,
    Comment,
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
    Range,
    RegisterAccess,
    SeeStmt,
    SetLiteral,
    Statement,
    StatementCall,
    StringLiteral,
    TupleLiteral,
    UnaryOp,
    Undefined,
    Unpredictable,
    WhenClause,
)
from ..known_types import ArmType, ScalarType, TupleType
from .base import CodeGenerator

PY_OPS: dict[str, str] = {
    "||": "or",
    "&&": "and",
    "==": "==",
    "!=": "!=",
    "<": "<",
    ">": ">",
    "<=": "<=",
    ">=": ">=",
    "+": "+",
    "-": "-",
    "*": "*",
    "/": "/",
    "MOD": "%",
    "DIV": "//",
    "!": "not ",
    "NOT": "~",
    "~": "~",
    "EOR": "^",
    "OR": "|",
    "AND": "&",
    "XOR": "^",
}

_INDENT = "    "


class PythonGenerator(CodeGenerator):
    """Transpile an ARM pseudocode AST into Python source code.

    Logical operators (``||``, ``&&``, ``NOT``) become Python
    ``or`` / ``and`` / ``not``.  ``IN`` is emitted as the native
    ``in`` operator, and ``for`` loops use ``range(start, end+1)``.
    """

    def __init__(self, input_types: Mapping[str, str | ArmType] | None = None) -> None:
        super().__init__(input_types=input_types)

    def type_annotation(self, arm_type: ArmType | None) -> str:
        """Return the Python type annotation for *arm_type*."""
        if arm_type is None:
            return "int"
        if isinstance(arm_type, TupleType):
            raise NotImplementedError("TupleType has no single Python type annotation")
        if isinstance(arm_type, ScalarType) and arm_type.kind == "bool":
            return "bool"
        return "int"

    def zero_value(self, arm_type: ArmType | None) -> str:
        """Return the Python literal for the zero of *arm_type*."""
        if arm_type is None:
            return "0"
        if isinstance(arm_type, TupleType):
            raise NotImplementedError("TupleType has no single Python zero literal")
        if isinstance(arm_type, ScalarType) and arm_type.kind == "bool":
            return "False"
        return "0"

    def generate(self, program: Program) -> str:
        """Emit Python source for *program*.

        Returns:
            A string containing the complete Python source, terminated by a
            trailing newline.
        """
        self._infer_types(program)
        return "\n".join(self.visit_statement(s, 0) for s in program.statements) + "\n"

    def visit_statement(self, stmt: Statement, indent: int = 0) -> str:
        match stmt:
            case Assignment():
                return self._assignment(stmt, indent)
            case DestructureAssignment():
                return self._destructure_assignment(stmt, indent)
            case IfThen():
                return self._if_then(stmt, indent)
            case ForLoop():
                return self._for_loop(stmt, indent)
            case StatementCall():
                return self._statement_call(stmt, indent)
            case Comment():
                return _INDENT * indent + f"# {stmt.text}"
            case Unpredictable():
                return _INDENT * indent + "sideffects |= SIDEFFECT_UNPREDICTABLE"
            case Undefined():
                return _INDENT * indent + "sideffects |= SIDEFFECT_UNDEFINED"
            case SeeStmt():
                return (
                    _INDENT * indent
                    + f'sideffects |= SIDEFFECT_SEE  # "{stmt.instruction}"'
                )
            case CaseOf():
                return self._case_of(stmt, indent)
            case WhenClause():
                return "\n".join(self.visit_statement(s, indent) for s in stmt.body)
            case _:
                raise NotImplementedError(f"No visitor for {type(stmt).__name__}")

    def visit_expression(self, expr: Expression) -> str:
        match expr:
            case IntegerLiteral():
                return str(expr.value)
            case HexLiteral():
                return hex(expr.value)
            case BitLiteral():
                return str(expr.value)
            case BitStringLiteral():
                return hex(int(expr.value, 2))
            case StringLiteral():
                return f'"{expr.value}"'
            case Identifier():
                if expr.name == "TRUE":
                    return "True"
                if expr.name == "FALSE":
                    return "False"
                if expr.name == "FPSCR":
                    return "ctx.fpscr"
                return expr.name
            case FieldAccess():
                if expr.base == "APSR":
                    return f"ctx.apsr.{expr.field}"
                return f"{expr.base.lower()}.{expr.field}"
            case BitIndex():
                idx = self.visit_expression(expr.index)
                base = "ctx.fpscr" if expr.name == "FPSCR" else expr.name
                return f"(({base} >> {idx}) & 1)"
            case BitRange():
                low_str = self.visit_expression(expr.low)
                width = self._get_expr_width(expr)
                mask = hex((1 << width) - 1)
                base = "ctx.fpscr" if expr.name == "FPSCR" else expr.name
                return f"(({base} >> {low_str}) & {mask})"
            case RegisterAccess():
                return f"R[{self.visit_expression(expr.index)}]"
            case ArrayAccess():
                args = ", ".join(self.visit_expression(a) for a in expr.args)
                return f"{expr.name}_read(ctx, {args})"
            case BinaryOp():
                if expr.op == ":":
                    left = self.visit_expression(expr.left)
                    right = self.visit_expression(expr.right)
                    right_width = self._get_expr_width(expr.right)
                    return f"concat_bits({left}, {right}, {right_width})"
                if expr.op in ("EOR", "OR", "AND"):
                    left = self.visit_expression(expr.left)
                    right = self.visit_expression(expr.right)
                    width = self._get_bitwise_width(expr)
                    mask = hex((1 << width) - 1)
                    py_op = PY_OPS[expr.op]
                    return f"(({left} {py_op} {right}) & {mask})"
                py_op = PY_OPS.get(expr.op, expr.op)
                left = self.visit_expression(expr.left)
                right = self.visit_expression(expr.right)
                return f"({left} {py_op} {right})"
            case UnaryOp():
                py_op = PY_OPS.get(expr.op, expr.op)
                if py_op == "not ":
                    return f"({py_op}({self.visit_expression(expr.operand)}))"
                if expr.op in ("NOT", "~"):
                    operand = self.visit_expression(expr.operand)
                    width = self._get_bitwise_width(expr.operand)
                    mask = hex((1 << width) - 1)
                    return f"(({py_op}{operand}) & {mask})"
                return f"({py_op}{self.visit_expression(expr.operand)})"
            case FunctionCall():
                # SignExtend and SInt read their operand as a signed value, so
                # the runtime needs the width to sign-extend from -- ARM leaves
                # it implicit in the operand's type.  SInt keeps an explicitly
                # written width; SignExtend's second argument is the target
                # width, which the runtime does not need.
                if expr.name == "SignExtend" or (
                    expr.name == "SInt" and len(expr.args) == 1
                ):
                    src_width = self._get_expr_width(expr.args[0])
                    value = self.visit_expression(expr.args[0])
                    return f"{expr.name}({value}, {src_width})"
                partial = [self.visit_expression(a) for a in expr.args]
                if expr.name in (
                    "ThumbExpandImm",
                    "ThumbExpandImm_C",
                ):
                    args = ", ".join(["sideffects", *partial])
                elif expr.name in (
                    "InITBlock",
                    "LastInITBlock",
                ):
                    args = ", ".join(["ctx", *partial])
                else:
                    args = ", ".join(partial)
                return f"{expr.name}({args})"
            case InExpr():
                left = self.visit_expression(expr.left)
                parts: list[str] = []
                for e in expr.set.elements:
                    if isinstance(e, Range):
                        parts.append(f"({e.start} <= {left} <= {e.end})")
                    else:
                        parts.append(f"({left} == {self.visit_expression(e)})")
                return f"({' or '.join(parts)})"
            case SetLiteral():
                return (
                    f"{{{', '.join(self.visit_expression(e) for e in expr.elements)}}}"
                )
            case TupleLiteral():
                elements = ", ".join(self.visit_expression(e) for e in expr.elements)
                return f"({elements})"
            case IfExpr():
                cond = self.visit_expression(expr.condition)
                then_val = self.visit_expression(expr.then_value)
                else_val = self.visit_expression(expr.else_value)
                return f"({then_val} if {cond} else {else_val})"
            case PatternMatch():
                expr_str = self.visit_expression(expr.expr)
                pm_mask = 0
                pm_value = 0
                for ch in expr.pattern:
                    pm_mask = (pm_mask << 1) | (0 if ch == "x" else 1)
                    pm_value = (pm_value << 1) | (1 if ch == "1" else 0)
                return f"(({expr_str} & {hex(pm_mask)}) == {hex(pm_value)})"
            case _:
                raise NotImplementedError(
                    f"No expression visitor for {type(expr).__name__}"
                )

    def _assignment(self, stmt: Assignment, indent: int = 0) -> str:
        value = self.visit_expression(stmt.value)
        if isinstance(stmt.target, str):
            lhs = stmt.target
            return _INDENT * indent + f"{lhs} = {value}"
        elif isinstance(stmt.target, FieldAccess):
            if stmt.target.base == "APSR":
                lhs = f"ctx.apsr.{stmt.target.field}"
            else:
                lhs = f"{stmt.target.base.lower()}.{stmt.target.field}"
            return _INDENT * indent + f"{lhs} = {value}"
        elif isinstance(stmt.target, BitIndex):
            name = stmt.target.name
            idx = self.visit_expression(stmt.target.index)
            return _INDENT * indent + f"{name} = ({name} | ({value} << {idx}))"
        elif isinstance(stmt.target, ArrayAccess):
            args = ", ".join(self.visit_expression(a) for a in stmt.target.args)
            return _INDENT * indent + f"{stmt.target.name}_write(ctx, {args}, {value})"
        else:
            lhs = self.visit_expression(stmt.target)
            return _INDENT * indent + f"{lhs} = {value}"

    def _destructure_assignment(self, stmt: DestructureAssignment, indent: int) -> str:
        pad = _INDENT * indent
        targets = ", ".join((t if t is not None else "_") for t in stmt.targets)
        value = self.visit_expression(stmt.value)
        return f"{pad}{targets} = {value}"

    def _if_then(self, stmt: IfThen, indent: int) -> str:
        pad = _INDENT * indent
        cond = self.visit_expression(stmt.condition)
        lines = [f"{pad}if {cond}:"]
        for s in stmt.then_body:
            lines.append(self.visit_statement(s, indent + 1))
        if stmt.else_body:
            lines.append(f"{pad}else:")
            for s in stmt.else_body:
                lines.append(self.visit_statement(s, indent + 1))
        return "\n".join(lines)

    def _for_loop(self, stmt: ForLoop, indent: int) -> str:
        pad = _INDENT * indent
        var = stmt.variable
        start = self.visit_expression(stmt.start)
        end = self.visit_expression(stmt.end)
        lines = [f"{pad}for {var} in range({start}, {end} + 1):"]
        for s in stmt.body:
            lines.append(self.visit_statement(s, indent + 1))
        return "\n".join(lines)

    def _statement_call(self, stmt: StatementCall, indent: int) -> str:
        args = ", ".join(self.visit_expression(a) for a in stmt.args)
        return _INDENT * indent + f"{stmt.name}({args})"

    def _case_of(self, stmt: CaseOf, indent: int) -> str:
        pad = _INDENT * indent
        expr = self.visit_expression(stmt.expr)
        lines: list[str] = []
        for i, clause in enumerate(stmt.clauses):
            pattern = self.visit_expression(clause.pattern)
            keyword = "if" if i == 0 else "elif"
            comment = f"  # {clause.comment}" if clause.comment else ""
            lines.append(f"{pad}{keyword} {expr} == {pattern}:{comment}")
            for s in clause.body:
                lines.append(self.visit_statement(s, indent + 1))
        if stmt.else_body:
            lines.append(f"{pad}else:")
            for s in stmt.else_body:
                lines.append(self.visit_statement(s, indent + 1))
        return "\n".join(lines)
