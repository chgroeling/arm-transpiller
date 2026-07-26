from __future__ import annotations

from pathlib import Path

import pytest

from arm_transpiller.known_types import (
    BOOL,
    ScalarType,
    TupleType,
    TypeSyntaxError,
    UnknownFunctionTypeError,
    UnknownTypeError,
    UnknownVariableTypeError,
    bits,
    get_type,
    join_types,
    parse_type,
    sint,
    uint,
    width_of,
)
from arm_transpiller.parser import parse
from arm_transpiller.runtime_types import (
    c_runtime_return_types,
    read_c_runtime,
    runtime_return_types,
)
from arm_transpiller.type_inference import (
    TypeInferencer,
    extract_variable_types,
    infer_types,
)

FIXTURES = Path(__file__).parent / "fixtures"


def type_of(source: str, expr_index: int = 0, **kwargs: object) -> str:
    """Return the inferred type of the value assigned by statement *expr_index*."""
    program = parse(source)
    inferencer = TypeInferencer(kwargs.get("input_types"))  # type: ignore[arg-type]
    inferencer.infer(program)
    stmt = program.statements[expr_index]
    return str(inferencer.type_of(stmt.value))  # type: ignore[attr-defined]


# --- Type model: parsing and formatting ---


def test_parse_bits_type() -> None:
    assert parse_type("bits4") == bits(4)


def test_parse_uint_type() -> None:
    assert parse_type("uint4") == uint(4)


def test_parse_sint_type() -> None:
    assert parse_type("sint32") == sint(32)


def test_parse_bool_type() -> None:
    assert parse_type("bool") == BOOL


def test_parse_tuple_type() -> None:
    assert parse_type("tuple[uint32, uint1]") == TupleType((uint(32), uint(1)))


def test_parse_nested_tuple_type() -> None:
    assert parse_type("tuple[uint8, tuple[bool, sint32]]") == TupleType(
        (uint(8), TupleType((BOOL, sint(32))))
    )


def test_parse_type_ignores_surrounding_whitespace() -> None:
    assert parse_type("  uint12  ") == uint(12)


@pytest.mark.parametrize(
    "text", ["int", "uint", "uint0", "bits", "bitfield4", "float32", "tuple[]", ""]
)
def test_parse_type_rejects_invalid_spelling(text: str) -> None:
    with pytest.raises(TypeSyntaxError):
        parse_type(text)


@pytest.mark.parametrize(
    "text", ["bits4", "uint4", "sint32", "bool", "tuple[bits32, bits1]"]
)
def test_type_str_round_trips(text: str) -> None:
    assert str(parse_type(text)) == text


def test_scalar_type_carries_width() -> None:
    assert uint(5).width == 5
    assert uint(5).kind == "uint"
    assert BOOL.width == 1


def test_width_of_tuple_raises() -> None:
    with pytest.raises(UnknownTypeError):
        width_of(TupleType((uint(32), uint(1))))


# --- Type model: joining ---


def test_join_identical_types() -> None:
    assert join_types(uint(8), uint(8)) == uint(8)


def test_join_widens_to_wider_operand() -> None:
    assert join_types(uint(8), uint(32)) == uint(32)


def test_join_signed_wins_over_unsigned() -> None:
    assert join_types(uint(8), sint(32)) == sint(32)


def test_join_bool_with_bits_gives_bits() -> None:
    assert join_types(BOOL, bits(4)) == bits(4)


def test_join_bits_with_uint_keeps_the_interpretation() -> None:
    assert join_types(bits(4), uint(32)) == uint(32)


def test_join_tuples_elementwise() -> None:
    joined = join_types(TupleType((bits(8), BOOL)), TupleType((bits(32), BOOL)))
    assert joined == TupleType((bits(32), BOOL))


# --- Known types table ---


def test_known_type_of_register_field() -> None:
    assert get_type("Rd") == bits(4)


def test_known_type_of_imm_pattern() -> None:
    assert get_type("imm12") == bits(12)


def test_known_type_of_boolean_constant() -> None:
    assert get_type("TRUE") == BOOL


def test_known_type_unknown_name_raises() -> None:
    with pytest.raises(UnknownVariableTypeError, match="Wibble"):
        get_type("Wibble")


