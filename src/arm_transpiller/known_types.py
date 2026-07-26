"""ARM pseudocode value types and the table of known input-variable types.

A type carries both the interpretation and the bit width of a value:

``bitsN``
    Raw bit vector, ``N`` bits wide — ARM's ``bits(N)``.  This is the default:
    encoding fields, register and memory contents, concatenations and bitwise
    results are all bit vectors with no numeric interpretation.
``uintN``
    Unsigned integer, ``N`` bits wide.  Produced only by ``UInt()``.
``sintN``
    Signed (two's complement) integer, ``N`` bits wide.  Produced only by
    ``SInt()`` and by negation.
``bool``
    Truth value, 1 bit wide.
``tuple[T, ...]``
    Several values at once — what a pseudocode destructuring assignment
    such as ``(shift_t, shift_n) = DecodeImmShift(type, imm5)`` consumes.

The same spelling is used for annotations in ``armruntime.py.template``, for
``--input-types`` overrides on the command line, and for the JSON emitted by
``arm-transpiller types``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Mapping

Kind = Literal["bits", "uint", "sint", "bool"]

# How kinds combine where control flow merges: the most specific interpretation
# wins, so a signed operand makes the result signed.
_KIND_ORDER: dict[Kind, int] = {"bool": 0, "bits": 1, "uint": 2, "sint": 3}


class UnknownTypeError(Exception):
    """Raised when the type of an expression cannot be determined."""


class UnknownVariableTypeError(UnknownTypeError):
    """Raised when a variable name has no known type."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"Cannot determine the type of '{name}'. "
            f"Add it to known_types.py (exact match or imm<N> pattern) "
            f"or pass it as an input type override (e.g. {name}=bits4)."
        )
        self.name = name


