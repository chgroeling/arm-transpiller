"""Type inference for ARM pseudocode.

Every expression is given an :class:`~.known_types.ArmType` — ``bitsN`` /
``uintN`` / ``sintN`` / ``bool`` / ``tuple[...]`` — and every variable defined
by the pseudocode gets the type of the value assigned to it.  Values are raw
bit vectors (``bitsN``) unless they are read as numbers: ``UInt()`` yields
``uintN``, ``SInt()`` and negation yield ``sintN``, comparisons yield ``bool``.

Types of *input* variables (read but never assigned) come from the table in
:mod:`~.known_types`, and may be overridden by the caller; types of runtime
function results come from the annotations in the Python runtime library
(see :mod:`~.runtime_types`).
"""

from __future__ import annotations

from typing import Mapping

from .ast_nodes import (
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
    StringLiteral,
    TupleLiteral,
    UnaryOp,
    WhenClause,
)
from .known_types import (
    BOOL,
    ArmType,
    TupleType,
    UnknownFunctionTypeError,
    UnknownTypeError,
    UnknownVariableTypeError,
    bits,
    coerce_types,
    get_type,
    join_types,
    sint,
    width_of,
)
from .runtime_types import runtime_return_types

_DEFAULT_WIDTH = 32

# Comparison and logical operators always produce a truth value.
_BOOL_OPS = frozenset({"==", "!=", "<", ">", "<=", ">=", "||", "&&"})

# Bitwise operators yield raw bits, as wide as their widest operand.
_BITWISE_OPS = frozenset({"EOR", "OR", "AND", "XOR"})

# Array accesses that read a number of bytes given by their second argument.
_MEMORY_ACCESSORS = frozenset({"MemA", "MemU"})

# Functions whose result width is given by one of their arguments.
_WIDTH_FROM_ARG: dict[str, int] = {
    "SignExtend": 1,
    "ZeroExtend": 1,
    "Zeros": 0,
    "Ones": 0,
    "VFPExpandImm": 1,
}