def test_known_type_override_wins() -> None:
    assert get_type("Rd", {"Rd": bits(3)}) == bits(3)


def test_known_type_override_supplies_unknown_name() -> None:
    assert get_type("Wibble", {"Wibble": BOOL}) == BOOL


def test_get_bit_width_from_type() -> None:
    assert width_of(get_type("registers"), "registers") == 16


# --- Runtime function return types (annotations in armruntime.py.template) ---


def test_runtime_return_type_of_uint_is_unsigned() -> None:
    assert runtime_return_types().get("UInt") == uint(32)


def test_runtime_return_type_of_sint_is_signed() -> None:
    assert runtime_return_types().get("SInt") == sint(32)


def test_runtime_return_type_of_other_functions_is_a_bits() -> None:
    assert runtime_return_types().get("ThumbExpandImm") == bits(32)


def test_runtime_return_type_bool() -> None:
    assert runtime_return_types().get("IsZeroBit") == BOOL


def test_runtime_return_type_of_sign_extend_is_a_bits() -> None:
    assert type_of("x = SignExtend(imm8, 32);") == "bits32"


def test_runtime_return_type_tuple() -> None:
    assert runtime_return_types().get("Shift_C") == TupleType((bits(32), bits(1)))


def test_runtime_return_type_of_procedure_is_none() -> None:
    assert runtime_return_types().get("LoadWritePC") is None


def test_runtime_return_type_of_unknown_function_is_none() -> None:
    assert runtime_return_types().get("FancyDecode") is None


def test_runtime_return_types_cover_the_builtins() -> None:
    annotated = runtime_return_types()
    for name in ("UInt", "ThumbExpandImm", "ThumbExpandImm_C", "DecodeImmShift"):
        assert name in annotated


# --- Expression inference ---


def test_infer_integer_literal_uses_minimal_width() -> None:
    assert type_of("x = 5;") == "bits3"


def test_infer_hex_literal() -> None:
    assert type_of("x = 0xFF;") == "bits8"


def test_infer_bit_string_literal_width() -> None:
    assert type_of("x = '0101';") == "bits4"


def test_infer_identifier_from_known_table() -> None:
    assert type_of("x = Rd;") == "bits4"


def test_infer_concat_adds_widths() -> None:
    assert type_of("x = i:imm3:imm8;") == "bits12"


def test_infer_bitwise_keeps_widest_operand() -> None:
    assert type_of("x = imm8 OR imm3;") == "bits8"


def test_infer_comparison_is_bool() -> None:
    assert type_of("x = (S == '1');") == "bool"


def test_infer_logical_and_is_bool() -> None:
    assert type_of("x = (S == '1') && (i == '0');") == "bool"


def test_infer_negation_is_bool() -> None:
    assert type_of("x = !(S == '1');") == "bool"


def test_infer_not_keeps_operand_width() -> None:
    assert type_of("x = NOT(imm8);") == "bits8"


def test_infer_bit_index_is_one_bit() -> None:
    assert type_of("x = registers<3>;") == "bits1"


def test_infer_bit_range_width() -> None:
    assert type_of("x = registers<7:4>;") == "bits4"


def test_infer_register_access_is_32_bit() -> None:
    assert type_of("x = R[3];") == "bits32"


def test_infer_memory_access_width_from_size() -> None:
    assert type_of("x = MemA[SP,2];") == "bits16"


def test_infer_field_access_of_apsr() -> None:
    assert type_of("x = APSR.C;") == "bits1"


def test_infer_function_call_from_annotation() -> None:
    assert type_of("x = ThumbExpandImm(imm12);") == "bits32"


def test_infer_uint_call_is_unsigned() -> None:
    assert type_of("x = UInt(Rd);") == "uint32"


def test_infer_sint_call_is_signed() -> None:
    assert type_of("x = SInt(Rd);") == "sint32"


def test_infer_concat_of_uint_call_is_a_bits() -> None:
    assert type_of("x = UInt(Rd):imm3;") == "bits35"


def test_infer_sign_extend_uses_target_width() -> None:
    assert type_of("x = SignExtend(imm8, 24);") == "bits24"


