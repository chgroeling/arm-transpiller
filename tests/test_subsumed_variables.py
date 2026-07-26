"""Tests for extract_subsumed_variables / subsumed-variable analysis."""

from __future__ import annotations

from pathlib import Path

from arm_transpiller.analysis._collect import _collect_definitions
from arm_transpiller.analysis.subsumed_variables import (
    _subsumed_variables,
    extract_subsumed_variables,
)
from arm_transpiller.parser import parse

FIXTURES = Path(__file__).parent / "fixtures"


def _subsumed(source: str, **kwargs: object) -> list[str]:
    return _subsumed_variables(parse(source), kwargs.get("input_types"))  # type: ignore[arg-type]


def _extract_sv(source: str) -> list[str]:
    return extract_subsumed_variables(parse(source))


# =============================================================================
# Fixture-based: B T4 / BL T1 report I1, I2
# =============================================================================


def test_bl_t1_reports_i1_i2() -> None:
    # I1 and I2 (both bits1) are each read once, as leaves of the concat
    # S:I1:I2:imm10:imm11:'0' — 25 bits total.  SignExtend(..., 32) preserves
    # every leaf since 32 ≥ 25.  Neither I1 nor I2 is read elsewhere, so
    # both are subsumed by imm32.
    source = (FIXTURES / "bl_decoder.pseudo").read_text()
    result = _extract_sv(source)
    assert result == ["I1", "I2"]


# =============================================================================
# Fixture-based: negative — must NOT report anything
# =============================================================================


def test_subset_of_output_variables() -> None:
    source = (FIXTURES / "bl_decoder.pseudo").read_text()
    cond = set(extract_subsumed_variables(parse(source)))
    all_outputs = set(_collect_definitions(parse(source)))
    assert cond <= all_outputs


def test_adc_immediate_empty() -> None:
    source = (FIXTURES / "adc_immediate_decoder.pseudo").read_text()
    assert _extract_sv(source) == []


def test_vcvt_t1_empty() -> None:
    source = (FIXTURES / "vcvt_t1_decoder.pseudo").read_text()
    assert _extract_sv(source) == []


def test_vsel_t1_empty() -> None:
    source = (FIXTURES / "vsel_t1_decoder.pseudo").read_text()
    assert _extract_sv(source) == []


def test_vabs_t1_empty() -> None:
    source = (FIXTURES / "vabs_t1_decoder.pseudo").read_text()
    assert _extract_sv(source) == []


def test_vrinta_t1_empty() -> None:
    source = (FIXTURES / "vrinta_t1_decoder.pseudo").read_text()
    assert _extract_sv(source) == []


def test_vrintz_t1_empty() -> None:
    source = (FIXTURES / "vrintz_t1_decoder.pseudo").read_text()
    assert _extract_sv(source) == []


def test_vnmla_t1_empty() -> None:
    source = (FIXTURES / "vnmla_t1_decoder.pseudo").read_text()
    assert _extract_sv(source) == []


# =============================================================================
# Synthetic: variable read in propagating position AND elsewhere → NOT subsumed
# =============================================================================


def test_variable_spliced_and_read_in_condition_not_subsumed() -> None:
    # x (bits1 from I1) appears in a propagating position — a concat leaf in
    # SignExtend(x:imm8:'0', 32), where 1+8+1=10 ≤ 32 — but also in a
    # consuming position: the condition of an if-then.  A single consuming
    # read disqualifies a variable from being subsumed.
    source = "x = I1;\ny = SignExtend(x:imm8:'0', 32);\nif x == '0' then UNPREDICTABLE;"
    assert _subsumed(source) == []


def test_variable_spliced_and_read_as_call_arg_not_subsumed() -> None:
    # x (bits1) is a concat leaf — propagating — but also a ThumbExpandImm
    # argument, which is a consuming read (only SignExtend/ZeroExtend preserve).
    source = "x = I1;\ny = SignExtend(x:imm8:'0', 32);\nz = ThumbExpandImm(x);"
    assert _subsumed(source) == []


# =============================================================================
# Synthetic: truncating extension → NOT subsumed
# =============================================================================


def test_truncating_zero_extend_not_subsumed() -> None:
    # x = UInt(Rd) → uint32 (32 bits).  x:imm8 is 40 bits.  ZeroExtend to 8
    # truncates (8 < 40), so the width check rejects x.
    source = "x = UInt(Rd);\ny = ZeroExtend(x:imm8, 8);"
    result = _subsumed(source)
    assert "x" not in result


def test_non_truncating_sign_extend_with_concat_leaf_is_subsumed() -> None:
    # x = I1 → bits1.  x:imm8:'0' = 1+8+1 = 10 bits.  SignExtend to 32
    # preserves (32 ≥ 10).  x is only read here, so it is subsumed by y.
    source = "x = I1;\ny = SignExtend(x:imm8:'0', 32);"
    result = _subsumed(source)
    assert result == ["x"]


# =============================================================================
# Synthetic: chain a → b → c, only c retained
# =============================================================================