class TypeInferencer:
    """Infers ARM types of pseudocode expressions and variables.

    Args:
        input_types: Types for input variables, overriding the built-in table.
            Values may be :class:`~.known_types.ArmType` instances or their
            string spelling (``"bits3"``, ``"bool"``, …).
    """

    def __init__(self, input_types: Mapping[str, str | ArmType] | None = None) -> None:
        self._overrides: dict[str, ArmType] = coerce_types(input_types)
        self._env: dict[str, ArmType] = {}

    @property
    def variable_types(self) -> Mapping[str, ArmType]:
        """Types of the variables defined by the most recently inferred program."""
        return self._env

    # --- Program level ---

    def infer(self, program: Program) -> dict[str, ArmType]:
        """Infer the types of every variable *program* defines.

        Variables whose type cannot be determined (because they derive from an
        input of unknown type) are left out of the result.

        Returns:
            A mapping of variable name → inferred type.
        """
        env: dict[str, ArmType] = {}
        self._visit_statements(program.statements, env)
        self._env = env
        return dict(env)

    def try_type_of(self, expr: Expression) -> ArmType | None:
        """Return the type of *expr*, or ``None`` when it cannot be determined."""
        try:
            return self._type_of(expr, self._env)
        except UnknownTypeError:
            return None

    def type_of(self, expr: Expression) -> ArmType:
        """Return the type of *expr* in the most recently inferred program.

        Raises:
            UnknownTypeError: if the type cannot be determined.
        """
        return self._type_of(expr, self._env)

    def width_of_expr(self, expr: Expression) -> int:
        """Return the bit width of *expr*.

        Raises:
            UnknownTypeError: if the width cannot be determined.
        """
        return width_of(self.type_of(expr), _describe(expr))

    def lookup(self, name: str) -> ArmType:
        """Return the type of variable *name* (override, inferred, or known)."""
        return self._lookup(name, self._env)

    # --- Statements ---

    def _visit_statements(
        self, statements: list[Statement], env: dict[str, ArmType]
    ) -> None:
        for stmt in statements:
            self._visit_statement(stmt, env)

    def _visit_statement(self, stmt: Statement, env: dict[str, ArmType]) -> None:
        match stmt:
            case Assignment():
                if isinstance(stmt.target, str):
                    self._define(env, stmt.target, self._try_type_of(stmt.value, env))
            case DestructureAssignment():
                self._visit_destructure(stmt, env)
            case ForLoop():
                self._define(env, stmt.variable, self._loop_variable_type(stmt, env))
                self._visit_statements(stmt.body, env)
            case IfThen():
                branches = [self._branch(stmt.then_body, env)]
                if stmt.else_body:
                    branches.append(self._branch(stmt.else_body, env))
                self._merge(env, branches)
            case CaseOf():
                branches = [self._branch(clause.body, env) for clause in stmt.clauses]
                if stmt.else_body:
                    branches.append(self._branch(stmt.else_body, env))
                self._merge(env, branches)
            case WhenClause():
                self._merge(env, [self._branch(stmt.body, env)])

    def _visit_destructure(
        self, stmt: DestructureAssignment, env: dict[str, ArmType]
    ) -> None:
        value_type = self._try_type_of(stmt.value, env)
        elements: tuple[ArmType | None, ...]
        if isinstance(value_type, TupleType):
            elements = value_type.elements
        else:
            elements = (None,) * len(stmt.targets)
        for target, element in zip(stmt.targets, elements):
            if target is not None:
                self._define(env, target, element)

    def _branch(
        self, body: list[Statement], env: dict[str, ArmType]
    ) -> dict[str, ArmType]:
        branch_env = dict(env)
        self._visit_statements(body, branch_env)
        return branch_env

    @staticmethod
    def _merge(env: dict[str, ArmType], branches: list[dict[str, ArmType]]) -> None:
        for branch_env in branches:
            for name, arm_type in branch_env.items():
                TypeInferencer._define(env, name, arm_type)

    @staticmethod
    def _define(env: dict[str, ArmType], name: str, arm_type: ArmType | None) -> None:
        if arm_type is None:
            return
        existing = env.get(name)
        env[name] = join_types(existing, arm_type) if existing else arm_type

    def _loop_variable_type(
        self, stmt: ForLoop, env: dict[str, ArmType]
    ) -> ArmType | None:
        start = self._try_type_of(stmt.start, env)
        end = self._try_type_of(stmt.end, env)
        if start is None or end is None:
            return start or end
        return join_types(start, end)

    def _try_type_of(self, expr: Expression, env: dict[str, ArmType]) -> ArmType | None:
        """Return the type of *expr*, or ``None`` when it cannot be determined."""
        try:
            return self._type_of(expr, env)
        except UnknownTypeError:
            return None

    # --- Expressions ---

    def _type_of(self, expr: Expression, env: dict[str, ArmType]) -> ArmType:
        match expr:
            case IntegerLiteral() | HexLiteral():
                return _literal_type(expr.value)
            case BitLiteral():
                return bits(1)
            case BitStringLiteral():
                return bits(len(expr.value))
            case Identifier():
                return self._lookup(expr.name, env)
            case FieldAccess():
                return self._lookup(f"{expr.base}.{expr.field}", env)
            case RegisterAccess():
                return bits(_DEFAULT_WIDTH)
            case BitIndex():
                return bits(1)
            case BitRange():
                return self._bit_range_type(expr, env)
            case ArrayAccess():
                return self._array_access_type(expr, env)
            case FunctionCall():
                return self._function_type(expr, env)
            case BinaryOp():
                return self._binary_op_type(expr, env)
            case UnaryOp():
                return self._unary_op_type(expr, env)
            case InExpr() | PatternMatch():
                return BOOL
            case IfExpr():
                return join_types(
                    self._type_of(expr.then_value, env),
                    self._type_of(expr.else_value, env),
                )
            case TupleLiteral():
                return TupleType(tuple(self._type_of(e, env) for e in expr.elements))
            case StringLiteral() | SetLiteral():
                raise UnknownTypeError(f"{_describe(expr)} has no value type.")
            case _:
                raise UnknownTypeError(f"No type rule for {type(expr).__name__}.")

    def _lookup(self, name: str, env: dict[str, ArmType]) -> ArmType:
        if name in self._overrides:
            return self._overrides[name]
        if name in env:
            return env[name]
        return get_type(name)

    def _bit_range_type(self, expr: BitRange, env: dict[str, ArmType]) -> ArmType:
        if isinstance(expr.high, IntegerLiteral) and isinstance(
            expr.low, IntegerLiteral
        ):
            return bits(expr.high.value - expr.low.value + 1)
        try:
            return bits(width_of(self._lookup(expr.name, env), expr.name))
        except UnknownTypeError:
            return bits(_DEFAULT_WIDTH)

    def _array_access_type(self, expr: ArrayAccess, env: dict[str, ArmType]) -> ArmType:
        # MemA[address, size] / MemU[address, size] read `size` bytes.
        if expr.name in _MEMORY_ACCESSORS and len(expr.args) == 2:
            size = expr.args[1]
            if isinstance(size, IntegerLiteral):
                return bits(size.value * 8)
        return bits(_DEFAULT_WIDTH)

    def _function_type(self, expr: FunctionCall, env: dict[str, ArmType]) -> ArmType:
        arg_index = _WIDTH_FROM_ARG.get(expr.name)
        if arg_index is not None and len(expr.args) > arg_index:
            width_arg = expr.args[arg_index]
            if isinstance(width_arg, IntegerLiteral):
                return bits(width_arg.value)
            return bits(_DEFAULT_WIDTH)
        if expr.name == "Replicate" and len(expr.args) == 2:
            count = expr.args[1]
            if isinstance(count, IntegerLiteral):
                element = self._type_of(expr.args[0], env)
                width = width_of(element, _describe(expr.args[0]))
                return bits(width * count.value)
        return_type = runtime_return_types().get(expr.name)
        if return_type is None:
            raise UnknownFunctionTypeError(expr.name)
        return return_type

    def _binary_op_type(self, expr: BinaryOp, env: dict[str, ArmType]) -> ArmType:
        if expr.op in _BOOL_OPS:
            return BOOL
        left = self._type_of(expr.left, env)
        right = self._type_of(expr.right, env)
        left_width = width_of(left, _describe(expr.left))
        right_width = width_of(right, _describe(expr.right))
        if expr.op == ":":
            return bits(left_width + right_width)
        if expr.op in _BITWISE_OPS:
            return bits(max(left_width, right_width))
        # Arithmetic keeps the widest operand and the most specific kind.
        return join_types(left, right)

    def _unary_op_type(self, expr: UnaryOp, env: dict[str, ArmType]) -> ArmType:
        if expr.op == "!":
            return BOOL
        operand = self._type_of(expr.operand, env)
        if expr.op in ("NOT", "~"):
            return bits(width_of(operand, _describe(expr.operand)))
        if expr.op == "-":
            return sint(width_of(operand, _describe(expr.operand)))
        return operand