def test_infer_zero_extend_uses_target_width() -> None:
    assert type_of("x = ZeroExtend(imm8, 16);") == "bits16"


def test_infer_zeros_uses_argument_width() -> None:
    assert type_of("x = Zeros(12);") == "bits12"


def test_infer_replicate_multiplies_width() -> None:
    assert type_of("x = Replicate('01', 4);") == "bits8"


def test_infer_vfp_expand_imm_32_returns_bits32() -> None:
    assert type_of("x = VFPExpandImm(imm8, 32);") == "bits32"


def test_infer_vfp_expand_imm_64_returns_bits64() -> None:
    assert type_of("x = VFPExpandImm(imm8, 64);") == "bits64"


def test_infer_vfp_expand_imm_variable_n_falls_back_to_annotation() -> None:
    assert (
        type_of("x = VFPExpandImm(imm8, n);", input_types={"n": bits(16)}) == "bits32"
    )


def test_infer_if_expression_joins_branches() -> None:
    assert type_of("x = if S == '1' then Rd else imm8;") == "bits8"


def test_infer_in_expression_is_bool() -> None:
    assert type_of("x = Rd IN {13,15};") == "bool"


def test_infer_tuple_literal() -> None:
    assert type_of("(a, b) = (Rd, imm8);", 0) == "tuple[bits4, bits8]"


def test_infer_unary_minus_is_signed() -> None:
    assert type_of("x = -imm8;") == "sint8"


# --- Variable inference ---


def test_infer_defined_variable_types() -> None:
    types = infer_types(parse("d = UInt(Rd); setflags = (S == '1');"))
    assert str(types["d"]) == "uint32"
    assert str(types["setflags"]) == "bool"


def test_infer_uses_previously_defined_variable() -> None:
    types = infer_types(parse("a = i:imm3; b = a:imm8;"))
    assert str(types["b"]) == "bits12"


def test_infer_destructuring_from_tuple_return() -> None:
    types = infer_types(parse("(shift_t, shift_n) = DecodeImmShift(type, imm5);"))
    assert str(types["shift_t"]) == "bits3"
    assert str(types["shift_n"]) == "bits6"


def test_infer_destructuring_skips_wildcard() -> None:
    types = infer_types(parse("(-, carry) = Shift_C(R[m], shift_t, shift_n, APSR.C);"))
    assert str(types["carry"]) == "bits1"


def test_infer_destructuring_from_tuple_literal() -> None:
    types = infer_types(parse("(shift_t, shift_n) = (SRType_LSL, UInt(imm2));"))
    assert str(types["shift_t"]) == "bits3"
    assert str(types["shift_n"]) == "uint32"


def test_infer_for_loop_variable_from_bounds() -> None:
    types = infer_types(parse("for i = 0 to 14\n    x = i;"))
    assert str(types["i"]) == "bits4"


def test_infer_joins_types_across_branches() -> None:
    source = "if S == '1' then\n    x = imm3;\nelse\n    x = imm8;"
    assert str(infer_types(parse(source))["x"]) == "bits8"


def test_infer_joins_types_across_case_clauses() -> None:
    source = "case type of\n  when '00'\n    x = imm3;\n  when '01'\n    x = imm12;"
    assert str(infer_types(parse(source))["x"]) == "bits12"


def test_infer_reassignment_widens() -> None:
    assert str(infer_types(parse("x = imm3; x = imm12;"))["x"]) == "bits12"


def test_infer_omits_variables_of_unknown_type() -> None:
    types = infer_types(parse("d = UInt(Rd); x = Wibble;"))
    assert "d" in types
    assert "x" not in types


def test_infer_input_types_override_known_table() -> None:
    types = infer_types(parse("x = Rd:imm3;"), {"Rd": "bits2"})
    assert str(types["x"]) == "bits5"


def test_infer_input_types_supply_unknown_name() -> None:
    types = infer_types(parse("x = Wibble:imm3;"), {"Wibble": "bits7"})
    assert str(types["x"]) == "bits10"


def test_infer_input_types_accept_type_objects() -> None:
    types = infer_types(parse("x = Wibble;"), {"Wibble": ScalarType("sint", 16)})
    assert str(types["x"]) == "sint16"