class UnknownFunctionTypeError(UnknownTypeError):
    """Raised when a called function has no known return type."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"Cannot determine the return type of '{name}()'. "
            f"Annotate the function in armruntime/armruntime.py.template "
            f"with an ARM type (e.g. '-> bits32')."
        )
        self.name = name


class TypeSyntaxError(ValueError):
    """Raised when a string is not a valid ARM type."""

    def __init__(self, text: str) -> None:
        super().__init__(
            f"'{text}' is not a valid ARM type. Expected 'bool', "
            f"'bits<N>', 'uint<N>', 'sint<N>' or 'tuple[...]'."
        )
        self.text = text


# --- Type model ---


@dataclass(frozen=True)
class ArmType:
    """Base class of all ARM pseudocode value types."""


@dataclass(frozen=True)
class ScalarType(ArmType):
    """A single value of ``kind`` that is ``width`` bits wide."""

    kind: Kind
    width: int

    def __str__(self) -> str:
        return "bool" if self.kind == "bool" else f"{self.kind}{self.width}"

    def with_kind(self, kind: Kind) -> ScalarType:
        """Return the same width, reinterpreted as *kind*."""
        return ScalarType(kind=kind, width=self.width)


@dataclass(frozen=True)
class TupleType(ArmType):
    """Several values returned together (e.g. by ``Shift_C``)."""

    elements: tuple[ArmType, ...]

    def __str__(self) -> str:
        return f"tuple[{', '.join(str(e) for e in self.elements)}]"


def bits(width: int) -> ScalarType:
    """Return the raw bit vector type of *width* bits (ARM's ``bits(N)``)."""
    return ScalarType(kind="bits", width=width)


def uint(width: int) -> ScalarType:
    """Return the unsigned integer type of *width* bits."""
    return ScalarType(kind="uint", width=width)


def sint(width: int) -> ScalarType:
    """Return the signed integer type of *width* bits."""
    return ScalarType(kind="sint", width=width)


BOOL = ScalarType(kind="bool", width=1)


_SCALAR_RE = re.compile(r"^(bits|uint|sint)(\d+)$")
_TUPLE_RE = re.compile(r"^tuple\[(.*)\]$", re.DOTALL)


def _split_type_list(text: str) -> list[str]:
    """Split a comma-separated type list, ignoring commas inside brackets."""
    parts: list[str] = []
    depth = 0
    current = ""
    for char in text:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [p.strip() for p in parts]


def parse_type(text: str) -> ArmType:
    """Parse a type spelling such as ``bits4``, ``bool`` or ``tuple[uint32, bool]``.

    Raises:
        TypeSyntaxError: if *text* is not a valid ARM type.
    """
    stripped = text.strip()
    if stripped == "bool":
        return BOOL
    scalar = _SCALAR_RE.match(stripped)
    if scalar:
        width = int(scalar.group(2))
        if width < 1:
            raise TypeSyntaxError(text)
        kind: Kind = scalar.group(1)  # type: ignore[assignment]
        return ScalarType(kind=kind, width=width)
    tuple_match = _TUPLE_RE.match(stripped)
    if tuple_match:
        inner = tuple_match.group(1).strip()
        if not inner:
            raise TypeSyntaxError(text)
        return TupleType(tuple(parse_type(p) for p in _split_type_list(inner)))
    raise TypeSyntaxError(text)


def join_types(left: ArmType, right: ArmType) -> ArmType:
    """Return a type able to hold values of both *left* and *right*.

    Used where control flow merges (branches of an ``if``, clauses of a
    ``case``) and where a variable is assigned more than once.  Scalars widen
    to the wider operand and keep the most specific interpretation
    (``sint`` > ``uint`` > ``bits`` > ``bool``).
    """
    if left == right:
        return left
    if isinstance(left, ScalarType) and isinstance(right, ScalarType):
        kind = max(left.kind, right.kind, key=lambda k: _KIND_ORDER[k])
        return ScalarType(kind=kind, width=max(left.width, right.width))
    if (
        isinstance(left, TupleType)
        and isinstance(right, TupleType)
        and len(left.elements) == len(right.elements)
    ):
        return TupleType(
            tuple(join_types(a, b) for a, b in zip(left.elements, right.elements))
        )
    return right


def _coerce_type(value: str | ArmType) -> ArmType:
    """Return *value* as an :class:`ArmType`, parsing it when it is a string."""
    return value if isinstance(value, ArmType) else parse_type(value)


def coerce_types(types: Mapping[str, str | ArmType] | None) -> dict[str, ArmType]:
    """Return a name → :class:`ArmType` mapping from user-supplied overrides."""
    if not types:
        return {}
    return {name: _coerce_type(value) for name, value in types.items()}


# --- Known types of pseudocode input variables ---

_KNOWN_TYPES: dict[str, ArmType] = {
    # Encoding fields
    "S": bits(1),
    "s": bits(1),
    "D": bits(1),
    "M": bits(1),
    "N": bits(1),
    "P": bits(1),
    "U": bits(1),
    "W": bits(1),
    "sz": bits(1),
    "op": bits(1),
    "opc2": bits(3),
    "RM": bits(2),
    "i": bits(1),
    "J1": bits(1),
    "J2": bits(1),
    "I1": bits(1),
    "I2": bits(1),
    "Rd": bits(4),
    "Rn": bits(4),
    "Rm": bits(4),
    "Rs": bits(4),
    "Rt": bits(4),
    "Ra": bits(4),
    "Rdn": bits(4),
    "Vd": bits(4),
    "Vm": bits(4),
    "Vn": bits(4),
    "cc": bits(2),
    "cond": bits(4),
    "type": bits(2),
    "SYSm": bits(8),
    "imm4H": bits(4),
    "imm4L": bits(4),
    "registers": bits(16),
    "rotation": bits(4),
    # Architectural registers
    "SP": bits(32),
    "LR": bits(32),
    "PC": bits(32),
    "FPSCR": bits(32),
    # Common decoder variables (ARM uses these names with a fixed meaning)
    "setflags": BOOL,
    "index": BOOL,
    "add": BOOL,
    "wback": BOOL,
    "carry": bits(1),
    "carry_in": bits(1),
    "carry_out": bits(1),
    "shift_t": bits(3),
    "shift_n": bits(6),
    # Flags
    "APSR.N": bits(1),
    "APSR.Z": bits(1),
    "APSR.C": bits(1),
    "APSR.V": bits(1),
    "APSR.Q": bits(1),
    # Constants
    "TRUE": BOOL,
    "FALSE": BOOL,
    "SRType_None": bits(3),
    "SRType_LSL": bits(3),
    "SRType_LSR": bits(3),
    "SRType_ASR": bits(3),
    "SRType_ROR": bits(3),
    "SRType_RRX": bits(3),
    # VFP negate-multiply type
    "VFPNegMul_VNMLA": bits(2),
    "VFPNegMul_VNMLS": bits(2),
    "VFPNegMul_VNMUL": bits(2),
}

_IMM_RE = re.compile(r"^imm(\d+)$")


def get_type(name: str, overrides: Mapping[str, ArmType] | None = None) -> ArmType:
    """Return the known type of the variable *name*.

    Args:
        name: Variable name as written in the pseudocode (e.g. ``Rd``, ``imm8``).
        overrides: User-supplied types that take precedence over the table.

    Raises:
        UnknownVariableTypeError: if the name is neither overridden, listed in
            the table, nor of the form ``imm<N>``.
    """
    if overrides and name in overrides:
        return overrides[name]
    if name in _KNOWN_TYPES:
        return _KNOWN_TYPES[name]
    match = _IMM_RE.match(name)
    if match:
        return bits(int(match.group(1)))
    raise UnknownVariableTypeError(name)


def width_of(arm_type: ArmType, what: str = "value") -> int:
    """Return the bit width of *arm_type*.

    Raises:
        UnknownTypeError: if the type is a tuple, which has no single width.
    """
    if isinstance(arm_type, ScalarType):
        return arm_type.width
    raise UnknownTypeError(f"{what} has type '{arm_type}', which has no bit width.")