def _literal_type(value: int) -> ArmType:
    """Return the narrowest type that can hold the literal *value*."""
    if value < 0:
        return sint(_DEFAULT_WIDTH)
    return bits(max(1, value.bit_length()))


def _describe(expr: Expression) -> str:
    """Return a short human-readable description of *expr* for error messages."""
    match expr:
        case Identifier():
            return f"'{expr.name}'"
        case FieldAccess():
            return f"'{expr.base}.{expr.field}'"
        case FunctionCall():
            return f"'{expr.name}()'"
        case BitIndex() | BitRange():
            return f"'{expr.name}'"
        case _:
            return type(expr).__name__


def infer_types(
    program: Program, input_types: Mapping[str, str | ArmType] | None = None
) -> dict[str, ArmType]:
    """Return the types of every variable in scope for *program*.

    Variables the block assigns are type-inferred.  Entries from *input_types*
    are also included; on names that appear in both, the inferred type wins
    (an assignment may widen or retype the value).

    Args:
        program: A parsed pseudocode program.
        input_types: Types for input variables, overriding the known table.

    Returns:
        A mapping of variable name → type.
    """
    inferencer = TypeInferencer(input_types)
    result = inferencer.infer(program)
    if input_types:
        coerced = coerce_types(input_types)
        for name, arm_type in coerced.items():
            if name not in result:
                result[name] = arm_type
    from .analysis._collect import _collect_input_variables  # noqa: PLC0415

    for name in _collect_input_variables(program):
        if name not in result:
            try:
                result[name] = inferencer.lookup(name)
            except UnknownVariableTypeError:
                pass
    return result


def extract_variable_types(
    program: Program,
    input_types: Mapping[str, str | ArmType] | None = None,
) -> dict[str, dict[str, str | None]]:
    """Return the inferred variable types.

    Returns a dict with ``"inputs"`` and ``"outputs"`` maps of
    variable name → type (``None`` when unknown).

    Input types come from the known-types table (or *input_types*);
    output types are inferred from the code.
    """
    from .analysis._collect import (  # noqa: PLC0415
        _collect_definitions,
        _collect_input_variables,
    )

    inferencer = TypeInferencer(input_types)
    defined = inferencer.infer(program)

    inputs: dict[str, str | None] = {}
    for name in _collect_input_variables(program):
        try:
            inputs[name] = str(inferencer.lookup(name))
        except UnknownVariableTypeError:
            inputs[name] = None
    if input_types:
        coerced = coerce_types(input_types)
        for name, arm_type in coerced.items():
            if name not in inputs:
                inputs[name] = str(arm_type)

    outputs: dict[str, str | None] = {}
    for name in _collect_definitions(program):
        out_type: ArmType | None = defined.get(name)
        if out_type is None:
            if name.startswith("R[") and name.endswith("]"):
                out_type = bits(32)
            else:
                try:
                    out_type = inferencer.lookup(name)
                except UnknownVariableTypeError:
                    out_type = None
        outputs[name] = str(out_type) if out_type is not None else None

    return {"inputs": inputs, "outputs": outputs}
