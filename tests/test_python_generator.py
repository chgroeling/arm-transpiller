from __future__ import annotations

from pathlib import Path

import pytest

from arm_transpiller.generators.python_generator import PythonGenerator
from arm_transpiller.parser import parse

FIXTURES = Path(__file__).parent / "fixtures"

SOURCE = (FIXTURES / "adc_immediate_decoder.pseudo").read_text()

EXPECTED = """\
d = UInt(Rd)
n = UInt(Rn)
setflags = (S == 1)
imm32 = ThumbExpandImm(ctx, concat_bits(concat_bits(i, imm3, 3), imm8, 8))
if (((d == 13) or (d == 15)) or ((n == 13) or (n == 15))):
    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE
"""


# --- Basic Python code generation ---


def test_python_adc_immediate_decoder() -> None:
    program = parse(SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED


def test_python_empty_program() -> None:
    from arm_transpiller.ast_nodes import Program

    gen = PythonGenerator()
    assert gen.generate(Program()) == "\n"


def test_python_assignment_integer() -> None:
    gen = PythonGenerator()
    program = parse("x = 42;\n")
    assert gen.generate(program) == "x = 42\n"


def test_python_if_else() -> None:
    program = parse("if x == 1 then a = 1; else a = 2;\n")
    gen = PythonGenerator()
    output = gen.generate(program)
    assert "a = 1" in output
    assert "a = 2" in output
    assert "else:" in output


# --- Fixture-based generation: POP / MVN operations ---


POP_SOURCE = (FIXTURES / "pop_ldm_op.pseudo").read_text()

EXPECTED_POP_PY = (
    "if ConditionPassed():\n"
    "    EncodingSpecificOperations()\n"
    "    address = SP\n"
    "    SP = (SP + (4 * BitCount(registers)))\n"
    "    for i in range(0, 14 + 1):\n"
    "        if (((registers >> i) & 1) == 1):\n"
    "            R[i] = MemA_read(ctx, address, 4)\n"
    "            address = (address + 4)\n"
    "    if (((registers >> 15) & 1) == 1):\n"
    "        LoadWritePC(MemA_read(ctx, address, 4))\n"
)


def test_python_pop_generation() -> None:
    program = parse(POP_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_POP_PY


# --- Python runtime integration tests (exec-compile) ---


# ---------------------------------------------------------------------------
# armruntime runtime — prepended to generated code before execution
# ---------------------------------------------------------------------------

_ARMLIB_PY = (
    Path(__file__).parent.parent
    / "src"
    / "arm_transpiller"
    / "armruntime"
    / "armruntime.py.template"
).read_text()

# ---------------------------------------------------------------------------
# Test-specific preambles (variables and types only)
# ---------------------------------------------------------------------------


_PREAMBLE = """\
R = [0] * 16
address = 0
SP = 0x1000
S = 0
Rd = 0
Rn = 0
d = 0
n = 0
i = 0
imm3 = 0
imm8 = 0
setflags = False
imm32 = 0
registers = 0
ctx = Context()
"""


def test_python_adc_immediate_decoder_compiles() -> None:
    program = parse(SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _PREAMBLE, ns)
    exec(code, ns)


def test_python_pop_compiles() -> None:
    program = parse(POP_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _PREAMBLE, ns)
    exec(code, ns)


# --- Fixture-based: MVN register operation ---


MVN_SOURCE = (FIXTURES / "mvn_register_op.pseudo").read_text()

EXPECTED_MVN_PY = (
    "if ConditionPassed():\n"
    "    EncodingSpecificOperations()\n"
    "    shifted, carry = Shift_C(R[m], shift_t, shift_n, ctx.apsr.C)\n"
    "    result = ((~shifted) & 0xffffffff)\n"
    "    R[d] = result\n"
    "    if setflags:\n"
    "        ctx.apsr.N = ((result >> 31) & 1)\n"
    "        ctx.apsr.Z = IsZeroBit(result)\n"
    "        ctx.apsr.C = carry\n"
    "        # APSR.V unchanged\n"
)


def test_python_mvn_register_op() -> None:
    program = parse(MVN_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_MVN_PY


_MVN_PREAMBLE = """\
R = [0] * 16
shifted = 0
carry = 0
result = 0
d = 0
m = 1
shift_t = 0
shift_n = 0
setflags = True

ctx = Context()
"""


def test_python_mvn_compiles() -> None:
    program = parse(MVN_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _MVN_PREAMBLE, ns)
    exec(code, ns)


# --- Fixture-based: LSR immediate / ADC register decoder variants ---


LSR_SOURCE = (FIXTURES / "lsr_immediate_decoder.pseudo").read_text()

EXPECTED_LSR_PY = (
    "d = UInt(Rd)\n"
    "m = UInt(Rm)\n"
    "setflags = (not (InITBlock(ctx)))\n"
    "_, shift_n = DecodeImmShift(0x1, imm5)\n"
)


def test_python_lsr_immediate_decoder() -> None:
    program = parse(LSR_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_LSR_PY


_LSR_PREAMBLE = """\
d = 0
m = 0
Rd = 0
Rm = 0
setflags = False
shift_n = 0
imm5 = 0
ctx = Context()
"""


def test_python_lsr_compiles() -> None:
    program = parse(LSR_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _LSR_PREAMBLE, ns)
    exec(code, ns)


ADC_REG_SOURCE = (FIXTURES / "adc_register_t2_decoder.pseudo").read_text()

EXPECTED_ADC_REG_PY = (
    "d = UInt(Rd)\n"
    "n = UInt(Rn)\n"
    "m = UInt(Rm)\n"
    "setflags = (S == 1)\n"
    "shift_t, shift_n = DecodeImmShift(type, concat_bits(imm3, imm2, 2))\n"
    "if ((((d == 13) or (d == 15)) or ((n == 13) or (n == 15)))"
    " or ((m == 13) or (m == 15))):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
)


def test_python_adc_register_decoder() -> None:
    program = parse(ADC_REG_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_ADC_REG_PY


_ADC_REG_PREAMBLE = """\
d = 0
n = 0
m = 0
Rd = 0
Rn = 0
Rm = 0
S = 0
setflags = False
shift_t = 0
shift_n = 0
type = 0
imm3 = 0
imm2 = 0
ctx = Context()
"""


def test_python_adc_register_compiles() -> None:
    program = parse(ADC_REG_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _ADC_REG_PREAMBLE, ns)
    exec(code, ns)


# --- Fixture-based: EOR / SUB / BL decoders ---


EOR_SOURCE = (FIXTURES / "eor_immediate_decoder.pseudo").read_text()

EXPECTED_EOR_PY = (
    "# EOR (immediate) — T1 encoding\n"
    "if ((Rd == 0xf) and (S == 1)):\n"
    '    ctx.sideeffect |= SIDEFFECT_SEE  # "TEQ (immediate)"\n'
    "d = UInt(Rd)\n"
    "n = UInt(Rn)\n"
    "setflags = (S == 1)\n"
    "imm32, carry = ThumbExpandImm_C(ctx, concat_bits(concat_bits(i, imm3, 3), imm8, 8)"
    ", ctx.apsr.C)\n"
    "if (((d == 13) or ((d == 15) and (S == 0))) or ((n == 13) or (n == 15))):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
)


def test_python_eor_immediate_decoder() -> None:
    program = parse(EOR_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_EOR_PY


_EOR_PREAMBLE = """\
R = [0] * 16
d = 0
n = 0
Rd = 0
Rn = 0
S = 0
setflags = False
i = 0
imm3 = 0
imm8 = 0
imm32 = 0
carry = 0

ctx = Context()
"""


def test_python_eor_compiles() -> None:
    program = parse(EOR_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _EOR_PREAMBLE, ns)
    exec(code, ns)


ADC_REG_TUPLE_SOURCE = (FIXTURES / "adc_register_t1_decoder.pseudo").read_text()

EXPECTED_ADC_REG_TUPLE_PY = (
    "d = UInt(Rdn)\n"
    "n = UInt(Rdn)\n"
    "m = UInt(Rm)\n"
    "setflags = (not (InITBlock(ctx)))\n"
    "shift_t, shift_n = (SRType_LSL, 0)\n"
)


def test_python_adc_register_tuple_decoder() -> None:
    program = parse(ADC_REG_TUPLE_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_ADC_REG_TUPLE_PY


_ADC_REG_TUPLE_PREAMBLE = """\
d = 0
n = 0
m = 0
Rdn = 0
Rm = 0
setflags = False
shift_t = 0
shift_n = 0
ctx = Context()
"""


def test_python_adc_register_tuple_compiles() -> None:
    program = parse(ADC_REG_TUPLE_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _ADC_REG_TUPLE_PREAMBLE, ns)
    exec(code, ns)


SUB_IMM_SOURCE = (FIXTURES / "sub_immediate_decoder.pseudo").read_text()

EXPECTED_SUB_IMM_PY = (
    "if ((Rd == 0xf) and (S == 1)):\n"
    '    ctx.sideeffect |= SIDEFFECT_SEE  # "CMP (immediate)"\n'
    "if (Rn == 0xd):\n"
    '    ctx.sideeffect |= SIDEFFECT_SEE  # "SUB (SP minus immediate)"\n'
    "d = UInt(Rd)\n"
    "n = UInt(Rn)\n"
    "setflags = (S == 1)\n"
    "imm32 = ThumbExpandImm(ctx, concat_bits(concat_bits(i, imm3, 3), imm8, 8))\n"
    "if (((d == 13) or ((d == 15) and (S == 0))) or (n == 15)):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
)


def test_python_sub_immediate_decoder() -> None:
    program = parse(SUB_IMM_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_SUB_IMM_PY


_SUB_IMM_PREAMBLE = """\
d = 0
n = 0
Rd = 0
Rn = 0
S = 0
setflags = False
i = 0
imm3 = 0
imm8 = 0
imm32 = 0
ctx = Context()
"""


def test_python_sub_immediate_compiles() -> None:
    program = parse(SUB_IMM_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _SUB_IMM_PREAMBLE, ns)
    exec(code, ns)


BL_SOURCE = (FIXTURES / "bl_decoder.pseudo").read_text()

EXPECTED_BL_PY = (
    "I1 = ((~((J1 ^ S) & 0x1)) & 0x1)\n"
    "I2 = ((~((J2 ^ S) & 0x1)) & 0x1)\n"
    "imm32 = SignExtend(concat_bits(concat_bits(concat_bits("
    "concat_bits(concat_bits(S, I1, 1), I2, 1), imm10, 10), "
    "imm11, 11), 0, 1), 25)\n"
    "if (InITBlock(ctx) and (not (LastInITBlock(ctx)))):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
)


def test_python_bl_decoder() -> None:
    program = parse(BL_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_BL_PY


_BL_PREAMBLE = """\
J1 = 0
J2 = 0
S = 0
imm10 = 0
imm11 = 0
I1 = 0
I2 = 0
imm32 = 0
ctx = Context()
"""


def test_python_bl_compiles() -> None:
    program = parse(BL_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _BL_PREAMBLE, ns)
    exec(code, ns)


B_T3_SOURCE = (FIXTURES / "b_t3_decoder.pseudo").read_text()

EXPECTED_B_T3_PY = (
    "if (((cond >> 1) & 0x7) == 0x7):\n"
    '    ctx.sideeffect |= SIDEFFECT_SEE  # "Related encodings"\n'
    "imm32 = SignExtend(concat_bits(concat_bits(concat_bits("
    "concat_bits(concat_bits(S, J2, 1), J1, 1), imm6, 6), "
    "imm11, 11), 0, 1), 21)\n"
    "if InITBlock(ctx):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
)


def test_python_b_t3_decoder() -> None:
    program = parse(B_T3_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_B_T3_PY


_B_T3_PREAMBLE = """\
cond = 0
S = 0
J1 = 0
J2 = 0
imm6 = 0
imm11 = 0
imm32 = 0
ctx = Context()
"""


def test_python_b_t3_compiles() -> None:
    program = parse(B_T3_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _B_T3_PREAMBLE, ns)
    exec(code, ns)


# --- Fixture-based: LDRH / POP_T3 / MRS_T1 decoders ---


LDRH_REG_SOURCE = (FIXTURES / "ldrh_register_decoder.pseudo").read_text()

EXPECTED_LDRH_REG_PY = (
    "if (Rn == 0xf):\n"
    '    ctx.sideeffect |= SIDEFFECT_SEE  # "LDRH (literal)"\n'
    "if (Rt == 0xf):\n"
    '    ctx.sideeffect |= SIDEFFECT_SEE  # "Related instructions"\n'
    "t = UInt(Rt)\n"
    "n = UInt(Rn)\n"
    "m = UInt(Rm)\n"
    "index = True\n"
    "add = True\n"
    "wback = False\n"
    "shift_t, shift_n = (SRType_LSL, UInt(imm2))\n"
    "if ((t == 13) or ((m == 13) or (m == 15))):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
)


def test_python_ldrh_register_decoder() -> None:
    program = parse(LDRH_REG_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_LDRH_REG_PY


_LDRH_REG_PREAMBLE = """\
t = 0
n = 0
m = 0
Rt = 0
Rn = 0
Rm = 0
index = 0
add = 0
wback = 0
imm2 = 0
shift_t = 0
shift_n = 0
"""


def test_python_ldrh_register_compiles() -> None:
    program = parse(LDRH_REG_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _LDRH_REG_PREAMBLE, ns)
    exec(code, ns)


POP_T3_SOURCE = (FIXTURES / "pop_t3_decoder.pseudo").read_text()

EXPECTED_POP_T3_PY = (
    "t = UInt(Rt)\n"
    "registers = Zeros(16)\n"
    "registers = (registers | (1 << t))\n"
    "UnalignedAllowed = True\n"
    "if ((t == 13) or (((t == 15) and InITBlock(ctx)) and "
    "(not (LastInITBlock(ctx))))):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
)


def test_python_pop_t3_decoder() -> None:
    program = parse(POP_T3_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_POP_T3_PY


_POP_T3_PREAMBLE = """\
t = 0
Rt = 0
registers = 0
UnalignedAllowed = 0
ctx = Context()
"""


def test_python_pop_t3_compiles() -> None:
    program = parse(POP_T3_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _POP_T3_PREAMBLE, ns)
    exec(code, ns)


MRS_T1_SOURCE = (FIXTURES / "mrs_t1_decoder.pseudo").read_text()

EXPECTED_MRS_T1_PY = (
    "d = UInt(Rd)\n"
    "if (((d == 13) or (d == 15)) or (not "
    "(((0 <= UInt(SYSm) <= 3) or (5 <= UInt(SYSm) <= 9) "
    "or (16 <= UInt(SYSm) <= 20))))):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
)


def test_python_mrs_t1_decoder() -> None:
    program = parse(MRS_T1_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_MRS_T1_PY


_MRS_T1_PREAMBLE = """\
d = 0
Rd = 0
SYSm = 0
"""


def test_python_mrs_t1_compiles() -> None:
    program = parse(MRS_T1_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _MRS_T1_PREAMBLE, ns)
    exec(code, ns)


# --- Fixture-based: ORR / AND / REV / STR operations ---


ORR_SOURCE = (FIXTURES / "orr_immediate_op.pseudo").read_text()

EXPECTED_ORR_PY = (
    "if ConditionPassed():\n"
    "    EncodingSpecificOperations()\n"
    "    result = ((R[n] | imm32) & 0xffffffff)\n"
    "    R[d] = result\n"
    "    if setflags:\n"
    "        ctx.apsr.N = ((result >> 31) & 1)\n"
    "        ctx.apsr.Z = IsZeroBit(result)\n"
    "        ctx.apsr.C = carry\n"
    "        # APSR.V unchanged\n"
)


def test_python_orr_immediate_op() -> None:
    program = parse(ORR_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_ORR_PY


_ORR_PREAMBLE = """\
R = [0] * 16
result = 0
d = 0
n = 0
imm32 = 0
setflags = True
carry = 0

ctx = Context()
"""


def test_python_orr_compiles() -> None:
    program = parse(ORR_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _ORR_PREAMBLE, ns)
    exec(code, ns)


AND_SOURCE = (FIXTURES / "and_register_op.pseudo").read_text()

EXPECTED_AND_PY = (
    "if ConditionPassed():\n"
    "    EncodingSpecificOperations()\n"
    "    shifted, carry = Shift_C(R[m], shift_t, shift_n, ctx.apsr.C)\n"
    "    result = ((R[n] & shifted) & 0xffffffff)\n"
    "    R[d] = result\n"
    "    if setflags:\n"
    "        ctx.apsr.N = ((result >> 31) & 1)\n"
    "        ctx.apsr.Z = IsZeroBit(result)\n"
    "        ctx.apsr.C = carry\n"
    "        # APSR.V unchanged\n"
)


def test_python_and_register_op() -> None:
    program = parse(AND_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_AND_PY


_AND_PREAMBLE = """\
R = [0] * 16
shifted = 0
carry = 0
result = 0
d = 0
m = 1
n = 0
shift_t = 0
shift_n = 0
setflags = True

ctx = Context()
"""


def test_python_and_compiles() -> None:
    program = parse(AND_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _AND_PREAMBLE, ns)
    exec(code, ns)


REV_T2_SOURCE = (FIXTURES / "rev_t2_decoder.pseudo").read_text()

EXPECTED_REV_T2_PY = (
    "if (not (Consistent(Rm))):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
    "d = UInt(Rd)\n"
    "m = UInt(Rm)\n"
    "if (((d == 13) or (d == 15)) or ((m == 13) or (m == 15))):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
)


def test_python_rev_t2_decoder() -> None:
    program = parse(REV_T2_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_REV_T2_PY


_REV_T2_PREAMBLE = """\
d = 0
m = 0
Rd = 0
Rm = 0
ctx = Context()
"""


def test_python_rev_t2_compiles() -> None:
    program = parse(REV_T2_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _REV_T2_PREAMBLE, ns)
    exec(code, ns)


STR_REG_SOURCE = (FIXTURES / "str_register_op.pseudo").read_text()

EXPECTED_STR_REG_PY = (
    "if ConditionPassed():\n"
    "    EncodingSpecificOperations()\n"
    "    offset = Shift(R[m], shift_t, shift_n, ctx.apsr.C)\n"
    "    address = (R[n] + offset)\n"
    "    MemU_write(ctx, address, 4, R[t])\n"
)


def test_python_str_register_op() -> None:
    program = parse(STR_REG_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_STR_REG_PY


_STR_REG_PREAMBLE = """\
offset = 0
address = 0
R = {
    0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0,
    8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 0, 14: 0, 15: 0,
}
m = 0
n = 0
t = 0
shift_t = 0
shift_n = 0
ctx = Context()
"""


def test_python_str_register_compiles() -> None:
    program = parse(STR_REG_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _STR_REG_PREAMBLE, ns)
    exec(code, ns)


# ---------------------------------------------------------------------------
# Fixture-based: VPU decoders (VABS / VCVT / VRINTA / VSEL / RSB) + field_widths
# ---------------------------------------------------------------------------


VABS_T1_SOURCE = (FIXTURES / "vabs_t1_decoder.pseudo").read_text()

EXPECTED_VABS_T1_PY = (
    "dp_operation = (sz == 1)\n"
    "d = (UInt(concat_bits(D, Vd, 4))"
    " if dp_operation else UInt(concat_bits(Vd, D, 1)))\n"
    "m = (UInt(concat_bits(M, Vm, 4))"
    " if dp_operation else UInt(concat_bits(Vm, M, 1)))\n"
)


def test_python_vabs_t1_decoder() -> None:
    program = parse(VABS_T1_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VABS_T1_PY


_VABS_T1_PREAMBLE = """\
dp_operation = 0
sz = 0
d = 0
m = 0
D = 0
Vd = 0
M = 0
Vm = 0
"""


def test_python_vabs_t1_compiles() -> None:
    program = parse(VABS_T1_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _VABS_T1_PREAMBLE, ns)
    exec(code, ns)


VCVT_T1_SOURCE = (FIXTURES / "vcvt_t1_decoder.pseudo").read_text()

EXPECTED_VCVT_T1_PY = (
    "if ((opc2 != 0x0) and (not (((opc2 & 0x6) == 0x4)))):\n"
    '    ctx.sideeffect |= SIDEFFECT_SEE  # "Related encodings"\n'
    "to_integer = (((opc2 >> 2) & 1) == 1)\n"
    "dp_operation = (sz == 1)\n"
    "if to_integer:\n"
    "    unsigned = (((opc2 >> 0) & 1) == 0)\n"
    "    round_zero = (op == 1)\n"
    "    d = UInt(concat_bits(Vd, D, 1))\n"
    "    m = (UInt(concat_bits(M, Vm, 4))"
    " if dp_operation else UInt(concat_bits(Vm, M, 1)))\n"
    "else:\n"
    "    unsigned = (op == 0)\n"
    "    round_nearest = False\n"
    "    m = UInt(concat_bits(Vm, M, 1))\n"
    "    d = (UInt(concat_bits(D, Vd, 4))"
    " if dp_operation else UInt(concat_bits(Vd, D, 1)))\n"
)


def test_python_vcvt_t1_decoder() -> None:
    program = parse(VCVT_T1_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VCVT_T1_PY


_VCVT_T1_PREAMBLE = """\
opc2 = 0
op = 0
sz = 0
to_integer = 0
dp_operation = 0
unsigned = 0
round_zero = 0
round_nearest = 0
d = 0
m = 0
D = 0
Vd = 0
M = 0
Vm = 0
"""  # noqa: E501


def test_python_vcvt_t1_compiles() -> None:
    program = parse(VCVT_T1_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _VCVT_T1_PREAMBLE, ns)
    exec(code, ns)


VRINTA_T1_SOURCE = (FIXTURES / "vrinta_t1_decoder.pseudo").read_text()

EXPECTED_VRINTA_T1_PY = (
    "if InITBlock(ctx):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
    "dp_operation = (sz == 1)\n"
    "if RM == 0x0:  # Round to nearest, with ties away\n"
    "    rmode = 0x1\n"
    "    away = True\n"
    "elif RM == 0x1:  # Round to nearest, with ties to even\n"
    "    rmode = 0x0\n"
    "    away = False\n"
    "elif RM == 0x2:  # Round towards Plus Infinity\n"
    "    rmode = 0x1\n"
    "    away = False\n"
    "elif RM == 0x3:  # Round towards Minus Infinity\n"
    "    rmode = 0x2\n"
    "    away = False\n"
    "d = (UInt(concat_bits(D, Vd, 4))"
    " if dp_operation else UInt(concat_bits(Vd, D, 1)))\n"
    "m = (UInt(concat_bits(M, Vm, 4))"
    " if dp_operation else UInt(concat_bits(Vm, M, 1)))\n"
)


def test_python_vrinta_t1_decoder() -> None:
    program = parse(VRINTA_T1_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VRINTA_T1_PY


_VRINTA_T1_PREAMBLE = """\
RM = 0
sz = 0
dp_operation = 0
rmode = 0
away = 0
d = 0
m = 0
D = 0
Vd = 0
M = 0
Vm = 0
ctx = Context()
"""


def test_python_vrinta_t1_compiles() -> None:
    program = parse(VRINTA_T1_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _VRINTA_T1_PREAMBLE, ns)
    exec(code, ns)


VSEL_T1_SOURCE = (FIXTURES / "vsel_t1_decoder.pseudo").read_text()

EXPECTED_VSEL_T1_PY = (
    "if InITBlock(ctx):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
    "dp_operation = (sz == 1)\n"
    "cond = concat_bits(concat_bits(cc, (((cc >> 1) & 1) ^ ((cc >> 0) & 1)), 1)"
    ", 0, 1)\n"
    "d = (UInt(concat_bits(D, Vd, 4))"
    " if dp_operation else UInt(concat_bits(Vd, D, 1)))\n"
    "n = (UInt(concat_bits(N, Vn, 4))"
    " if dp_operation else UInt(concat_bits(Vn, N, 1)))\n"
    "m = (UInt(concat_bits(M, Vm, 4))"
    " if dp_operation else UInt(concat_bits(Vm, M, 1)))\n"
)


def test_python_vsel_t1_decoder() -> None:
    program = parse(VSEL_T1_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VSEL_T1_PY


_VSEL_T1_PREAMBLE = """\
sz = 0
cc = 0
dp_operation = 0
cond = 0
d = 0
n = 0
m = 0
D = 0
Vd = 0
N = 0
Vn = 0
M = 0
Vm = 0
ctx = Context()
"""


def test_python_vsel_t1_compiles() -> None:
    program = parse(VSEL_T1_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _VSEL_T1_PREAMBLE, ns)
    exec(code, ns)


VNMLA_T1_SOURCE = (FIXTURES / "vnmla_t1_decoder.pseudo").read_text()

EXPECTED_VNMLA_T1_PY = (
    "type = (VFPNegMul_VNMLA if (op == 1) else VFPNegMul_VNMLS)\n"
    "dp_operation = (sz == 1)\n"
    "d = (UInt(concat_bits(D, Vd, 4))"
    " if dp_operation else UInt(concat_bits(Vd, D, 1)))\n"
    "n = (UInt(concat_bits(N, Vn, 4))"
    " if dp_operation else UInt(concat_bits(Vn, N, 1)))\n"
    "m = (UInt(concat_bits(M, Vm, 4))"
    " if dp_operation else UInt(concat_bits(Vm, M, 1)))\n"
)


def test_python_vnmla_t1_decoder() -> None:
    program = parse(VNMLA_T1_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VNMLA_T1_PY


_VNMLA_T1_PREAMBLE = """\
op = 0
sz = 0
type = 0
dp_operation = 0
d = 0
n = 0
m = 0
D = 0
Vd = 0
N = 0
Vn = 0
M = 0
Vm = 0
ctx = Context()
"""


def test_python_vnmla_t1_compiles() -> None:
    program = parse(VNMLA_T1_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _VNMLA_T1_PREAMBLE, ns)
    exec(code, ns)


VLDM_T1_SOURCE = (FIXTURES / "vldm_t1_decoder.pseudo").read_text()

EXPECTED_VLDM_T1_PY = (
    "if (((P == 0) and (U == 0)) and (W == 0)):\n"
    '    ctx.sideeffect |= SIDEFFECT_SEE  # "Related encodings"\n'
    "if ((((P == 0) and (U == 1)) and (W == 1)) and (Rn == 0xd)):\n"
    '    ctx.sideeffect |= SIDEFFECT_SEE  # "VPOP"\n'
    "if ((P == 1) and (W == 0)):\n"
    '    ctx.sideeffect |= SIDEFFECT_SEE  # "VLDR"\n'
    "if (((imm8 >> 0) & 1) == 1):\n"
    '    ctx.sideeffect |= SIDEFFECT_SEE  # "FLDMX"\n'
    "if ((P == U) and (W == 1)):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNDEFINED\n"
    "# Remaining combinations are PUW = 010 (IA without !)"
    ", 011 (IA with !), 101 (DB with !)\n"
    "single_regs = False\n"
    "add = (U == 1)\n"
    "wback = (W == 1)\n"
    "d = UInt(concat_bits(D, Vd, 4))\n"
    "n = UInt(Rn)\n"
    "imm32 = ZeroExtend(concat_bits(imm8, 0x0, 2), 32)\n"
    "regs = (UInt(imm8) // 2)\n"
    "if (n == 15):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
    "if (((regs == 0) or (regs > 16)) or ((d + regs) > 32)):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
    "if (VFPSmallRegisterBank() and ((d + regs) > 16)):\n"
    "    ctx.sideeffect |= SIDEFFECT_UNPREDICTABLE\n"
)


def test_python_vldm_t1_decoder() -> None:
    program = parse(VLDM_T1_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VLDM_T1_PY


_VLDM_T1_PREAMBLE = """\
P = 0
U = 0
W = 0
Rn = 0
imm8 = 0
D = 0
Vd = 0
single_regs = False
add = False
wback = False
d = 0
n = 0
imm32 = 0
regs = 0
ctx = Context()
"""


def test_python_vldm_t1_compiles() -> None:
    program = parse(VLDM_T1_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _VLDM_T1_PREAMBLE, ns)
    exec(code, ns)


VRINTZ_T1_SOURCE = (FIXTURES / "vrintz_t1_decoder.pseudo").read_text()

EXPECTED_VRINTZ_T1_PY = (
    "dp_operation = (sz == 1)\n"
    "rmode = (0x3 if (op == 1) else ((ctx.fpscr >> 22) & 0x3))\n"
    "d = (UInt(concat_bits(D, Vd, 4))"
    " if dp_operation else UInt(concat_bits(Vd, D, 1)))\n"
    "m = (UInt(concat_bits(M, Vm, 4))"
    " if dp_operation else UInt(concat_bits(Vm, M, 1)))\n"
)


def test_python_vrintz_t1_decoder() -> None:
    program = parse(VRINTZ_T1_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VRINTZ_T1_PY


_VRINTZ_T1_PREAMBLE = """\
sz = 0
op = 0
dp_operation = 0
rmode = 0
d = 0
m = 0
D = 0
Vd = 0
M = 0
Vm = 0
ctx = Context()
ctx.fpscr = 0
"""


def test_python_vrintz_t1_compiles() -> None:
    program = parse(VRINTZ_T1_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _VRINTZ_T1_PREAMBLE, ns)
    exec(code, ns)


RSB_IMM_T1_SOURCE = (FIXTURES / "rsb_immediate_t1_decoder.pseudo").read_text()

EXPECTED_RSB_IMM_T1_PY = (
    "d = UInt(Rd)\n"
    "n = UInt(Rn)\n"
    "setflags = (not (InITBlock(ctx)))\n"
    "imm32 = Zeros(32)\n"
    "# immediate = #0\n"
)


def test_python_rsb_immediate_t1_decoder() -> None:
    program = parse(RSB_IMM_T1_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_RSB_IMM_T1_PY


_RSB_IMM_T1_PREAMBLE = """\
d = 0
n = 0
Rd = 0
Rn = 0
setflags = False
imm32 = 0
ctx = Context()
"""


def test_python_rsb_immediate_t1_compiles() -> None:
    program = parse(RSB_IMM_T1_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _RSB_IMM_T1_PREAMBLE, ns)
    exec(code, ns)


# --- input_types constructor / override tests ---


def test_python_input_types_overrides_known_name() -> None:
    gen = PythonGenerator(input_types={"Rdn": "bits3"})
    program = parse("x = UInt(Rdn);")
    output = gen.generate(program)
    assert output == "x = UInt(Rdn)\n"


def test_python_input_types_supplies_unknown_name() -> None:
    gen = PythonGenerator(input_types={"Rdm": "bits3"})
    program = parse("x = UInt(Rdm);")
    output = gen.generate(program)
    assert output == "x = UInt(Rdm)\n"


def test_python_input_types_overrides_imm_pattern() -> None:
    gen = PythonGenerator(input_types={"imm8": "bits16"})
    program = parse("x = SignExtend(imm8, 32);")
    output = gen.generate(program)
    assert "SignExtend(imm8, 16)" in output


def test_python_input_types_accepts_arm_type_objects() -> None:
    from arm_transpiller.known_types import uint

    gen = PythonGenerator(input_types={"imm8": uint(16)})
    program = parse("x = SignExtend(imm8, 32);")
    assert "SignExtend(imm8, 16)" in gen.generate(program)


def test_python_input_types_bool_masks_to_one_bit() -> None:
    gen = PythonGenerator(input_types={"flag": "bool"})
    program = parse("x = NOT(flag);")
    assert gen.generate(program) == "x = ((~flag) & 0x1)\n"


def test_python_concat_width_comes_from_input_types() -> None:
    gen = PythonGenerator(input_types={"a": "bits5", "b": "bits7"})
    program = parse("x = SignExtend(a:b, 32);")
    output = gen.generate(program)
    assert "concat_bits(a, b, 7)" in output
    assert "SignExtend(concat_bits(a, b, 7), 12)" in output


def test_python_without_input_types_unknown_name_raises() -> None:
    from arm_transpiller.known_types import UnknownVariableTypeError

    gen = PythonGenerator()
    program = parse("x = SignExtend(Rdm, 32);")
    with pytest.raises(UnknownVariableTypeError, match="Rdm"):
        gen.generate(program)


def test_python_unknown_function_return_type_raises() -> None:
    from arm_transpiller.known_types import UnknownFunctionTypeError

    gen = PythonGenerator()
    program = parse("x = SignExtend(FancyDecode(Rd), 32);")
    with pytest.raises(UnknownFunctionTypeError, match="FancyDecode"):
        gen.generate(program)


# --- Signedness: Python integers are already signed, so no casts are emitted ---


def test_python_signed_operators_need_no_casts() -> None:
    gen = PythonGenerator()
    program = parse(
        "off = SInt(R[n]); x = off < 0; y = off DIV imm3; z = off MOD imm3;"
    )
    output = gen.generate(program)
    assert output == (
        "off = SInt(R[n], 32)\nx = (off < 0)\ny = (off // imm3)\nz = (off % imm3)\n"
    )


def test_python_sint_gets_the_operand_width() -> None:
    gen = PythonGenerator()
    assert gen.generate(parse("x = SInt(imm8);")) == "x = SInt(imm8, 8)\n"


def test_python_sint_keeps_an_explicit_width() -> None:
    gen = PythonGenerator()
    assert gen.generate(parse("x = SInt(imm8, 32);")) == "x = SInt(imm8, 32)\n"


# --- VMOV (immediate) T1 ---

VMOV_IMM_T1_SOURCE = (FIXTURES / "vmov_immediate_t1_decoder.pseudo").read_text()

EXPECTED_VMOV_IMM_T1_PY = (
    "dp_operation = (sz == 1)\n"
    "if dp_operation:\n"
    "    d = UInt(concat_bits(D, Vd, 4))\n"
    "    imm64 = VFPExpandImm(concat_bits(imm4H, imm4L, 4), 64)\n"
    "else:\n"
    "    d = UInt(concat_bits(Vd, D, 1))\n"
    "    imm32 = VFPExpandImm(concat_bits(imm4H, imm4L, 4), 32)\n"
)


def test_python_vmov_immediate_t1_decoder() -> None:
    program = parse(VMOV_IMM_T1_SOURCE)
    gen = PythonGenerator()
    output = gen.generate(program)
    assert output == EXPECTED_VMOV_IMM_T1_PY


_VMOV_IMM_T1_PREAMBLE = """\
dp_operation = 0
sz = 0
d = 0
imm64 = 0
imm32 = 0
D = 0
Vd = 0
imm4H = 0
imm4L = 0
"""


def test_python_vmov_immediate_t1_compiles() -> None:
    program = parse(VMOV_IMM_T1_SOURCE)
    gen = PythonGenerator()
    code = gen.generate(program)

    ns: dict[str, object] = {}
    exec(_ARMLIB_PY + _VMOV_IMM_T1_PREAMBLE, ns)
    exec(code, ns)
