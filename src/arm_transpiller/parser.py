from __future__ import annotations

from typing import Any, cast

from lark import Lark, Token, Transformer
from lark.visitors import v_args

from .ast_nodes import (
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
from .grammar_path import read_grammar


def _preprocess_indentation(source: str) -> str:
    lines = source.split("\n")
    result: list[str] = []
    indent_stack: list[int] = [0]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())

        if stripped.startswith("//"):
            comment_text = stripped[2:].strip()
            if indent > indent_stack[-1]:
                result.append("begin")
                indent_stack.append(indent)
            elif indent < indent_stack[-1]:
                while indent < indent_stack[-1]:
                    result.append("end;")
                    indent_stack.pop()
            result.append(f'__CMT__"{comment_text}";')
            continue

        code_part, sep, comment_part = stripped.partition("//")
        code_only = code_part.strip()
        inline_comment = comment_part.strip() if comment_part else None

        if indent > indent_stack[-1]:
            result.append("begin")
            indent_stack.append(indent)
        elif indent < indent_stack[-1]:
            while indent < indent_stack[-1]:
                result.append("end;")
                indent_stack.pop()

        result.append(code_only)
        if inline_comment:
            result.append(f'__CMT_INLINE__"{inline_comment}";')

    while len(indent_stack) > 1:
        result.append("end;")
        indent_stack.pop()

    return " ".join(result)


def _preprocess_see(source: str) -> str:
    import re

    result: list[str] = []
    i = 0
    while i < len(source):
        match = re.match(r"SEE\s+", source[i:])
        if match:
            result.append("SEE")
            i += match.end()
            end = source.find(";", i)
            if end == -1:
                arg = source[i:].strip()
                i = len(source)
            else:
                arg = source[i:end].strip()
                i = end
            escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
            result.append(f'__SEE__"{escaped}"')
        else:
            result.append(source[i])
            i += 1
    return "".join(result)


