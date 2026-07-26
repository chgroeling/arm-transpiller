from __future__ import annotations

from pathlib import Path

from arm_transpiller.analysis._collect import _collect_definitions
from arm_transpiller.analysis.conditionally_assigned import (
    _conditionally_assigned_vars,
    _exhaustive,
    _pattern_values,
    extract_conditionally_assigned,
)
from arm_transpiller.ast_nodes import (
    BitStringLiteral,
    HexLiteral,
    IntegerLiteral,
    Range,
    WhenClause,
)
from arm_transpiller.known_types import bits, sint
from arm_transpiller.parser import parse

FIXTURES = Path(__file__).parent / "fixtures"


def _ca(source: str, **kwargs: object) -> list[str]:
    """Shortcut: parse *source*, return conditionally assigned variable names."""
    return _conditionally_assigned_vars(parse(source), kwargs.get("input_types"))  # type: ignore[arg-type]


def _extract_ca(source: str) -> list[str]:
    return extract_conditionally_assigned(parse(source))


# =============================================================================
# Fixture-based encoding tests (must produce the tabulated results)
# =============================================================================


def test_vmov_immediate_t1_conditionally_assigned() -> None:
    source = (FIXTURES / "vmov_immediate_t1_decoder.pseudo").read_text()
    result = _extract_ca(source)
    assert result == ["imm64", "imm32"]


def test_vcvt_t1_conditionally_assigned() -> None:
    source = (FIXTURES / "vcvt_t1_decoder.pseudo").read_text()
    result = _extract_ca(source)
    assert result == ["round_zero", "round_nearest"]


def test_vrinta_t1_not_conditionally_assigned() -> None:
    source = (FIXTURES / "vrinta_t1_decoder.pseudo").read_text()
    result = _extract_ca(source)
    assert result == []


def test_vrintz_t1_not_conditionally_assigned() -> None:
    source = (FIXTURES / "vrintz_t1_decoder.pseudo").read_text()
    result = _extract_ca(source)
    assert result == []


def test_vsel_t1_not_conditionally_assigned() -> None:
    source = (FIXTURES / "vsel_t1_decoder.pseudo").read_text()
    result = _extract_ca(source)
    assert result == []


# =============================================================================
# subset property: result is always subset of extract_output_variables
# =============================================================================


def test_result_is_subset_of_output_variables() -> None:
    source = (FIXTURES / "vmov_immediate_t1_decoder.pseudo").read_text()
    cond = set(extract_conditionally_assigned(parse(source)))
    all_outputs = set(_collect_definitions(parse(source)))
    assert cond <= all_outputs


# =============================================================================
# Synthetic cases
# =============================================================================


def test_if_without_else_reports_both_branch_assignments() -> None:
    result = _ca("if cond then\n    x = 1; y = 2;")
    assert result == ["x", "y"]


def test_if_with_else_reports_only_difference() -> None:
    result = _ca("if cond then\n    x = 1; y = 2;\nelse\n    x = 3;")
    assert result == ["y"]


def test_if_with_else_where_both_branches_fully_bind() -> None:
    result = _ca("if cond then\n    x = 1; y = 2;\nelse\n    x = 3; y = 4;")
    assert result == []


def test_nested_if_with_else_fully_binds() -> None:
    source = (
        "if a == '1' then\n"
        "    if b == '1' then\n"
        "        d = 1; m = 2;\n"
        "    else\n"
        "        d = 3; m = 4;\n"
        "else\n"
        "    d = 5; m = 6;"
    )
    assert _ca(source) == []


def test_exhaustive_case_not_reported() -> None:
    source = (
        "case RM\n"
        "    when '00'\n        rmode = '01'; away = TRUE;\n"
        "    when '01'\n        rmode = '00'; away = FALSE;\n"
        "    when '10'\n        rmode = '01'; away = FALSE;\n"
        "    when '11'\n        rmode = '10'; away = FALSE;"
    )
    assert _ca(source) == []