# --- infer_types now includes input_types in the result ---


def test_infer_includes_input_types_in_empty_block() -> None:
    types = infer_types(
        parse("// No additional decoding required\n"), {"option": "bits4"}
    )
    assert str(types["option"]) == "bits4"


def test_infer_includes_input_types_alongside_assigned_vars() -> None:
    types = infer_types(parse("d = UInt(Rd);"), {"imm8": "bits8"})
    assert str(types["d"]) == "uint32"
    assert str(types["imm8"]) == "bits8"


def test_infer_inference_wins_over_input_type_on_conflict() -> None:
    types = infer_types(parse("x = imm12;"), {"x": "bits4", "imm12": "bits12"})
    assert str(types["x"]) == "bits12"


def test_infer_input_type_assigned_wider_value_reports_inferred_type() -> None:
    types = infer_types(parse("x = imm12;"), {"x": "bits4"})
    assert str(types["x"]) == "bits12"


def test_infer_input_types_none_is_unchanged() -> None:
    types = infer_types(parse("d = UInt(Rd);"))
    assert "d" in types
    assert str(types["Rd"]) == "bits4"


def test_infer_input_types_empty_is_unchanged() -> None:
    types = infer_types(parse("d = UInt(Rd);"), {})
    assert "d" in types
    assert str(types["Rd"]) == "bits4"


def test_infer_input_types_accept_arm_type_objects_and_includes_them() -> None:
    types = infer_types(
        parse("d = UInt(Rd);"),
        {"option": ScalarType("bits", 4), "Rd": ScalarType("bits", 3)},
    )
    assert str(types["option"]) == "bits4"
    assert str(types["d"]) == "uint32"


def test_extract_variable_types_includes_unreferenced_inputs() -> None:
    result = extract_variable_types(
        parse("// No additional decoding required\n"), {"option": "bits4"}
    )
    assert result == {"inputs": {"option": "bits4"}, "outputs": {}}


def test_extract_variable_types_includes_inputs_and_inferred() -> None:
    result = extract_variable_types(parse("d = UInt(Rd);"), {"imm8": "bits8"})
    assert result["inputs"] == {"Rd": "bits4", "imm8": "bits8"}
    assert result["outputs"] == {"d": "uint32"}


def test_infer_unknown_variable_raises_on_direct_query() -> None:
    inferencer = TypeInferencer()
    program = parse("x = Wibble;")
    inferencer.infer(program)
    with pytest.raises(UnknownVariableTypeError, match="Wibble"):
        inferencer.type_of(program.statements[0].value)  # type: ignore[attr-defined]


def test_infer_unknown_function_raises_on_direct_query() -> None:
    inferencer = TypeInferencer()
    program = parse("x = FancyDecode(Rd);")
    inferencer.infer(program)
    with pytest.raises(UnknownFunctionTypeError, match="FancyDecode"):
        inferencer.type_of(program.statements[0].value)  # type: ignore[attr-defined]


# --- Fixture-based: whole decoders ---


def test_infer_types_of_adc_immediate_decoder() -> None:
    program = parse((FIXTURES / "adc_immediate_decoder.pseudo").read_text())
    types = {name: str(t) for name, t in infer_types(program).items()}
    assert types == {
        "Rd": "bits4",
        "Rn": "bits4",
        "S": "bits1",
        "d": "uint32",
        "i": "bits1",
        "imm3": "bits3",
        "imm32": "bits32",
        "imm8": "bits8",
        "n": "uint32",
        "setflags": "bool",
    }


def test_infer_types_of_bl_decoder() -> None:
    program = parse((FIXTURES / "bl_decoder.pseudo").read_text())
    types = {name: str(t) for name, t in infer_types(program).items()}
    assert types == {
        "I1": "bits1",
        "I2": "bits1",
        "J1": "bits1",
        "J2": "bits1",
        "S": "bits1",
        "imm10": "bits10",
        "imm11": "bits11",
        "imm32": "bits32",
    }


def test_infer_types_of_vsel_decoder() -> None:
    program = parse((FIXTURES / "vsel_t1_decoder.pseudo").read_text())
    types = {name: str(t) for name, t in infer_types(program).items()}
    assert types["dp_operation"] == "bool"
    assert types["cond"] == "bits4"
    assert types["d"] == "uint32"


