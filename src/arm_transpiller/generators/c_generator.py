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

_NO_SEMICOLON = (Comment, DestructureAssignment, SeeStmt)

_C_KEYWORDS = frozenset(
    {
        "auto",
        "break",
        "case",
        "char",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extern",
        "float",
        "for",
        "goto",
        "if",
        "inline",
        "int",
        "long",
        "register",
        "restrict",
        "return",
        "short",
        "signed",
        "sizeof",
        "static",
        "struct",
        "switch",
        "typedef",
        "union",
        "unsigned",
        "void",
        "volatile",
        "while",
        "_Bool",
        "_Complex",
        "_Imaginary",
    }
)

CPP_OPS: dict[str, str] = {
    "||": "||",
    "&&": "&&",
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
    "DIV": "/",
    ":": "concat_bits",
    "!": "!",
    "NOT": "~",
    "~": "~",
    "EOR": "^",
    "OR": "|",
    "AND": "&",
    "XOR": "^",
}

_INDENT = "    "

# Operators whose result depends on the signedness of their operands.  C's
# usual arithmetic conversions would make a signed operand unsigned, so both
# sides are cast to the runtime's signed type when either side is signed.
# ``==`` and ``!=`` are excluded: every value lives in a 32-bit container, so
# comparing the bit patterns gives the same answer either way.
_SIGNEDNESS_SENSITIVE_OPS = frozenset({"<", ">", "<=", ">=", "/", "DIV", "MOD"})

_SIGNED_C_TYPE = "int32_t"