class ASTBuilder(Transformer[Any, Any]):
    def start(self, items: list[Any]) -> Program:
        return Program(list(items[0]))

    def statement_list(self, items: list[Any]) -> list[Statement]:
        return [cast(Statement, item) for item in items if not isinstance(item, Token)]

    def assignment(self, items: list[Any]) -> Assignment:
        target_item = items[0]
        if isinstance(target_item, Token):
            target: str | RegisterAccess | FieldAccess | BitIndex = str(target_item)
        elif isinstance(target_item, (FieldAccess, BitIndex)):
            target = target_item
        else:
            target = cast(RegisterAccess, target_item)
        op_token = cast(Token, items[1])
        value = cast(Expression, items[2])
        return Assignment(
            target=target,
            value=value,
            arch_visible=(str(op_token) == "="),
        )

    def destructure_assignment(self, items: list[Any]) -> DestructureAssignment:
        assign_idx = next(
            i
            for i, item in enumerate(items)
            if isinstance(item, Token) and str(item) in ("=", ":=")
        )
        targets: list[str | None] = []
        for item in items[:assign_idx]:
            if isinstance(item, Token):
                continue
            if item is None:
                targets.append(None)
            elif isinstance(item, Identifier):
                targets.append(item.name)
        value = cast(Expression, items[-1])
        return DestructureAssignment(targets=targets, value=value)

    def wildcard(self, items: list[Any]) -> None:
        return None

    def conditional(self, items: list[Any]) -> IfThen:
        condition = cast(Expression, items[0])
        then_body = cast(list[Statement], items[1])
        else_body: list[Statement] | None = (
            cast(list[Statement], items[2]) if len(items) > 2 else None
        )
        return IfThen(condition=condition, then_body=then_body, else_body=else_body)

    def for_stmt(self, items: list[Any]) -> ForLoop:
        variable = str(cast(Token, items[0]))
        start = cast(Expression, items[1])
        end = cast(Expression, items[2])
        body = cast(list[Statement], items[3])
        return ForLoop(variable=variable, start=start, end=end, body=body)

    def block(self, items: list[Any]) -> list[Statement]:
        return cast(list[Statement], items[0])

    def body(self, items: list[Any]) -> list[Statement]:
        result = items[0]
        if isinstance(result, list):
            return cast(list[Statement], result)
        return [cast(Statement, result)]

    def case_stmt(self, items: list[Any]) -> CaseOf:
        expr = cast(Expression, items[1])
        raw_body = cast(list[Statement], items[2])
        clauses: list[WhenClause] = []
        others: list[Statement] = []
        pending_comment: str | None = None
        for stmt in raw_body:
            if isinstance(stmt, WhenClause):
                if stmt.comment is None and pending_comment is not None:
                    stmt = WhenClause(
                        pattern=stmt.pattern,
                        body=stmt.body,
                        comment=pending_comment,
                    )
                pending_comment = None
                clauses.append(stmt)
            elif isinstance(stmt, Comment):
                pending_comment = stmt.text
            else:
                others.append(stmt)
        else_body = others if others else None
        return CaseOf(expr=expr, clauses=clauses, else_body=else_body)

    def when_clause(self, items: list[Any]) -> WhenClause:
        pattern = cast(Expression, items[1])
        inline = items[2] if isinstance(items[2], Comment) else None
        body = cast(list[Statement], items[-1])
        return WhenClause(
            pattern=pattern,
            body=body,
            comment=inline.text if inline else None,
        )

    def statement_call(self, items: list[Any]) -> StatementCall:
        name = str(cast(Token, items[0]))
        args: list[Expression] = [
            cast(Expression, item)
            for item in items[1:]
            if not isinstance(item, Token) and item is not None
        ]
        return StatementCall(name=name, args=args)

    @v_args(inline=True)
    def unpredictable(self, token: Token) -> Unpredictable:
        return Unpredictable()

    @v_args(inline=True)
    def undefined(self, token: Token) -> Undefined:
        return Undefined()

    def comment(self, items: list[Any]) -> Comment:
        token = cast(Token, items[0])
        raw = str(token)
        text = raw[len('__CMT__"') : -1]
        return Comment(text=text, trailing=False)

    def trailing_comment(self, items: list[Any]) -> Comment:
        token = cast(Token, items[0])
        raw = str(token)
        text = raw[len('__CMT_INLINE__"') : -1]
        return Comment(text=text, trailing=True)

    def or_expr(self, items: list[Any]) -> Expression:
        return self._binop_chain(items)

    def and_expr(self, items: list[Any]) -> Expression:
        return self._binop_chain(items)

    def equality_expr(self, items: list[Any]) -> Expression:
        return self._binop_chain(items)

    def bitwise_expr(self, items: list[Any]) -> Expression:
        return self._binop_chain(items)

    def relational_expr(self, items: list[Any]) -> Expression:
        if len(items) == 1:
            return cast(Expression, items[0])
        result: Expression = cast(Expression, items[0])
        i = 1
        while i < len(items):
            token = items[i]
            if isinstance(token, Token) and str(token) == "IN":
                rhs = items[i + 1]
                if isinstance(rhs, SetLiteral):
                    result = InExpr(left=result, set=rhs)
                elif isinstance(rhs, StringLiteral):
                    result = PatternMatch(expr=result, pattern=rhs.value)
                else:
                    result = InExpr(left=result, set=rhs)
                i += 2
            else:
                right = cast(Expression, items[i + 1])
                result = BinaryOp(left=result, op=str(cast(Token, token)), right=right)
                i += 2
        return result

    def concat_expr(self, items: list[Any]) -> Expression:
        return self._binop_chain(items)

    def additive_expr(self, items: list[Any]) -> Expression:
        return self._binop_chain(items)

    def multiplicative_expr(self, items: list[Any]) -> Expression:
        return self._binop_chain(items)

    @v_args(inline=True)
    def unary_expr(self, *items: Any) -> Expression:
        if len(items) == 2:
            op_token, operand = items
            return UnaryOp(
                op=str(cast(Token, op_token)), operand=cast(Expression, operand)
            )
        return cast(Expression, items[0])

    @v_args(inline=True)
    def hex_literal(self, token: Token) -> HexLiteral:
        return HexLiteral(value=int(str(token), 16))

    @v_args(inline=True)
    def bit_literal(self, token: Token) -> BitLiteral:
        return BitLiteral(value=int(str(token)[1]))

    @v_args(inline=True)
    def bitstring_literal(self, token: Token) -> BitStringLiteral:
        raw = str(token).strip("'")
        return BitStringLiteral(value=raw)

    @v_args(inline=True)
    def string_literal(self, token: Token) -> StringLiteral:
        raw = str(token).strip('"')
        return StringLiteral(value=raw)

    @v_args(inline=True)
    def int_literal(self, token: Token) -> IntegerLiteral:
        return IntegerLiteral(value=int(str(token)))

    @v_args(inline=True)
    def identifier(self, token: Token) -> Identifier:
        return Identifier(name=str(token))

    def function_call(self, items: list[Any]) -> FunctionCall:
        name: str = str(cast(Token, items[0]))
        args: list[Expression] = [
            cast(Expression, item)
            for item in items[1:]
            if not isinstance(item, Token) and item is not None
        ]
        return FunctionCall(name=name, args=args)

    def register_access(self, items: list[Any]) -> RegisterAccess:
        index = cast(Expression, items[1])
        return RegisterAccess(index=index)

    def array_access(self, items: list[Any]) -> ArrayAccess:
        name = str(cast(Token, items[0]))
        args: list[Expression] = [
            cast(Expression, item)
            for item in items[1:]
            if not isinstance(item, Token) and item is not None
        ]
        return ArrayAccess(name=name, args=args)

    def bit_range(self, items: list[Any]) -> BitRange:
        name = str(cast(Token, items[0]))
        high = cast(Expression, items[1])
        low = cast(Expression, items[2])
        return BitRange(name=name, high=high, low=low)

    def bit_index(self, items: list[Any]) -> BitIndex:
        name = str(cast(Token, items[0]))
        index = cast(Expression, items[1])
        return BitIndex(name=name, index=index)

    def field_access(self, items: list[Any]) -> FieldAccess:
        base = str(cast(Token, items[0]))
        field = str(cast(Token, items[1]))
        return FieldAccess(base=base, field=field)

    @v_args(inline=True)
    def range_expr(self, start_tok: Token, op_tok: Token, end_tok: Token) -> Range:
        return Range(start=int(str(start_tok)), end=int(str(end_tok)))

    def see_stmt(self, items: list[Any]) -> SeeStmt:
        token = cast(Token, items[1])
        raw = str(token)
        text = raw[len("__SEE__") + 1 : -1]
        text = text.replace('\\"', '"').replace("\\\\", "\\")
        if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        return SeeStmt(instruction=text)

    def set_literal(self, items: list[Any]) -> SetLiteral:
        elements: list[Expression] = [
            cast(Expression, item)
            for item in items
            if not isinstance(item, Token) and item is not None
        ]
        return SetLiteral(elements=elements)

    def tuple_literal(self, items: list[Any]) -> TupleLiteral:
        elements: list[Expression] = [
            cast(Expression, item)
            for item in items
            if not isinstance(item, Token) and item is not None
        ]
        return TupleLiteral(elements=elements)

    def if_expr(self, items: list[Any]) -> IfExpr:
        condition = cast(Expression, items[0])
        then_value = cast(Expression, items[1])
        else_value = cast(Expression, items[2])
        return IfExpr(condition=condition, then_value=then_value, else_value=else_value)

    @staticmethod
    def _binop_chain(items: list[Any]) -> Expression:
        if len(items) == 1:
            return cast(Expression, items[0])
        result: Expression = cast(Expression, items[0])
        for i in range(1, len(items), 2):
            right = cast(Expression, items[i + 1])
            result = BinaryOp(left=result, op=str(cast(Token, items[i])), right=right)
        return result


def make_parser() -> Lark:
    return Lark(
        read_grammar(),
        start="start",
        parser="earley",
        propagate_positions=False,
    )


def parse(source: str, preprocess: bool = True) -> Program:
    """Parse ARM pseudocode source into a typed AST.

    Args:
        source: Raw ARM pseudocode text (indentation-based scoping).
        preprocess: If True (default), convert indentation into explicit
            ``begin``/``end`` markers before parsing.

    Returns:
        A :class:`Program` AST node whose ``statements`` list contains the
        top-level statements.
    """
    if preprocess:
        source = _preprocess_indentation(source)
        source = _preprocess_see(source)
    parser = make_parser()
    tree = parser.parse(source)
    builder = ASTBuilder()
    result = builder.transform(tree)
    return cast(Program, result)