def test_chain_abc_only_c_retained() -> None:
    # a → b → c chain, each step preserves width:
    #   a (bits1) in a:imm2:'0' → 1+2+1=4, SignExtend to 16 ✓
    #   b (bits16) in b:imm8:'0' → 16+8+1=25, SignExtend to 32 ✓
    # The fixed-point resolves a first, then b, retaining only c.
    source = "a = I1;\nb = SignExtend(a:imm2:'0', 16);\nc = SignExtend(b:imm8:'0', 32);"
    result = _subsumed(source)
    assert "a" in result
    assert "b" in result
    assert "c" not in result


# =============================================================================
# Synthetic: variable spliced into non-output target → NOT subsumed
# =============================================================================


def test_variable_spliced_into_register_not_subsumed() -> None:
    # A concat that feeds into a register access target (R[1], not a plain
    # variable) does not propagate to any output member.
    source = "x = UInt(Rd);\nR[1] = x:imm8;"
    result = _subsumed(source)
    assert "x" not in result


def test_variable_spliced_into_bit_index_not_subsumed() -> None:
    # x is assigned to a FPSCR bit — not an output variable.
    source = "x = UInt(Rd);\nFPSCR<0> = x;"
    result = _subsumed(source)
    assert "x" not in result


def test_self_splice_not_subsumed() -> None:
    # t = t:x has t as a concat leaf propagating to itself.  Self-splice
    # is not a true subsumption — the variable's old value partially
    # defines its own new value, so dropping it would lose data.
    source = "t = NOT(a);\nt = t:x;"
    result = _subsumed(source)
    assert "t" not in result


# =============================================================================
# Synthetic: variable assigned but never read at all → NOT subsumed
# =============================================================================


def test_assigned_never_read_not_subsumed() -> None:
    # Rule 1: must be read at least once.  An assigned-but-unused variable
    # is not subsumed — it is simply dead.
    source = "x = UInt(Rd);\n"
    assert _subsumed(source) == []


# =============================================================================
# Synthetic: cyclic (not expressible in real decode but must not loop)
# =============================================================================


def test_cyclic_splice_does_not_loop() -> None:
    # a = b:c and b = a:'0' form a cycle.  The fixed-point resolution starts
    # with both kept; neither can resolve because each depends on the other.
    # The loop terminates with nothing subsumed.
    source = "a = b:c;\nb = a:'0';"
    result = _subsumed(source)
    assert "a" not in result
    assert "b" not in result


# =============================================================================
# JSON API
# =============================================================================


def test_json_api_accepts_string() -> None:
    # x (bits1) → concat 1+8+1=10, SignExtend to 32 → preserved.
    result = extract_subsumed_variables(
        parse("x = I1;\ny = SignExtend(x:imm8:'0', 32);")
    )
    assert result == ["x"]


def test_json_api_accepts_program() -> None:
    program = parse("x = I1;\ny = SignExtend(x:imm8:'0', 32);")
    result = extract_subsumed_variables(program)
    assert result == ["x"]


def test_subsumed_variables_returns_list() -> None:
    # Assigned but never read — not subsumed.
    result = extract_subsumed_variables(parse("x = I1;"))
    assert isinstance(result, list)
    assert result == []


def test_json_api_with_input_types() -> None:
    # Wibble (bits7 via override) → concat 7+8+1=16, SignExtend to 32 ✓.
    result = extract_subsumed_variables(
        parse("x = Wibble;\ny = SignExtend(x:imm8:'0', 32);"),
        {"Wibble": "bits7"},
    )
    assert result == ["x"]


def test_result_is_stable_order() -> None:
    # a → b → c chain: a (bits1), b (bits16 from 1+8+1=10→16),
    # c (32 from 16+10+1=27→32).  a subsumed by b, b by c.
    source = (
        "a = I1;\nb = SignExtend(a:imm8:'0', 16);\nc = SignExtend(b:imm10:'0', 32);"
    )
    for _ in range(5):
        result = _extract_sv(source)
        assert result == ["a", "b"]


# =============================================================================
# Exhaustiveness: direct concat (no extension wrapper)
# =============================================================================


def test_direct_concat_subsumed() -> None:
    # lo and hi are each uint32.  full = lo:hi → bits64.  Each leaf (32 bits)
    # fits within the target (64 bits), and neither is read elsewhere.
    source = "lo = UInt(Rd);\nhi = UInt(Rn);\nfull = lo:hi;"
    result = _subsumed(source)
    assert "lo" in result
    assert "hi" in result
    assert "full" not in result


# =============================================================================
# Width check: leaf wider than target → not subsumed
# =============================================================================


def test_leaf_wider_than_target_not_subsumed() -> None:
    # wide (sint32 from SInt(Rd)) is read in wide<3:0> — a BitRange, which
    # is a consuming read, not a propagating concat leaf.  So it cannot be
    # subsumed regardless of widths.
    source = "wide = SInt(Rd);\nnarrow = wide<3:0>;\ncombined = narrow:imm8;"
    result = _subsumed(source)
    assert "wide" not in result