def test_non_exhaustive_case_without_else_reported() -> None:
    source = (
        "case RM\n"
        "    when '00'\n        rmode = '01'; away = TRUE;\n"
        "    when '01'\n        rmode = '00'; away = FALSE;\n"
        "    when '10'\n        rmode = '01'; away = FALSE;"
    )
    assert _ca(source) == ["rmode", "away"]


def test_non_exhaustive_case_with_else_that_assigns_reports_empty() -> None:
    source = (
        "case RM\n"
        "    when '00'\n        rmode = '01'; away = TRUE;\n"
        "    when '01'\n        rmode = '00'; away = FALSE;\n"
        "    rmode = '10'; away = FALSE;"
    )
    result = _ca(source)
    assert result == []


def test_case_with_else_that_does_not_assign_is_reported() -> None:
    source = (
        "case RM\n"
        "    when '00'\n        rmode = '01'; away = TRUE;\n"
        "    when '01'\n        rmode = '00'; away = FALSE;\n"
        "    rmode = '10';"
    )
    result = _ca(source)
    assert set(result) == {"away"}


def test_for_loop_body_assignment_reported() -> None:
    source = "for i = 0 to 14\n    x = i;"
    assert _ca(source) == ["i", "x"]


def test_branch_with_unpredictable_does_not_poison() -> None:
    source = "if cond then\n    d = UInt(Rd);\nelse\n    UNPREDICTABLE;"
    result = _ca(source)
    assert result == []


def test_destructure_with_wildcard() -> None:
    source = "(result, -) = Shift_C(Rm, shift_t, shift_n, APSR.C);"
    assert _ca(source) == []


def test_destructure_all_wildcards() -> None:
    source = "(-, -) = Shift_C(Rm, shift_t, shift_n, APSR.C);"
    assert _ca(source) == []


def test_assignment_to_non_str_target_does_not_bind_local() -> None:
    source = "R[d] = imm8; APSR.N = '1';"
    assert _ca(source) == []


def test_result_is_stable_order() -> None:
    for _ in range(5):
        result = _extract_ca("if cond then\n  a = 1; b = 2;\nelse\n  a = 3; c = 4;")
        assert result == ["b", "c"]


# =============================================================================
# JSON API
# =============================================================================


def test_json_api_accepts_string() -> None:
    result = extract_conditionally_assigned(
        parse("if cond then\n    x = 1;\nelse\n    y = 2;")
    )
    assert result == ["x", "y"]


def test_json_api_accepts_program() -> None:
    program = parse("if cond then\n    x = 1;\nelse\n    y = 2;")
    result = extract_conditionally_assigned(program)
    assert result == ["x", "y"]


def test_json_api_empty_block() -> None:
    result = extract_conditionally_assigned(parse("x = 1; y = 2;"))
    assert result == []


def test_json_api_with_input_types() -> None:
    result = extract_conditionally_assigned(parse("x = Wibble;"), {"Wibble": "bits7"})
    assert result == []


def test_conditionally_assigned_returns_list() -> None:
    result = extract_conditionally_assigned(parse("if c then x = 1; else y = 2;"))
    assert isinstance(result, list)
    assert result == ["x", "y"]


# =============================================================================
# Exhaustiveness checks
# =============================================================================


def test_exhaustive_empty_clauses() -> None:
    assert _exhaustive([], None) is False


def test_exhaustive_bit_string_literal_same_width_full_coverage() -> None:
    clauses = [
        WhenClause(BitStringLiteral("0"), []),
        WhenClause(BitStringLiteral("1"), []),
    ]
    assert _exhaustive(clauses, bits(1)) is True


def test_exhaustive_bit_string_literal_same_width_missing() -> None:
    clauses = [
        WhenClause(BitStringLiteral("0"), []),
    ]
    assert _exhaustive(clauses, bits(1)) is False


def test_exhaustive_non_bit_string_patterns() -> None:
    clauses = [
        WhenClause(IntegerLiteral(0), []),
        WhenClause(IntegerLiteral(1), []),
    ]
    assert _exhaustive(clauses, None) is False