class CGenerator(CodeGenerator):
    """Transpile an ARM pseudocode AST into C source code.

    Bitfield concatenation (``:``) is lowered to ``concat_bits()`` calls,
    ``IN`` is expanded to chained ``==`` comparisons, and ``NOT`` becomes
    the C ``!`` operator.  ``for`` loops use C99 inline variable declarations.
    """

    def __init__(self, input_types: Mapping[str, str | ArmType] | None = None) -> None:
        super().__init__(input_types=input_types)
        self._tuple_2_counter = 0

    def type_annotation(self, arm_type: ArmType | None) -> str:
        """Return the C type annotation for *arm_type*."""
        if arm_type is None:
            return "uint32_t"
        if isinstance(arm_type, TupleType):
            raise NotImplementedError("TupleType has no single C type annotation")
        if isinstance(arm_type, ScalarType):
            if arm_type.kind == "bool":
                return "bool"
            if arm_type.kind == "sint":
                return "int32_t"
        return "uint32_t"

    def zero_value(self, arm_type: ArmType | None) -> str:
        """Return the C literal for the zero of *arm_type*."""
        if arm_type is None:
            return "0"
        if isinstance(arm_type, TupleType):
            raise NotImplementedError("TupleType has no single C zero literal")
        if isinstance(arm_type, ScalarType) and arm_type.kind == "bool":
            return "false"
        return "0"

    @staticmethod
    def _c_name(name: str) -> str:
        return f"_{name}" if name in _C_KEYWORDS else name

    def generate(self, program: Program) -> str:
        """Emit C source for *program*.

        Returns:
            A string containing the complete C source, terminated by a
            trailing newline.
        """
        self._tuple_2_counter = 0
        self._infer_types(program)
        lines: list[str] = []
        for stmt in program.statements:
            line = self.visit_statement(stmt, 0)
            if not isinstance(stmt, _NO_SEMICOLON):
                line += ";"
            lines.append(line)
        return "\n".join(lines) + "\n"

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
                return _INDENT * indent + f"// {stmt.text}"
            case Unpredictable():
                return _INDENT * indent + "sideffects |= SIDEFFECT_UNPREDICTABLE"
            case Undefined():
                return _INDENT * indent + "sideffects |= SIDEFFECT_UNDEFINED"
            case SeeStmt():
                return (
                    _INDENT * indent
                    + f'sideffects |= SIDEFFECT_SEE;  // "{stmt.instruction}"'
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
                    return "true"
                if expr.name == "FALSE":
                    return "false"
                if expr.name == "FPSCR":
                    return "ctx->fpscr"
                return self._c_name(expr.name)
            case FieldAccess():
                if expr.base == "APSR":
                    return f"ctx->apsr.{expr.field}"
                return f"{self._c_name(expr.base.lower())}.{expr.field}"
            case BitIndex():
                idx = self.visit_expression(expr.index)
                base = "ctx->fpscr" if expr.name == "FPSCR" else self._c_name(expr.name)
                return f"(({base} >> {idx}) & 1)"
            case BitRange():
                low_str = self.visit_expression(expr.low)
                width = self._get_expr_width(expr)
                mask = hex((1 << width) - 1)
                base = "ctx->fpscr" if expr.name == "FPSCR" else self._c_name(expr.name)
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
                    c_op = CPP_OPS[expr.op]
                    return f"(({left} {c_op} {right}) & {mask}u)"
                c_op = CPP_OPS.get(expr.op, expr.op)
                left = self.visit_expression(expr.left)
                right = self.visit_expression(expr.right)
                if expr.op in _SIGNEDNESS_SENSITIVE_OPS and (
                    self._is_signed(expr.left) or self._is_signed(expr.right)
                ):
                    left = f"({_SIGNED_C_TYPE}){left}"
                    right = f"({_SIGNED_C_TYPE}){right}"
                return f"({left} {c_op} {right})"
            case UnaryOp():
                c_op = CPP_OPS.get(expr.op, expr.op)
                if expr.op in ("NOT", "~"):
                    operand = self.visit_expression(expr.operand)
                    width = self._get_bitwise_width(expr.operand)
                    mask = hex((1 << width) - 1)
                    return f"(({c_op}{operand}) & {mask}u)"
                return f"({c_op}{self.visit_expression(expr.operand)})"
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
                    args = ", ".join(["&sideffects", *partial])
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
                        parts.append(f"({left} >= {e.start} && {left} <= {e.end})")
                    else:
                        parts.append(f"({left} == {self.visit_expression(e)})")
                return f"({' || '.join(parts)})"
            case SetLiteral():
                return (
                    f"{{{', '.join(self.visit_expression(e) for e in expr.elements)}}}"
                )
            case TupleLiteral():
                fields = ", ".join(
                    f".f{i} = {self.visit_expression(e)}"
                    for i, e in enumerate(expr.elements)
                )
                return f"(Tuple2Ret){{{fields}}}"
            case IfExpr():
                cond = self.visit_expression(expr.condition)
                then_val = self.visit_expression(expr.then_value)
                else_val = self.visit_expression(expr.else_value)
                return f"({cond} ? {then_val} : {else_val})"
            case PatternMatch():
                expr_str = self.visit_expression(expr.expr)
                pm_mask = 0
                pm_value = 0
                for ch in expr.pattern:
                    pm_mask = (pm_mask << 1) | (0 if ch == "x" else 1)
                    pm_value = (pm_value << 1) | (1 if ch == "1" else 0)
                return f"(({expr_str} & {hex(pm_mask)}u) == {hex(pm_value)}u)"
            case _:
                raise NotImplementedError(
                    f"No expression visitor for {type(expr).__name__}"
                )

    def _assignment(self, stmt: Assignment, indent: int = 0) -> str:
        value = self.visit_expression(stmt.value)
        if isinstance(stmt.target, str):
            lhs = self._c_name(stmt.target)
            return _INDENT * indent + f"{lhs} = {value}"
        elif isinstance(stmt.target, FieldAccess):
            if stmt.target.base == "APSR":
                lhs = f"ctx->apsr.{stmt.target.field}"
            else:
                lhs = f"{self._c_name(stmt.target.base.lower())}.{stmt.target.field}"
            return _INDENT * indent + f"{lhs} = {value}"
        elif isinstance(stmt.target, BitIndex):
            name = self._c_name(stmt.target.name)
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
        self._tuple_2_counter += 1
        tmp = f"tuple_2_ret_{self._tuple_2_counter}"
        value = self.visit_expression(stmt.value)
        lines = [f"{pad}Tuple2Ret {tmp} = {value};"]
        for i, target in enumerate(stmt.targets):
            if target is not None:
                lines.append(f"{pad}{self._c_name(target)} = {tmp}.f{i};")
        return "\n".join(lines)

    def _if_then(self, stmt: IfThen, indent: int) -> str:
        pad = _INDENT * indent
        cond = self.visit_expression(stmt.condition)
        lines = [f"{pad}if ({cond}) {{"]
        for s in stmt.then_body:
            body_line = self.visit_statement(s, indent + 1)
            if not isinstance(s, _NO_SEMICOLON):
                body_line += ";"
            lines.append(body_line)
        if stmt.else_body:
            lines.append(f"{pad}}} else {{")
            for s in stmt.else_body:
                body_line = self.visit_statement(s, indent + 1)
                if not isinstance(s, _NO_SEMICOLON):
                    body_line += ";"
                lines.append(body_line)
        lines.append(f"{pad}}}")
        return "\n".join(lines)

    def _for_loop(self, stmt: ForLoop, indent: int) -> str:
        pad = _INDENT * indent
        var = self._c_name(stmt.variable)
        start = self.visit_expression(stmt.start)
        end = self.visit_expression(stmt.end)
        lines = [f"{pad}for (int {var} = {start}; {var} <= {end}; {var}++) {{"]
        for s in stmt.body:
            body_line = self.visit_statement(s, indent + 1)
            if not isinstance(s, _NO_SEMICOLON):
                body_line += ";"
            lines.append(body_line)
        lines.append(f"{pad}}}")
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
            comment = f"  // {clause.comment}" if clause.comment else ""
            if i == 0:
                lines.append(f"{pad}if ({expr} == {pattern}) {{{comment}")
            else:
                lines.append(f"{pad}}} else if ({expr} == {pattern}) {{{comment}")
            for s in clause.body:
                body_line = self.visit_statement(s, indent + 1)
                if not isinstance(s, _NO_SEMICOLON):
                    body_line += ";"
                lines.append(body_line)
        if stmt.else_body:
            lines.append(f"{pad}}} else {{")
            for s in stmt.else_body:
                body_line = self.visit_statement(s, indent + 1)
                if not isinstance(s, _NO_SEMICOLON):
                    body_line += ";"
                lines.append(body_line)
        lines.append(f"{pad}}}")
        return "\n".join(lines)
