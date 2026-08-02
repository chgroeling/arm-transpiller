from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from arm_transpiller.generators.c_generator import CGenerator
from arm_transpiller.parser import parse

FIXTURES = Path(__file__).parent / "fixtures"

SOURCE = (FIXTURES / "adc_immediate_decoder.pseudo").read_text()

EXPECTED = """\
d = UInt(Rd);
n = UInt(Rn);
setflags = (S == 1);
imm32 = ThumbExpandImm(&sideffect_flags, concat_bits(concat_bits(i, imm3, 3), imm8, 8));
if ((((d == 13) || (d == 15)) || ((n == 13) || (n == 15)))) {
    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;
};
"""


# --- Basic C code generation ---


def test_c_adc_immediate_decoder() -> None:
    program = parse(SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED


def test_c_empty_program() -> None:
    from arm_transpiller.ast_nodes import Program

    gen = CGenerator()
    assert gen.generate(Program()) == "\n"


def test_c_assignment_integer() -> None:
    gen = CGenerator()
    program = parse("x = 42;\n")
    assert gen.generate(program) == "x = 42;\n"


def test_c_if_else() -> None:
    program = parse("if x == 1 then a = 1; else a = 2;\n")
    gen = CGenerator()
    output = gen.generate(program)
    assert "a = 1;" in output
    assert "a = 2;" in output
    assert "else" in output


# --- Fixture-based generation: POP / MVN (operations) ---


POP_SOURCE = (FIXTURES / "pop_ldm_op.pseudo").read_text()

EXPECTED_POP_C = (
    "if (ConditionPassed()) {\n"
    "    EncodingSpecificOperations();\n"
    "    address = SP;\n"
    "    SP = (SP + (4 * BitCount(registers)));\n"
    "    for (int i = 0; i <= 14; i++) {\n"
    "        if ((((registers >> i) & 1) == 1)) {\n"
    "            R[i] = MemA_read(ctx, address, 4);\n"
    "            address = (address + 4);\n"
    "        };\n"
    "    };\n"
    "    if ((((registers >> 15) & 1) == 1)) {\n"
    "        LoadWritePC(MemA_read(ctx, address, 4));\n"
    "    };\n"
    "};\n"
)


def test_c_pop_generation() -> None:
    program = parse(POP_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_POP_C


MVN_SOURCE = (FIXTURES / "mvn_register_op.pseudo").read_text()

EXPECTED_MVN_C = (
    "if (ConditionPassed()) {\n"
    "    EncodingSpecificOperations();\n"
    "    Tuple2Ret tuple_2_ret_1 = Shift_C(R[m], shift_t, shift_n, ctx->apsr.C);\n"
    "    shifted = tuple_2_ret_1.f0;\n"
    "    carry = tuple_2_ret_1.f1;\n"
    "    result = ((~shifted) & 0xffffffffu);\n"
    "    R[d] = result;\n"
    "    if (setflags) {\n"
    "        ctx->apsr.N = ((result >> 31) & 1);\n"
    "        ctx->apsr.Z = IsZeroBit(result);\n"
    "        ctx->apsr.C = carry;\n"
    "        // APSR.V unchanged\n"
    "    };\n"
    "};\n"
)


def test_c_mvn_register_op() -> None:
    program = parse(MVN_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_MVN_C


# --- C compilation tests (decoders) ---


# ---------------------------------------------------------------------------
# Optional C compilation tests (requires gcc or cc)
# ---------------------------------------------------------------------------

_CC = shutil.which("gcc") or shutil.which("cc")
_has_c_compiler = _CC is not None

c_compile = pytest.mark.skipif(
    not _has_c_compiler,
    reason="C compiler (gcc/cc) not found on PATH",
)

_ARMLIB_H = (
    Path(__file__).parent.parent
    / "src"
    / "arm_transpiller"
    / "armruntime"
    / "armruntime.h.template"
).read_text()

_C_ADC_MAIN = """\
int main(void) {
    uint32_t R[16] = {0};
    uint32_t d = 0, n = 0, Rd = 0, Rn = 0;
    uint32_t S = 0;
    bool setflags = false;
    uint32_t i = 0, imm3 = 0, imm8 = 0, imm32 = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""

_C_POP_MAIN = """\
int main(void) {
    uint32_t R[16] = {0};
    uint32_t registers = 0;
    uint32_t address = 0, SP = 0x1000;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""

_C_MVN_MAIN = """\
int main(void) {
    uint32_t R[16] = {0};
    uint32_t d = 0, m = 1;
    uint32_t shift_t = 0, shift_n = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
    uint32_t shifted = 0, carry = 0, result = 0;
    bool setflags = true;
"""

_C_POSTAMBLE = """
    return 0;
}
"""


def _compile_and_run(c_source: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".c", delete=False, encoding="utf-8"
    ) as src_file:
        src_file.write(c_source)
        src_path = src_file.name

    exe_path = src_path + ".out"
    try:
        assert _CC is not None
        compile_cmd = [
            _CC,
            "-std=c99",
            "-Wall",
            "-Werror",
            "-Wno-unused",
            "-o",
            exe_path,
            src_path,
        ]
        result = subprocess.run(compile_cmd, capture_output=True, text=True)
        assert result.returncode == 0, (
            f"Compilation failed:\n{result.stderr}\n{result.stdout}"
        )

        result = subprocess.run([exe_path], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        )
    finally:
        Path(src_path).unlink(missing_ok=True)
        Path(exe_path).unlink(missing_ok=True)


@c_compile
@pytest.mark.c_compile
def test_c_mvn_compiles() -> None:
    program = parse(MVN_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _C_MVN_MAIN + body + _C_POSTAMBLE)


@c_compile
@pytest.mark.c_compile
def test_c_pop_compiles() -> None:
    program = parse(POP_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _C_POP_MAIN + body + _C_POSTAMBLE)


@c_compile
@pytest.mark.c_compile
def test_c_adc_compiles() -> None:
    program = parse(SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _C_ADC_MAIN + body + _C_POSTAMBLE)


# --- Fixture-based: LSR / ADC register / EOR / SUB / BL decoders ---


LSR_SOURCE = (FIXTURES / "lsr_immediate_decoder.pseudo").read_text()

EXPECTED_LSR_C = (
    "d = UInt(Rd);\n"
    "m = UInt(Rm);\n"
    "setflags = (!InITBlock(ctx));\n"
    "Tuple2Ret tuple_2_ret_1 = DecodeImmShift(0x1, imm5);\n"
    "shift_n = tuple_2_ret_1.f1;\n"
)


def test_c_lsr_immediate_decoder() -> None:
    program = parse(LSR_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_LSR_C


_LSR_MAIN = """\
int main(void) {
    uint32_t d = 0, m = 0, Rd = 0, Rm = 0;
    bool setflags = false;
    uint32_t shift_n = 0, imm5 = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_lsr_compiles() -> None:
    program = parse(LSR_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _LSR_MAIN + body + _C_POSTAMBLE)


ADC_REG_SOURCE = (FIXTURES / "adc_register_t2_decoder.pseudo").read_text()

EXPECTED_ADC_REG_C = (
    "d = UInt(Rd);\n"
    "n = UInt(Rn);\n"
    "m = UInt(Rm);\n"
    "setflags = (S == 1);\n"
    "Tuple2Ret tuple_2_ret_1 = DecodeImmShift(type, concat_bits(imm3, imm2, 2));\n"
    "shift_t = tuple_2_ret_1.f0;\n"
    "shift_n = tuple_2_ret_1.f1;\n"
    "if (((((d == 13) || (d == 15)) || ((n == 13) || (n == 15)))"
    " || ((m == 13) || (m == 15)))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
)


def test_c_adc_register_decoder() -> None:
    program = parse(ADC_REG_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_ADC_REG_C


_ADC_REG_MAIN = """\
int main(void) {
    uint32_t R[16] = {0};
    uint32_t d = 0, n = 0, m = 0, Rd = 0, Rn = 0, Rm = 0;
    uint32_t S = 0;
    bool setflags = false;
    uint32_t type = 0, imm3 = 0, imm2 = 0;
    uint32_t shift_t = 0, shift_n = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_adc_register_compiles() -> None:
    program = parse(ADC_REG_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _ADC_REG_MAIN + body + _C_POSTAMBLE)


ADC_REG_TUPLE_SOURCE = (FIXTURES / "adc_register_t1_decoder.pseudo").read_text()

EXPECTED_ADC_REG_TUPLE_C = (
    "d = UInt(Rdn);\n"
    "n = UInt(Rdn);\n"
    "m = UInt(Rm);\n"
    "setflags = (!InITBlock(ctx));\n"
    "Tuple2Ret tuple_2_ret_1 = (Tuple2Ret){.f0 = SRType_LSL, .f1 = 0};\n"
    "shift_t = tuple_2_ret_1.f0;\n"
    "shift_n = tuple_2_ret_1.f1;\n"
)


def test_c_adc_register_tuple_decoder() -> None:
    program = parse(ADC_REG_TUPLE_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_ADC_REG_TUPLE_C


_ADC_REG_TUPLE_MAIN = """\
int main(void) {
    uint32_t d = 0, n = 0, m = 0, Rdn = 0, Rm = 0;
    bool setflags = false;
    uint32_t shift_t = 0, shift_n = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_adc_register_tuple_compiles() -> None:
    program = parse(ADC_REG_TUPLE_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _ADC_REG_TUPLE_MAIN + body + _C_POSTAMBLE)


EOR_SOURCE = (FIXTURES / "eor_immediate_decoder.pseudo").read_text()

EXPECTED_EOR_C = (
    "// EOR (immediate) — T1 encoding\n"
    "if (((Rd == 0xf) && (S == 1))) {\n"
    '    sideffect_flags |= SIDEFFECT_SEE;  // "TEQ (immediate)"\n'
    "};\n"
    "d = UInt(Rd);\n"
    "n = UInt(Rn);\n"
    "setflags = (S == 1);\n"
    "Tuple2Ret tuple_2_ret_1 = ThumbExpandImm_C(&sideffect_flags, "
    "concat_bits(concat_bits(i, imm3, 3), imm8, 8), ctx->apsr.C);\n"
    "imm32 = tuple_2_ret_1.f0;\n"
    "carry = tuple_2_ret_1.f1;\n"
    "if ((((d == 13) || ((d == 15) && (S == 0))) || ((n == 13) || (n == 15)))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
)


def test_c_eor_immediate_decoder() -> None:
    program = parse(EOR_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_EOR_C


_C_EOR_MAIN = """\
int main(void) {
    uint32_t R[16] = {0};
    uint32_t d = 0, n = 0, Rd = 0, Rn = 0, S = 0;
    bool setflags = false;
    uint32_t i = 0, imm3 = 0, imm8 = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
    uint32_t imm32 = 0, carry = 0;
"""


@c_compile
@pytest.mark.c_compile
def test_c_eor_compiles() -> None:
    program = parse(EOR_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _C_EOR_MAIN + body + _C_POSTAMBLE)


SUB_IMM_SOURCE = (FIXTURES / "sub_immediate_decoder.pseudo").read_text()

EXPECTED_SUB_IMM_C = (
    "if (((Rd == 0xf) && (S == 1))) {\n"
    '    sideffect_flags |= SIDEFFECT_SEE;  // "CMP (immediate)"\n'
    "};\n"
    "if ((Rn == 0xd)) {\n"
    '    sideffect_flags |= SIDEFFECT_SEE;  // "SUB (SP minus immediate)"\n'
    "};\n"
    "d = UInt(Rd);\n"
    "n = UInt(Rn);\n"
    "setflags = (S == 1);\n"
    "imm32 = ThumbExpandImm(&sideffect_flags,"
    " concat_bits(concat_bits(i, imm3, 3), imm8, 8));\n"
    "if ((((d == 13) || ((d == 15) && (S == 0))) || (n == 15))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
)


def test_c_sub_immediate_decoder() -> None:
    program = parse(SUB_IMM_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_SUB_IMM_C


_SUB_IMM_MAIN = """\
int main(void) {
    uint32_t Rd = 0, Rn = 0, S = 0;
    uint32_t d = 0, n = 0;
    bool setflags = false;
    uint32_t i = 0, imm3 = 0, imm8 = 0, imm32 = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_sub_immediate_compiles() -> None:
    program = parse(SUB_IMM_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _SUB_IMM_MAIN + body + _C_POSTAMBLE)


BL_SOURCE = (FIXTURES / "bl_decoder.pseudo").read_text()

EXPECTED_BL_C = (
    "I1 = ((~((J1 ^ S) & 0x1u)) & 0x1u);\n"
    "I2 = ((~((J2 ^ S) & 0x1u)) & 0x1u);\n"
    "imm32 = SignExtend(concat_bits(concat_bits(concat_bits("
    "concat_bits(concat_bits(S, I1, 1), I2, 1), imm10, 10), "
    "imm11, 11), 0, 1), 25);\n"
    "if ((InITBlock(ctx) && (!LastInITBlock(ctx)))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
)


def test_c_bl_decoder() -> None:
    program = parse(BL_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_BL_C


_BL_MAIN = """\
int main(void) {
    uint32_t J1 = 0, J2 = 0, S = 0, imm10 = 0, imm11 = 0;
    uint32_t I1 = 0, I2 = 0, imm32 = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_bl_compiles() -> None:
    program = parse(BL_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _BL_MAIN + body + _C_POSTAMBLE)


B_T3_SOURCE = (FIXTURES / "b_t3_decoder.pseudo").read_text()

EXPECTED_B_T3_C = (
    "if ((((cond >> 1) & 0x7) == 0x7)) {\n"
    '    sideffect_flags |= SIDEFFECT_SEE;  // "Related encodings"\n'
    "};\n"
    "imm32 = SignExtend(concat_bits(concat_bits(concat_bits("
    "concat_bits(concat_bits(S, J2, 1), J1, 1), imm6, 6), "
    "imm11, 11), 0, 1), 21);\n"
    "if (InITBlock(ctx)) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
)


def test_c_b_t3_decoder() -> None:
    program = parse(B_T3_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_B_T3_C


_B_T3_MAIN = """\
int main(void) {
    uint32_t cond = 0, S = 0, J1 = 0, J2 = 0, imm6 = 0, imm11 = 0;
    uint32_t imm32 = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_b_t3_compiles() -> None:
    program = parse(B_T3_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _B_T3_MAIN + body + _C_POSTAMBLE)


# --- Fixture-based: LDRH / POP_T3 / MRS_T1 / ORR / AND / REV / STR ---


LDRH_REG_SOURCE = (FIXTURES / "ldrh_register_decoder.pseudo").read_text()

EXPECTED_LDRH_REG_C = (
    "if ((Rn == 0xf)) {\n"
    '    sideffect_flags |= SIDEFFECT_SEE;  // "LDRH (literal)"\n'
    "};\n"
    "if ((Rt == 0xf)) {\n"
    '    sideffect_flags |= SIDEFFECT_SEE;  // "Related instructions"\n'
    "};\n"
    "t = UInt(Rt);\n"
    "n = UInt(Rn);\n"
    "m = UInt(Rm);\n"
    "index = true;\n"
    "add = true;\n"
    "wback = false;\n"
    "Tuple2Ret tuple_2_ret_1 = (Tuple2Ret){.f0 = SRType_LSL, .f1 = UInt(imm2)};\n"
    "shift_t = tuple_2_ret_1.f0;\n"
    "shift_n = tuple_2_ret_1.f1;\n"
    "if (((t == 13) || ((m == 13) || (m == 15)))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
)


def test_c_ldrh_register_decoder() -> None:
    program = parse(LDRH_REG_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_LDRH_REG_C


_LDRH_REG_MAIN = """\
int main(void) {
    uint32_t d = 0, n = 0, m = 0, Rd = 0, Rn = 0, Rm = 0;
    uint32_t t = 0, Rt = 0;
    uint32_t index = 0, add = 0, wback = 0;
    uint32_t imm2 = 0;
    uint32_t shift_t = 0, shift_n = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_ldrh_register_compiles() -> None:
    program = parse(LDRH_REG_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _LDRH_REG_MAIN + body + _C_POSTAMBLE)


POP_T3_SOURCE = (FIXTURES / "pop_t3_decoder.pseudo").read_text()

EXPECTED_POP_T3_C = (
    "t = UInt(Rt);\n"
    "registers = Zeros(16);\n"
    "registers = (registers | (1 << t));\n"
    "UnalignedAllowed = true;\n"
    "if (((t == 13) || (((t == 15) && InITBlock(ctx)) && (!LastInITBlock(ctx))))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
)


def test_c_pop_t3_decoder() -> None:
    program = parse(POP_T3_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_POP_T3_C


_POP_T3_MAIN = """\
int main(void) {
    uint32_t R[16] = {0};
    uint32_t t = 0, Rt = 0, registers = 0;
    uint32_t UnalignedAllowed = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_pop_t3_compiles() -> None:
    program = parse(POP_T3_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _POP_T3_MAIN + body + _C_POSTAMBLE)


MRS_T1_SOURCE = (FIXTURES / "mrs_t1_decoder.pseudo").read_text()

EXPECTED_MRS_T1_C = (
    "d = UInt(Rd);\n"
    "if ((((d == 13) || (d == 15)) || (!((UInt(SYSm) >= 0 && UInt(SYSm) <= 3) ||"
    " (UInt(SYSm) >= 5 && UInt(SYSm) <= 9) ||"
    " (UInt(SYSm) >= 16 && UInt(SYSm) <= 20))))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
)


def test_c_mrs_t1_decoder() -> None:
    program = parse(MRS_T1_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_MRS_T1_C


_MRS_T1_MAIN = """\
int main(void) {
    uint32_t d = 0, Rd = 0;
    uint32_t SYSm = 0;
"""


ORR_SOURCE = (FIXTURES / "orr_immediate_op.pseudo").read_text()

EXPECTED_ORR_C = (
    "if (ConditionPassed()) {\n"
    "    EncodingSpecificOperations();\n"
    "    result = ((R[n] | imm32) & 0xffffffffu);\n"
    "    R[d] = result;\n"
    "    if (setflags) {\n"
    "        ctx->apsr.N = ((result >> 31) & 1);\n"
    "        ctx->apsr.Z = IsZeroBit(result);\n"
    "        ctx->apsr.C = carry;\n"
    "        // APSR.V unchanged\n"
    "    };\n"
    "};\n"
)


def test_c_orr_immediate_op() -> None:
    program = parse(ORR_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_ORR_C


_ORR_MAIN = """\
int main(void) {
    uint32_t R[16] = {0};
    uint32_t result = 0, n = 0, d = 0;
    uint32_t imm32 = 0;
    bool setflags = true;
    uint32_t carry = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_orr_compiles() -> None:
    program = parse(ORR_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _ORR_MAIN + body + _C_POSTAMBLE)


AND_SOURCE = (FIXTURES / "and_register_op.pseudo").read_text()

EXPECTED_AND_C = (
    "if (ConditionPassed()) {\n"
    "    EncodingSpecificOperations();\n"
    "    Tuple2Ret tuple_2_ret_1 = Shift_C(R[m], shift_t, shift_n, ctx->apsr.C);\n"
    "    shifted = tuple_2_ret_1.f0;\n"
    "    carry = tuple_2_ret_1.f1;\n"
    "    result = ((R[n] & shifted) & 0xffffffffu);\n"
    "    R[d] = result;\n"
    "    if (setflags) {\n"
    "        ctx->apsr.N = ((result >> 31) & 1);\n"
    "        ctx->apsr.Z = IsZeroBit(result);\n"
    "        ctx->apsr.C = carry;\n"
    "        // APSR.V unchanged\n"
    "    };\n"
    "};\n"
)


def test_c_and_register_op() -> None:
    program = parse(AND_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_AND_C


_AND_MAIN = """\
int main(void) {
    uint32_t R[16] = {0};
    uint32_t shifted = 0, carry = 0, result = 0;
    uint32_t d = 0, m = 1, n = 0;
    uint32_t shift_t = 0, shift_n = 0;
    bool setflags = true;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_and_compiles() -> None:
    program = parse(AND_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _AND_MAIN + body + _C_POSTAMBLE)


REV_T2_SOURCE = (FIXTURES / "rev_t2_decoder.pseudo").read_text()

EXPECTED_REV_T2_C = (
    "if ((!Consistent(Rm))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
    "d = UInt(Rd);\n"
    "m = UInt(Rm);\n"
    "if ((((d == 13) || (d == 15)) || ((m == 13) || (m == 15)))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
)


def test_c_rev_t2_decoder() -> None:
    program = parse(REV_T2_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_REV_T2_C


_REV_T2_MAIN = """\
int main(void) {
    uint32_t R[16] = {0};
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
    uint32_t d = 0, m = 0, Rd = 0, Rm = 0;
"""


@c_compile
@pytest.mark.c_compile
def test_c_rev_t2_compiles() -> None:
    program = parse(REV_T2_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _REV_T2_MAIN + body + _C_POSTAMBLE)


STR_REG_SOURCE = (FIXTURES / "str_register_op.pseudo").read_text()

EXPECTED_STR_REG_C = (
    "if (ConditionPassed()) {\n"
    "    EncodingSpecificOperations();\n"
    "    offset = Shift(R[m], shift_t, shift_n, ctx->apsr.C);\n"
    "    address = (R[n] + offset);\n"
    "    MemU_write(ctx, address, 4, R[t]);\n"
    "};\n"
)


def test_c_str_register_op() -> None:
    program = parse(STR_REG_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_STR_REG_C


_STR_REG_MAIN = """\
int main(void) {
    uint32_t R[16] = {0};
    uint32_t offset = 0, address = 0;
    uint32_t m = 0, n = 0, t = 0;
    uint32_t shift_t = 0, shift_n = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_str_register_compiles() -> None:
    program = parse(STR_REG_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _STR_REG_MAIN + body + _C_POSTAMBLE)


# ---------------------------------------------------------------------------
# Fixture-based: VPU decoders (VABS / VCVT / VRINTA / VSEL / RSB) + field_widths
# ---------------------------------------------------------------------------


VABS_T1_SOURCE = (FIXTURES / "vabs_t1_decoder.pseudo").read_text()

EXPECTED_VABS_T1_C = (
    "dp_operation = (sz == 1);\n"
    "d = (dp_operation ? UInt(concat_bits(D, Vd, 4))"
    " : UInt(concat_bits(Vd, D, 1)));\n"
    "m = (dp_operation ? UInt(concat_bits(M, Vm, 4))"
    " : UInt(concat_bits(Vm, M, 1)));\n"
)


def test_c_vabs_t1_decoder() -> None:
    program = parse(VABS_T1_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VABS_T1_C


_VABS_T1_MAIN = """\
int main(void) {
    uint32_t dp_operation = 0, sz = 0;
    uint32_t d = 0, m = 0;
    uint32_t D = 0, Vd = 0, M = 0, Vm = 0;
"""


@c_compile
@pytest.mark.c_compile
def test_c_vabs_t1_compiles() -> None:
    program = parse(VABS_T1_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _VABS_T1_MAIN + body + _C_POSTAMBLE)


VCVT_T1_SOURCE = (FIXTURES / "vcvt_t1_decoder.pseudo").read_text()

EXPECTED_VCVT_T1_C = (
    "if (((opc2 != 0x0) && (!((opc2 & 0x6u) == 0x4u)))) {\n"
    '    sideffect_flags |= SIDEFFECT_SEE;  // "Related encodings"\n'
    "};\n"
    "to_integer = (((opc2 >> 2) & 1) == 1);\n"
    "dp_operation = (sz == 1);\n"
    "if (to_integer) {\n"
    "    _unsigned = (((opc2 >> 0) & 1) == 0);\n"
    "    round_zero = (op == 1);\n"
    "    d = UInt(concat_bits(Vd, D, 1));\n"
    "    m = (dp_operation ? UInt(concat_bits(M, Vm, 4))"
    " : UInt(concat_bits(Vm, M, 1)));\n"
    "} else {\n"
    "    _unsigned = (op == 0);\n"
    "    round_nearest = false;\n"
    "    m = UInt(concat_bits(Vm, M, 1));\n"
    "    d = (dp_operation ? UInt(concat_bits(D, Vd, 4))"
    " : UInt(concat_bits(Vd, D, 1)));\n"
    "};\n"
)


def test_c_vcvt_t1_decoder() -> None:
    program = parse(VCVT_T1_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VCVT_T1_C


_VCVT_T1_MAIN = """\
int main(void) {
    uint32_t opc2 = 0, op = 0, sz = 0;
    uint32_t to_integer = 0, dp_operation = 0;
    uint32_t _unsigned = 0, round_zero = 0, round_nearest = 0;
    uint32_t d = 0, m = 0;
    uint32_t D = 0, Vd = 0, M = 0, Vm = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_vcvt_t1_compiles() -> None:
    program = parse(VCVT_T1_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _VCVT_T1_MAIN + body + _C_POSTAMBLE)


VRINTA_T1_SOURCE = (FIXTURES / "vrinta_t1_decoder.pseudo").read_text()

EXPECTED_VRINTA_T1_C = (
    "if (InITBlock(ctx)) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
    "dp_operation = (sz == 1);\n"
    "if (RM == 0x0) {  // Round to nearest, with ties away\n"
    "    rmode = 0x1;\n"
    "    away = true;\n"
    "} else if (RM == 0x1) {  // Round to nearest, with ties to even\n"
    "    rmode = 0x0;\n"
    "    away = false;\n"
    "} else if (RM == 0x2) {  // Round towards Plus Infinity\n"
    "    rmode = 0x1;\n"
    "    away = false;\n"
    "} else if (RM == 0x3) {  // Round towards Minus Infinity\n"
    "    rmode = 0x2;\n"
    "    away = false;\n"
    "};\n"
    "d = (dp_operation ? UInt(concat_bits(D, Vd, 4))"
    " : UInt(concat_bits(Vd, D, 1)));\n"
    "m = (dp_operation ? UInt(concat_bits(M, Vm, 4))"
    " : UInt(concat_bits(Vm, M, 1)));\n"
)


def test_c_vrinta_t1_decoder() -> None:
    program = parse(VRINTA_T1_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VRINTA_T1_C


_VRINTA_T1_MAIN = """\
int main(void) {
    uint32_t RM = 0, sz = 0;
    uint32_t dp_operation = 0;
    uint32_t rmode = 0, away = 0;
    uint32_t d = 0, m = 0;
    uint32_t D = 0, Vd = 0, M = 0, Vm = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_vrinta_t1_compiles() -> None:
    program = parse(VRINTA_T1_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _VRINTA_T1_MAIN + body + _C_POSTAMBLE)


VSEL_T1_SOURCE = (FIXTURES / "vsel_t1_decoder.pseudo").read_text()

EXPECTED_VSEL_T1_C = (
    "if (InITBlock(ctx)) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
    "dp_operation = (sz == 1);\n"
    "cond = concat_bits(concat_bits(cc, (((cc >> 1) & 1) ^ ((cc >> 0) & 1)), 1)"
    ", 0, 1);\n"
    "d = (dp_operation ? UInt(concat_bits(D, Vd, 4))"
    " : UInt(concat_bits(Vd, D, 1)));\n"
    "n = (dp_operation ? UInt(concat_bits(N, Vn, 4))"
    " : UInt(concat_bits(Vn, N, 1)));\n"
    "m = (dp_operation ? UInt(concat_bits(M, Vm, 4))"
    " : UInt(concat_bits(Vm, M, 1)));\n"
)


def test_c_vsel_t1_decoder() -> None:
    program = parse(VSEL_T1_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VSEL_T1_C


_VSEL_T1_MAIN = """\
int main(void) {
    uint32_t sz = 0, cc = 0, dp_operation = 0, cond = 0;
    uint32_t d = 0, n = 0, m = 0;
    uint32_t D = 0, Vd = 0, N = 0, Vn = 0, M = 0, Vm = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_vsel_t1_compiles() -> None:
    program = parse(VSEL_T1_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _VSEL_T1_MAIN + body + _C_POSTAMBLE)


VNMLA_T1_SOURCE = (FIXTURES / "vnmla_t1_decoder.pseudo").read_text()

EXPECTED_VNMLA_T1_C = (
    "type = ((op == 1) ? VFPNegMul_VNMLA : VFPNegMul_VNMLS);\n"
    "dp_operation = (sz == 1);\n"
    "d = (dp_operation ? UInt(concat_bits(D, Vd, 4))"
    " : UInt(concat_bits(Vd, D, 1)));\n"
    "n = (dp_operation ? UInt(concat_bits(N, Vn, 4))"
    " : UInt(concat_bits(Vn, N, 1)));\n"
    "m = (dp_operation ? UInt(concat_bits(M, Vm, 4))"
    " : UInt(concat_bits(Vm, M, 1)));\n"
)


def test_c_vnmla_t1_decoder() -> None:
    program = parse(VNMLA_T1_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VNMLA_T1_C


_VNMLA_T1_MAIN = """\
int main(void) {
    uint32_t op = 0, sz = 0;
    uint32_t type = 0, dp_operation = 0;
    uint32_t d = 0, n = 0, m = 0;
    uint32_t D = 0, Vd = 0, N = 0, Vn = 0, M = 0, Vm = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_vnmla_t1_compiles() -> None:
    program = parse(VNMLA_T1_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _VNMLA_T1_MAIN + body + _C_POSTAMBLE)


VLDM_T1_SOURCE = (FIXTURES / "vldm_t1_decoder.pseudo").read_text()

EXPECTED_VLDM_T1_C = (
    "if ((((P == 0) && (U == 0)) && (W == 0))) {\n"
    '    sideffect_flags |= SIDEFFECT_SEE;  // "Related encodings"\n'
    "};\n"
    "if (((((P == 0) && (U == 1)) && (W == 1)) && (Rn == 0xd))) {\n"
    '    sideffect_flags |= SIDEFFECT_SEE;  // "VPOP"\n'
    "};\n"
    "if (((P == 1) && (W == 0))) {\n"
    '    sideffect_flags |= SIDEFFECT_SEE;  // "VLDR"\n'
    "};\n"
    "if ((((imm8 >> 0) & 1) == 1)) {\n"
    '    sideffect_flags |= SIDEFFECT_SEE;  // "FLDMX"\n'
    "};\n"
    "if (((P == U) && (W == 1))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNDEFINED;\n"
    "};\n"
    "// Remaining combinations are PUW = 010 (IA without !)"
    ", 011 (IA with !), 101 (DB with !)\n"
    "single_regs = false;\n"
    "add = (U == 1);\n"
    "wback = (W == 1);\n"
    "d = UInt(concat_bits(D, Vd, 4));\n"
    "n = UInt(Rn);\n"
    "imm32 = ZeroExtend(concat_bits(imm8, 0x0, 2), 32);\n"
    "regs = (UInt(imm8) / 2);\n"
    "if ((n == 15)) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
    "if ((((regs == 0) || (regs > 16)) || ((d + regs) > 32))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
    "if ((VFPSmallRegisterBank() && ((d + regs) > 16))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
)


def test_c_vldm_t1_decoder() -> None:
    program = parse(VLDM_T1_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VLDM_T1_C


_VLDM_T1_MAIN = """\
int main(void) {
    uint32_t P = 0, U = 0, W = 0;
    uint32_t Rn = 0, imm8 = 0;
    uint32_t D = 0, Vd = 0;
    bool single_regs = false, add = false, wback = false;
    uint32_t d = 0, n = 0, imm32 = 0, regs = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_vldm_t1_compiles() -> None:
    program = parse(VLDM_T1_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _VLDM_T1_MAIN + body + _C_POSTAMBLE)


VRINTZ_T1_SOURCE = (FIXTURES / "vrintz_t1_decoder.pseudo").read_text()

EXPECTED_VRINTZ_T1_C = (
    "dp_operation = (sz == 1);\n"
    "rmode = ((op == 1) ? 0x3 : ((ctx->fpscr >> 22) & 0x3));\n"
    "d = (dp_operation ? UInt(concat_bits(D, Vd, 4))"
    " : UInt(concat_bits(Vd, D, 1)));\n"
    "m = (dp_operation ? UInt(concat_bits(M, Vm, 4))"
    " : UInt(concat_bits(Vm, M, 1)));\n"
)


def test_c_vrintz_t1_decoder() -> None:
    program = parse(VRINTZ_T1_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VRINTZ_T1_C


_VRINTZ_T1_MAIN = """\
int main(void) {
    uint32_t sz = 0, op = 0;
    uint32_t dp_operation = 0, rmode = 0;
    uint32_t d = 0, m = 0;
    uint32_t D = 0, Vd = 0, M = 0, Vm = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    _ctx.fpscr = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_vrintz_t1_compiles() -> None:
    program = parse(VRINTZ_T1_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _VRINTZ_T1_MAIN + body + _C_POSTAMBLE)


RSB_IMM_T1_SOURCE = (FIXTURES / "rsb_immediate_t1_decoder.pseudo").read_text()

EXPECTED_RSB_IMM_T1_C = (
    "d = UInt(Rd);\n"
    "n = UInt(Rn);\n"
    "setflags = (!InITBlock(ctx));\n"
    "imm32 = Zeros(32);  // immediate = #0\n"
)


def test_c_rsb_immediate_t1_decoder() -> None:
    program = parse(RSB_IMM_T1_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_RSB_IMM_T1_C


def test_c_comment_inline_on_same_line() -> None:
    program = parse("x = 1;  // inline\n")
    gen = CGenerator()
    output = gen.generate(program)
    expected = "x = 1;  // inline\n"
    assert output == expected


def test_c_comment_standalone_on_own_line() -> None:
    program = parse("// standalone\nx = 1;\n")
    gen = CGenerator()
    output = gen.generate(program)
    expected = "// standalone\nx = 1;\n"
    assert output == expected


_RSB_IMM_T1_MAIN = """\
int main(void) {
    uint32_t d = 0, n = 0, Rd = 0, Rn = 0;
    bool setflags = false;
    uint32_t imm32 = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_rsb_immediate_t1_compiles() -> None:
    program = parse(RSB_IMM_T1_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _RSB_IMM_T1_MAIN + body + _C_POSTAMBLE)


# --- input_types constructor / override tests ---


def test_c_input_types_overrides_known_name() -> None:
    gen = CGenerator(input_types={"Rdn": "bits3"})
    program = parse("x = UInt(Rdn);")
    output = gen.generate(program)
    assert output == "x = UInt(Rdn);\n"


def test_c_input_types_supplies_unknown_name() -> None:
    gen = CGenerator(input_types={"Rdm": "bits3"})
    program = parse("x = UInt(Rdm);")
    output = gen.generate(program)
    assert output == "x = UInt(Rdm);\n"


def test_c_input_types_overrides_imm_pattern() -> None:
    gen = CGenerator(input_types={"imm8": "bits16"})
    program = parse("x = SignExtend(imm8, 32);")
    output = gen.generate(program)
    assert "SignExtend(imm8, 16)" in output


def test_c_input_types_accepts_arm_type_objects() -> None:
    from arm_transpiller.known_types import uint

    gen = CGenerator(input_types={"imm8": uint(16)})
    program = parse("x = SignExtend(imm8, 32);")
    assert "SignExtend(imm8, 16)" in gen.generate(program)


def test_c_input_types_bool_masks_to_one_bit() -> None:
    gen = CGenerator(input_types={"flag": "bool"})
    program = parse("x = NOT(flag);")
    assert gen.generate(program) == "x = ((~flag) & 0x1u);\n"


def test_c_concat_width_comes_from_input_types() -> None:
    gen = CGenerator(input_types={"a": "bits5", "b": "bits7"})
    program = parse("x = SignExtend(a:b, 32);")
    output = gen.generate(program)
    assert "concat_bits(a, b, 7)" in output
    assert "SignExtend(concat_bits(a, b, 7), 12)" in output


def test_c_without_input_types_unknown_name_raises() -> None:
    from arm_transpiller.known_types import UnknownVariableTypeError

    gen = CGenerator()
    program = parse("x = SignExtend(Rdm, 32);")
    with pytest.raises(UnknownVariableTypeError, match="Rdm"):
        gen.generate(program)


def test_c_unknown_function_return_type_raises() -> None:
    from arm_transpiller.known_types import UnknownFunctionTypeError

    gen = CGenerator()
    program = parse("x = SignExtend(FancyDecode(Rd), 32);")
    with pytest.raises(UnknownFunctionTypeError, match="FancyDecode"):
        gen.generate(program)


_FW_MAIN = """\
int main(void) {
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
    uint32_t x = 0, imm8 = 0xFF;
"""


@c_compile
@pytest.mark.c_compile
def test_c_input_types_signextend_compiles() -> None:
    gen = CGenerator(input_types={"imm8": "bits16"})
    program = parse("x = SignExtend(imm8, 32);")
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _FW_MAIN + body + _C_POSTAMBLE)


# --- Signedness: C's usual arithmetic conversions need explicit casts ---


def test_c_signed_comparison_casts_both_operands() -> None:
    gen = CGenerator()
    program = parse("off = SInt(Rn); x = off < 0;")
    output = gen.generate(program)
    assert "x = ((int32_t)off < (int32_t)0);" in output


def test_c_sint_gets_the_operand_width() -> None:
    gen = CGenerator()
    assert gen.generate(parse("x = SInt(imm8);")) == "x = SInt(imm8, 8);\n"


def test_c_sint_keeps_an_explicit_width() -> None:
    gen = CGenerator()
    assert gen.generate(parse("x = SInt(imm8, 32);")) == "x = SInt(imm8, 32);\n"


def test_c_signed_division_casts_both_operands() -> None:
    gen = CGenerator()
    program = parse("off = SInt(Rn); x = off DIV imm3;")
    output = gen.generate(program)
    assert "x = ((int32_t)off / (int32_t)imm3);" in output


def test_c_signed_modulo_casts_both_operands() -> None:
    gen = CGenerator()
    program = parse("off = SInt(Rn); x = off MOD imm3;")
    output = gen.generate(program)
    assert "x = ((int32_t)off % (int32_t)imm3);" in output


def test_c_negation_makes_a_comparison_signed() -> None:
    gen = CGenerator()
    program = parse("x = -imm8 < imm3;")
    output = gen.generate(program)
    assert "x = ((int32_t)(-imm8) < (int32_t)imm3);" in output


def test_c_equality_is_not_cast_even_when_signed() -> None:
    gen = CGenerator()
    program = parse("off = SInt(Rn); x = off == 0;")
    output = gen.generate(program)
    assert "x = (off == 0);" in output


def test_c_unsigned_comparison_is_not_cast() -> None:
    gen = CGenerator()
    program = parse("x = imm8 < imm3; y = imm8 DIV imm3;")
    output = gen.generate(program)
    assert output == "x = (imm8 < imm3);\ny = (imm8 / imm3);\n"


def test_c_signedness_follows_input_types() -> None:
    gen = CGenerator(input_types={"delta": "sint16"})
    program = parse("x = delta < imm3;")
    output = gen.generate(program)
    assert "x = ((int32_t)delta < (int32_t)imm3);" in output


_SIGNED_MAIN = """\
int main(void) {
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
    uint32_t Rn = 0xFu;  /* all ones in a 4-bit field: -1 read as signed */
    uint32_t imm3 = 2;
    uint32_t off = 0, is_negative = 0, quotient = 0;
"""

_SIGNED_CHECKS = """
    if ((int32_t)off != -1) return 1;
    if (is_negative != 1) return 2;
    /* unsigned division would give 0x7FFFFFFF here */
    if ((int32_t)quotient != 0) return 3;
    return 0;
}
"""


@c_compile
@pytest.mark.c_compile
def test_c_signed_comparison_and_division_are_correct_at_runtime() -> None:
    gen = CGenerator()
    program = parse("off = SInt(Rn); is_negative = off < 0; quotient = off DIV imm3;")
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _SIGNED_MAIN + body + _SIGNED_CHECKS)


# --- VMOV (immediate) T1 ---

VMOV_IMM_T1_SOURCE = (FIXTURES / "vmov_immediate_t1_decoder.pseudo").read_text()

EXPECTED_VMOV_IMM_T1_C = (
    "dp_operation = (sz == 1);\n"
    "if (dp_operation) {\n"
    "    d = UInt(concat_bits(D, Vd, 4));\n"
    "    imm64 = VFPExpandImm(concat_bits(imm4H, imm4L, 4), 64);\n"
    "} else {\n"
    "    d = UInt(concat_bits(Vd, D, 1));\n"
    "    imm32 = VFPExpandImm(concat_bits(imm4H, imm4L, 4), 32);\n"
    "};\n"
)


def test_c_vmov_immediate_t1_decoder() -> None:
    program = parse(VMOV_IMM_T1_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VMOV_IMM_T1_C


_VMOV_IMM_T1_MAIN = """\
int main(void) {
    uint32_t dp_operation = 0, sz = 0;
    uint32_t d = 0, imm64 = 0, imm32 = 0;
    uint32_t D = 0, Vd = 0, imm4H = 0, imm4L = 0;
"""


@c_compile
@pytest.mark.c_compile
def test_c_vmov_immediate_t1_compiles() -> None:
    program = parse(VMOV_IMM_T1_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _VMOV_IMM_T1_MAIN + body + _C_POSTAMBLE)


# --- SSAT (T1) ---

SSAT_T1_SOURCE = (FIXTURES / "ssat_t1_decoder.pseudo").read_text()

EXPECTED_SSAT_T1_C = (
    "if (((sh == 1) && (concat_bits(imm3, imm2, 2) == 0x0))) {\n"
    "    if (HaveDSPExt()) {\n"
    '        sideffect_flags |= SIDEFFECT_SEE;  // "SSAT16"\n'
    "    } else {\n"
    "        sideffect_flags |= SIDEFFECT_UNDEFINED;\n"
    "    };\n"
    "};\n"
    "d = UInt(Rd);\n"
    "n = UInt(Rn);\n"
    "saturate_to = (UInt(sat_imm) + 1);\n"
    "Tuple2Ret tuple_2_ret_1 = DecodeImmShift(concat_bits(sh, 0, 1), "
    "concat_bits(imm3, imm2, 2));\n"
    "shift_t = tuple_2_ret_1.f0;\n"
    "shift_n = tuple_2_ret_1.f1;\n"
    "if ((((d == 13) || (d == 15)) || ((n == 13) || (n == 15)))) {\n"
    "    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;\n"
    "};\n"
)


def test_c_ssat_t1_decoder() -> None:
    program = parse(SSAT_T1_SOURCE)
    gen = CGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_SSAT_T1_C


_SSAT_T1_MAIN = """\
int main(void) {
    uint32_t R[16] = {0};
    uint32_t d = 0, n = 0, Rd = 0, Rn = 0, sat_imm = 0, saturate_to = 0;
    uint32_t sh = 0, imm3 = 0, imm2 = 0;
    uint32_t shift_t = 0, shift_n = 0;
    Context _ctx = {0};
    SideffectFlags sideffect_flags = 0;
    Context *ctx = &_ctx;
"""


@c_compile
@pytest.mark.c_compile
def test_c_ssat_t1_compiles() -> None:
    program = parse(SSAT_T1_SOURCE)
    gen = CGenerator()
    body = gen.generate(program)
    _compile_and_run(_ARMLIB_H + _SSAT_T1_MAIN + body + _C_POSTAMBLE)