def test_exhaustive_with_type_using_integer_patterns() -> None:
    clauses = [
        WhenClause(IntegerLiteral(0), []),
        WhenClause(IntegerLiteral(1), []),
    ]
    assert _exhaustive(clauses, bits(1)) is True


def test_exhaustive_with_type_using_hex_patterns() -> None:
    clauses = [
        WhenClause(HexLiteral(0x0), []),
        WhenClause(HexLiteral(0x1), []),
    ]
    assert _exhaustive(clauses, bits(1)) is True


def test_exhaustive_with_type_using_range_pattern() -> None:
    clauses = [
        WhenClause(Range(0, 3), []),
    ]
    assert _exhaustive(clauses, bits(2)) is True


def test_exhaustive_range_missing_values() -> None:
    clauses = [
        WhenClause(Range(0, 2), []),
    ]
    assert _exhaustive(clauses, bits(2)) is False


def test_exhaustive_mixed_pattern_types_with_type() -> None:
    clauses = [
        WhenClause(BitStringLiteral("00"), []),
        WhenClause(IntegerLiteral(1), []),
        WhenClause(IntegerLiteral(2), []),
        WhenClause(HexLiteral(0x3), []),
    ]
    assert _exhaustive(clauses, bits(2)) is True


def test_exhaustive_mixed_patterns_duplicate_values() -> None:
    clauses = [
        WhenClause(IntegerLiteral(0), []),
        WhenClause(BitStringLiteral("0"), []),
        WhenClause(HexLiteral(0x1), []),
    ]
    assert _exhaustive(clauses, bits(1)) is True


def test_exhaustive_without_type_falls_back_to_heuristic() -> None:
    clauses = [
        WhenClause(BitStringLiteral("00"), []),
        WhenClause(BitStringLiteral("01"), []),
        WhenClause(BitStringLiteral("10"), []),
        WhenClause(BitStringLiteral("11"), []),
    ]
    assert _exhaustive(clauses, None) is True


def test_exhaustive_heuristic_fails_on_mixed_widths() -> None:
    clauses = [
        WhenClause(BitStringLiteral("0"), []),
        WhenClause(BitStringLiteral("10"), []),
    ]
    assert _exhaustive(clauses, None) is False


# =============================================================================
# _pattern_values
# =============================================================================


def test_pattern_values_all_bit_strings() -> None:
    patterns = [BitStringLiteral("00"), BitStringLiteral("01"), BitStringLiteral("10")]
    result = _pattern_values(patterns)
    assert result == {0, 1, 2}


def test_pattern_values_all_integers() -> None:
    patterns = [IntegerLiteral(0), IntegerLiteral(5), IntegerLiteral(42)]
    result = _pattern_values(patterns)
    assert result == {0, 5, 42}


def test_pattern_values_all_hex() -> None:
    patterns = [HexLiteral(0xA), HexLiteral(0xB), HexLiteral(0xC)]
    result = _pattern_values(patterns)
    assert result == {10, 11, 12}


def test_pattern_values_range() -> None:
    patterns = [Range(0, 3)]
    result = _pattern_values(patterns)
    assert result == {0, 1, 2, 3}


def test_pattern_values_unknown_pattern_returns_none() -> None:
    from arm_transpiller.ast_nodes import Identifier

    patterns = [BitStringLiteral("0"), Identifier("x")]
    assert _pattern_values(patterns) is None


# =============================================================================
# Type-based exhaustiveness of a 1-bit selector (signed type too)
# =============================================================================


def test_exhaustive_with_sint_type() -> None:
    clauses = [
        WhenClause(IntegerLiteral(0), []),
        WhenClause(IntegerLiteral(1), []),
    ]
    assert _exhaustive(clauses, sint(1)) is True


def test_exhaustive_signed_type_missing_value() -> None:
    clauses = [
        WhenClause(IntegerLiteral(0), []),
    ]
    assert _exhaustive(clauses, sint(2)) is False