def test_infer_types_of_vnmla_t1_decoder() -> None:
    program = parse((FIXTURES / "vnmla_t1_decoder.pseudo").read_text())
    types = {name: str(t) for name, t in infer_types(program).items()}
    assert types["type"] == "bits2"
    assert types["dp_operation"] == "bool"
    assert types["d"] == "uint32"
    assert types["n"] == "uint32"
    assert types["m"] == "uint32"


def test_infer_types_of_vldm_t1_decoder() -> None:
    program = parse((FIXTURES / "vldm_t1_decoder.pseudo").read_text())
    types = {name: str(t) for name, t in infer_types(program).items()}
    assert types["single_regs"] == "bool"
    assert types["add"] == "bool"
    assert types["d"] == "uint32"
    assert types["regs"] == "uint32"


def test_infer_types_of_vrintz_t1_decoder() -> None:
    program = parse((FIXTURES / "vrintz_t1_decoder.pseudo").read_text())
    types = {name: str(t) for name, t in infer_types(program).items()}
    assert types["dp_operation"] == "bool"
    assert types["rmode"] == "bits2"
    assert types["d"] == "uint32"
    assert types["m"] == "uint32"


def test_infer_types_of_mvn_register_op() -> None:
    program = parse((FIXTURES / "mvn_register_op.pseudo").read_text())
    types = {name: str(t) for name, t in infer_types(program).items()}
    assert types["shifted"] == "bits32"
    assert types["carry"] == "bits1"
    assert types["result"] == "bits32"


# --- JSON extraction ---


def test_extract_variable_types_shape() -> None:
    result = extract_variable_types(parse("d = UInt(Rd);"))
    assert result == {"inputs": {"Rd": "bits4"}, "outputs": {"d": "uint32"}}


def test_extract_variable_types_accepts_program() -> None:
    program = parse("d = UInt(Rd);")
    result = extract_variable_types(program)
    assert result["outputs"] == {"d": "uint32"}


def test_extract_variable_types_reports_unknown_as_null() -> None:
    result = extract_variable_types(parse("x = Wibble;"))
    assert result["inputs"] == {"Wibble": None}
    assert result["outputs"] == {"x": None}


def test_extract_variable_types_applies_overrides() -> None:
    result = extract_variable_types(parse("x = Wibble;"), {"Wibble": "bits7"})
    assert result == {"inputs": {"Wibble": "bits7"}, "outputs": {"x": "bits7"}}


def test_extract_variable_types_types_architectural_targets() -> None:
    result = extract_variable_types(parse("R[d] = imm8; APSR.N = '1';"))
    assert result["outputs"]["R[d]"] == "bits32"
    assert result["outputs"]["APSR.N"] == "bits1"


def test_infer_non_memory_array_access_defaults_to_32_bit() -> None:
    assert type_of("x = Table[Rd,2];") == "bits32"


# --- C runtime declares the same types as the Python runtime ---


def test_c_runtime_uses_standard_types_directly() -> None:
    header = read_c_runtime()
    for alias in ("bits1", "bits3", "bits32", "uint32", "sint32"):
        assert f" {alias};" not in header, f"{alias} typedef should not exist"
    assert "uint32_t" in header
    assert "int32_t" in header


def test_c_and_python_runtimes_agree_on_functions() -> None:
    c_types = c_runtime_return_types()
    for name, arm_type in runtime_return_types().items():
        assert name in c_types, f"{name}() is missing from the C runtime"
        if isinstance(arm_type, TupleType):
            assert c_types[name] == "Tuple2Ret", (
                f"{name}() should return Tuple2Ret in C, got {c_types[name]}"
            )


def test_c_runtime_has_no_unannotated_value_functions() -> None:
    from arm_transpiller.type_inference import _WIDTH_FROM_ARG

    annotated = runtime_return_types()
    for name, return_type in c_runtime_return_types().items():
        if return_type == "void":
            continue
        if name in _WIDTH_FROM_ARG:
            continue
        assert name in annotated, f"{name}() returns a value in C but has no type entry"
