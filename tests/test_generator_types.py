"""Tests for type_annotation() and zero_value() on both code generators."""

from __future__ import annotations

import pytest

from arm_transpiller.generators.c_generator import CGenerator
from arm_transpiller.generators.python_generator import PythonGenerator
from arm_transpiller.known_types import BOOL, ScalarType, TupleType, bits, sint, uint

_MK_GENERATORS = [PythonGenerator, CGenerator]


# =============================================================================
# None (undetermined type)
# =============================================================================


@pytest.mark.parametrize("make_gen", _MK_GENERATORS)
def test_none_type_annotation_does_not_raise(make_gen: type) -> None:
    make_gen().type_annotation(None)


@pytest.mark.parametrize("make_gen", _MK_GENERATORS)
def test_none_zero_value_does_not_raise(make_gen: type) -> None:
    make_gen().zero_value(None)


# =============================================================================
# Callable before generate()
# =============================================================================


@pytest.mark.parametrize("make_gen", _MK_GENERATORS)
def test_callable_before_generate_ran(make_gen: type) -> None:
    gen = make_gen()
    assert isinstance(gen.type_annotation(bits(4)), str)
    assert isinstance(gen.zero_value(bits(4)), str)


# =============================================================================
# Python backend — matches decoder-forge's current output exactly
# =============================================================================


def test_python_bool_annotation() -> None:
    assert PythonGenerator().type_annotation(BOOL) == "bool"


def test_python_bool_zero() -> None:
    assert PythonGenerator().zero_value(BOOL) == "False"


def test_python_bits_annotation() -> None:
    assert PythonGenerator().type_annotation(bits(4)) == "int"


def test_python_bits_zero() -> None:
    assert PythonGenerator().zero_value(bits(4)) == "0"


def test_python_uint_annotation() -> None:
    assert PythonGenerator().type_annotation(uint(8)) == "int"


def test_python_uint_zero() -> None:
    assert PythonGenerator().zero_value(uint(8)) == "0"


def test_python_sint_annotation() -> None:
    assert PythonGenerator().type_annotation(sint(32)) == "int"


def test_python_sint_zero() -> None:
    assert PythonGenerator().zero_value(sint(32)) == "0"


def test_python_none_annotation() -> None:
    assert PythonGenerator().type_annotation(None) == "int"


def test_python_none_zero() -> None:
    assert PythonGenerator().zero_value(None) == "0"


# =============================================================================
# C backend
# =============================================================================


def test_c_bool_annotation() -> None:
    assert CGenerator().type_annotation(BOOL) == "bool"


def test_c_bool_zero() -> None:
    assert CGenerator().zero_value(BOOL) == "false"


def test_c_bits_annotation() -> None:
    assert CGenerator().type_annotation(bits(4)) == "uint32_t"


def test_c_bits_zero() -> None:
    assert CGenerator().zero_value(bits(4)) == "0"


def test_c_uint_annotation() -> None:
    assert CGenerator().type_annotation(uint(8)) == "uint32_t"


def test_c_uint_zero() -> None:
    assert CGenerator().zero_value(uint(8)) == "0"


def test_c_sint_annotation() -> None:
    assert CGenerator().type_annotation(sint(32)) == "int32_t"


def test_c_sint_zero() -> None:
    assert CGenerator().zero_value(sint(32)) == "0"


def test_c_none_annotation() -> None:
    assert CGenerator().type_annotation(None) == "uint32_t"


def test_c_none_zero() -> None:
    assert CGenerator().zero_value(None) == "0"


# =============================================================================
# Consistency: annotation and zero agree
# =============================================================================


@pytest.mark.parametrize(
    "arm_type",
    [None, BOOL, bits(4), uint(8), sint(32)],
)
@pytest.mark.parametrize("make_gen", _MK_GENERATORS)
def test_type_annotation_and_zero_value_are_consistent(
    make_gen: type, arm_type: ScalarType | None
) -> None:
    gen = make_gen()
    ann = gen.type_annotation(arm_type)
    zero = gen.zero_value(arm_type)
    assert isinstance(ann, str)
    assert isinstance(zero, str)
    # The zero must be a valid literal of the annotated type in the target
    # language.  At minimum, they should not be empty and both output something
    # that could live in the target language:
    assert len(ann) > 0
    assert len(zero) > 0


# =============================================================================
# TupleType raises
# =============================================================================


@pytest.mark.parametrize("make_gen", _MK_GENERATORS)
def test_tuple_type_annotation_raises(make_gen: type) -> None:
    gen = make_gen()
    tup = TupleType((bits(32), BOOL))
    with pytest.raises(NotImplementedError):
        gen.type_annotation(tup)


@pytest.mark.parametrize("make_gen", _MK_GENERATORS)
def test_tuple_zero_value_raises(make_gen: type) -> None:
    gen = make_gen()
    tup = TupleType((bits(32), BOOL))
    with pytest.raises(NotImplementedError):
        gen.zero_value(tup)


# =============================================================================
# Every concrete subclass must implement both methods
# =============================================================================


def test_all_concrete_subclasses_implement_type_annotation() -> None:
    for cls in _MK_GENERATORS:
        gen = cls()
        assert gen.type_annotation is not type(gen).type_annotation
        gen.type_annotation(None)


def test_all_concrete_subclasses_implement_zero_value() -> None:
    for cls in _MK_GENERATORS:
        gen = cls()
        assert gen.zero_value is not type(gen).zero_value
        gen.zero_value(None)


# =============================================================================
# C-specific: bool zero is "false" (lowercase), not "False"
# =============================================================================


def test_c_bool_zero_is_lowercase_false() -> None:
    assert CGenerator().zero_value(BOOL) == "false"
