from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping

from ..ast_nodes import Expression, Program, Statement
from ..known_types import ArmType, ScalarType, UnknownTypeError
from ..type_inference import TypeInferencer

_DEFAULT_WIDTH = 32


class CodeGenerator(ABC):
    """Base class of the target code generators.

    Args:
        input_types: Types of the pseudocode's input variables, overriding the
            table in :mod:`~arm_transpiller.known_types`.  Values are
            :class:`~arm_transpiller.known_types.ArmType` instances or their
            string spelling (e.g. ``{"Rdn": "uint3"}``).
    """

    def __init__(self, input_types: Mapping[str, str | ArmType] | None = None) -> None:
        self._types = TypeInferencer(input_types)

    @abstractmethod
    def generate(self, program: Program) -> str: ...

    @abstractmethod
    def visit_statement(self, stmt: Statement, indent: int = 0) -> str: ...

    @abstractmethod
    def visit_expression(self, expr: Expression) -> str: ...

    @abstractmethod
    def type_annotation(self, arm_type: ArmType | None) -> str:
        """Return the target-language type that holds an ARM value of *arm_type*.

        ``None`` (type undetermined) must map to the language's general-purpose
        integer type.  ``TupleType`` has no natural single-value spelling;
        subclasses may raise ``NotImplementedError``.
        """

    @abstractmethod
    def zero_value(self, arm_type: ArmType | None) -> str:
        """Return the target-language literal for the zero of *arm_type*.

        Must be consistent with :meth:`type_annotation`: the returned
        literal must be a valid value of the returned type.
        """

    @property
    def variable_types(self) -> Mapping[str, ArmType]:
        """Types inferred for the variables of the last generated program."""
        return self._types.variable_types

    def _infer_types(self, program: Program) -> None:
        """Infer the types of *program*'s variables before generating code."""
        self._types.infer(program)

    def _get_expr_type(self, expr: Expression) -> ArmType:
        return self._types.type_of(expr)

    def _get_expr_width(self, expr: Expression) -> int:
        return self._types.width_of_expr(expr)

    def _get_bitwise_width(self, expr: Expression) -> int:
        """Return the width to mask a bitwise result with, defaulting to 32."""
        try:
            return self._get_expr_width(expr)
        except UnknownTypeError:
            return _DEFAULT_WIDTH

    def _is_signed(self, expr: Expression) -> bool:
        """Return True if *expr* holds a signed value (``sintN``).

        Values are unsigned unless the pseudocode asked for a signed reading,
        so an undeterminable type answers False.
        """
        try:
            arm_type = self._get_expr_type(expr)
        except UnknownTypeError:
            return False
        return isinstance(arm_type, ScalarType) and arm_type.kind == "sint"
