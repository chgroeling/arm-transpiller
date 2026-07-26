from __future__ import annotations

from pathlib import Path

import pytest
from lark.exceptions import UnexpectedInput

from arm_transpiller.analysis.input_variables import extract_input_variables
from arm_transpiller.analysis.output_variables import extract_output_variables
from arm_transpiller.ast_nodes import (
    ArrayAccess,
    Assignment,
    BinaryOp,
    BitIndex,
    BitLiteral,
    BitStringLiteral,
    Comment,
    DestructureAssignment,
    ForLoop,
    FunctionCall,
    HexLiteral,
    Identifier,
    IfThen,
    InExpr,
    IntegerLiteral,
    Program,
    RegisterAccess,
    StatementCall,
    TupleLiteral,
    UnaryOp,
    Unpredictable,
)
from arm_transpiller.parser import parse

FIXTURES = Path(__file__).parent / "fixtures"


# --- Fixture-based instruction decoder parsing ---


def test_parse_adc_immediate_decoder() -> None:
    source = (FIXTURES / "adc_immediate_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 5

    s0: Assignment = program.statements[0]
    assert isinstance(s0, Assignment)
    assert s0.target == "d"
    assert isinstance(s0.value, FunctionCall)
    assert s0.value.name == "UInt"
    assert len(s0.value.args) == 1
    assert isinstance(s0.value.args[0], Identifier)
    assert s0.value.args[0].name == "Rd"

    s1: Assignment = program.statements[1]
    assert isinstance(s1, Assignment)
    assert s1.target == "n"
    assert isinstance(s1.value, FunctionCall)
    assert s1.value.name == "UInt"
    assert isinstance(s1.value.args[0], Identifier)
    assert s1.value.args[0].name == "Rn"

    s2: Assignment = program.statements[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "setflags"
    assert isinstance(s2.value, BinaryOp)
    assert s2.value.op == "=="
    assert isinstance(s2.value.left, Identifier)
    assert s2.value.left.name == "S"
    assert isinstance(s2.value.right, BitLiteral)
    assert s2.value.right.value == 1

    s3: Assignment = program.statements[3]
    assert isinstance(s3, Assignment)
    assert s3.target == "imm32"
    assert isinstance(s3.value, FunctionCall)
    assert s3.value.name == "ThumbExpandImm"
    assert len(s3.value.args) == 1
    concat = s3.value.args[0]
    assert isinstance(concat, BinaryOp)
    assert concat.op == ":"
    assert isinstance(concat.left, BinaryOp)
    assert concat.left.op == ":"
    assert isinstance(concat.left.left, Identifier)
    assert concat.left.left.name == "i"
    assert isinstance(concat.left.right, Identifier)
    assert concat.left.right.name == "imm3"
    assert isinstance(concat.right, Identifier)
    assert concat.right.name == "imm8"

    s4: IfThen = program.statements[4]
    assert isinstance(s4, IfThen)
    assert isinstance(s4.condition, BinaryOp)
    assert s4.condition.op == "||"
    assert isinstance(s4.condition.left, InExpr)
    assert isinstance(s4.condition.left.left, Identifier)
    assert s4.condition.left.left.name == "d"
    assert len(s4.condition.left.set.elements) == 2
    assert isinstance(s4.condition.right, InExpr)
    assert isinstance(s4.condition.right.left, Identifier)
    assert s4.condition.right.left.name == "n"
    assert len(s4.then_body) == 1
    assert isinstance(s4.then_body[0], Unpredictable)
    assert s4.else_body is None


# --- Basic literal and expression parsing ---


def test_parse_bit_literal() -> None:
    program = parse("x = '0';\n")
    assert isinstance(program.statements[0], Assignment)
    val = program.statements[0].value
    assert isinstance(val, BitLiteral)
    assert val.value == 0


def test_parse_hex_literal() -> None:
    program = parse("x = 0x1A;\n")
    assert isinstance(program.statements[0], Assignment)
    val = program.statements[0].value
    assert isinstance(val, HexLiteral)
    assert val.value == 26


def test_parse_integer_literal() -> None:
    program = parse("x = 42;\n")
    assert isinstance(program.statements[0], Assignment)
    val = program.statements[0].value
    assert isinstance(val, IntegerLiteral)
    assert val.value == 42


def test_parse_undefined() -> None:
    program = parse("UNDEFINED;\n")
    assert len(program.statements) == 1
    from arm_transpiller.ast_nodes import Undefined

    assert isinstance(program.statements[0], Undefined)


def test_parse_if_else() -> None:
    program = parse("if x == 1 then a = 1; else a = 2;\n")
    stmt = program.statements[0]
    assert isinstance(stmt, IfThen)
    assert stmt.else_body is not None
    assert len(stmt.else_body) == 1


def test_parse_multiple_statements_one_line() -> None:
    program = parse("a = 1; b = 2; c = 3;\n")
    assert len(program.statements) == 3


# --- Fixture-based instruction operation parsing ---


def test_parse_pop_fixture() -> None:
    source = (FIXTURES / "pop_ldm_op.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 1

    outer_if = program.statements[0]
    assert isinstance(outer_if, IfThen)

    assert isinstance(outer_if.condition, FunctionCall)
    assert outer_if.condition.name == "ConditionPassed"
    assert len(outer_if.condition.args) == 0
    assert outer_if.else_body is None
    assert len(outer_if.then_body) == 5

    s0 = outer_if.then_body[0]
    assert isinstance(s0, StatementCall)
    assert s0.name == "EncodingSpecificOperations"
    assert len(s0.args) == 0

    s1 = outer_if.then_body[1]
    assert isinstance(s1, Assignment)
    assert s1.target == "address"
    assert isinstance(s1.value, Identifier)
    assert s1.value.name == "SP"

    s2 = outer_if.then_body[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "SP"

    s3 = outer_if.then_body[3]
    assert isinstance(s3, ForLoop)
    assert s3.variable == "i"
    assert isinstance(s3.start, IntegerLiteral)
    assert s3.start.value == 0
    assert isinstance(s3.end, IntegerLiteral)
    assert s3.end.value == 14
    assert len(s3.body) == 1

    inner_if = s3.body[0]
    assert isinstance(inner_if, IfThen)
    assert isinstance(inner_if.condition, BinaryOp)
    assert inner_if.condition.op == "=="
    assert isinstance(inner_if.condition.left, BitIndex)
    assert inner_if.condition.left.name == "registers"
    assert isinstance(inner_if.condition.left.index, Identifier)
    assert inner_if.condition.left.index.name == "i"
    assert isinstance(inner_if.condition.right, BitLiteral)
    assert inner_if.condition.right.value == 1
    assert len(inner_if.then_body) == 2

    inner_s0 = inner_if.then_body[0]
    assert isinstance(inner_s0, Assignment)
    assert isinstance(inner_s0.target, RegisterAccess)
    assert isinstance(inner_s0.target.index, Identifier)
    assert inner_s0.target.index.name == "i"
    assert isinstance(inner_s0.value, ArrayAccess)
    assert inner_s0.value.name == "MemA"
    assert len(inner_s0.value.args) == 2

    inner_s1 = inner_if.then_body[1]
    assert isinstance(inner_s1, Assignment)
    assert inner_s1.target == "address"

    s4 = outer_if.then_body[4]
    assert isinstance(s4, IfThen)
    assert isinstance(s4.condition, BinaryOp)
    assert s4.condition.op == "=="
    assert isinstance(s4.condition.left, BitIndex)
    assert s4.condition.left.name == "registers"
    assert isinstance(s4.condition.left.index, IntegerLiteral)
    assert s4.condition.left.index.value == 15
    assert isinstance(s4.condition.right, BitLiteral)
    assert s4.condition.right.value == 1
    assert len(s4.then_body) == 1

    load_stmt = s4.then_body[0]
    assert isinstance(load_stmt, StatementCall)
    assert load_stmt.name == "LoadWritePC"
    assert len(load_stmt.args) == 1
    assert isinstance(load_stmt.args[0], ArrayAccess)
    assert load_stmt.args[0].name == "MemA"


# --- Comment handling (standalone, inline, when-clause) ---


def test_parse_comment_standalone() -> None:
    program = parse("// a comment\n")
    assert len(program.statements) == 1
    cmt = program.statements[0]
    assert isinstance(cmt, Comment)
    assert cmt.text == "a comment"


def test_parse_comment_inline() -> None:
    program = parse("x = 1; // inline comment\n")
    assert len(program.statements) == 2
    assert isinstance(program.statements[0], Assignment)
    cmt = program.statements[1]
    assert isinstance(cmt, Comment)
    assert cmt.text == "inline comment"


def test_parse_when_comment_inline() -> None:
    from arm_transpiller.ast_nodes import CaseOf

    program = parse("case RM\n    when '00' // ties away\n        rmode = '01';\n")
    case_of = program.statements[0]
    assert isinstance(case_of, CaseOf)
    assert len(case_of.clauses) == 1
    clause = case_of.clauses[0]
    assert clause.comment == "ties away"
    assert len(clause.body) == 1
    assert isinstance(clause.body[0], Assignment)


def test_parse_when_comment_above_clause() -> None:
    from arm_transpiller.ast_nodes import CaseOf

    program = parse("case RM\n    // ties away\n    when '00'\n        rmode = '01';\n")
    case_of = program.statements[0]
    assert isinstance(case_of, CaseOf)
    assert case_of.clauses[0].comment == "ties away"
    assert case_of.else_body is None


def test_parse_when_inline_comment_wins_over_comment_above() -> None:
    from arm_transpiller.ast_nodes import CaseOf

    program = parse(
        "case RM\n    // section\n    when '00' // ties away\n        rmode = '01';\n"
    )
    case_of = program.statements[0]
    assert isinstance(case_of, CaseOf)
    assert case_of.clauses[0].comment == "ties away"


def test_parse_when_comment_inline_keeps_body_comment() -> None:
    from arm_transpiller.ast_nodes import CaseOf

    program = parse(
        "case RM\n"
        "    when '00' // ties away\n"
        "        // body note\n"
        "        rmode = '01';\n"
    )
    case_of = program.statements[0]
    assert isinstance(case_of, CaseOf)
    clause = case_of.clauses[0]
    assert clause.comment == "ties away"
    assert len(clause.body) == 2
    body_comment = clause.body[0]
    assert isinstance(body_comment, Comment)
    assert body_comment.text == "body note"
    assert isinstance(clause.body[1], Assignment)


# --- Operator disambiguation: NOT, register access, identifiers ---


def test_register_access_is_not_array_access() -> None:
    """Only an exact ``R`` is the register file; ``Rd[…]`` is an array."""
    reg = parse("x = R[d];").statements[0]
    assert isinstance(reg, Assignment)
    assert isinstance(reg.value, RegisterAccess)

    arr = parse("x = Rd[1];").statements[0]
    assert isinstance(arr, Assignment)
    assert isinstance(arr.value, ArrayAccess)
    assert arr.value.name == "Rd"


def test_not_is_an_operator_not_a_callee() -> None:
    """``NOT(x)`` is a unary operator; only a longer name is a call."""
    unary = parse("x = NOT(y);").statements[0]
    assert isinstance(unary, Assignment)
    assert isinstance(unary.value, UnaryOp)
    assert unary.value.op == "NOT"

    call = parse("x = NOTFLAG(y);").statements[0]
    assert isinstance(call, Assignment)
    assert isinstance(call.value, FunctionCall)
    assert call.value.name == "NOTFLAG"


def test_word_operators_require_a_word_boundary() -> None:
    """``NOTHING`` is an identifier, not ``NOT HING``."""
    ident = parse("x = NOTHING;").statements[0]
    assert isinstance(ident, Assignment)
    assert isinstance(ident.value, Identifier)
    assert ident.value.name == "NOTHING"

    with pytest.raises(UnexpectedInput):
        parse("x = a ORDER;")


# --- Fixture-based: MVN register operation ---


def test_parse_mvn_register_op() -> None:
    from arm_transpiller.ast_nodes import FieldAccess

    source = (FIXTURES / "mvn_register_op.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 1

    outer_if = program.statements[0]
    assert isinstance(outer_if, IfThen)
    assert isinstance(outer_if.condition, FunctionCall)
    assert outer_if.condition.name == "ConditionPassed"
    assert len(outer_if.then_body) == 5

    s0 = outer_if.then_body[0]
    assert isinstance(s0, StatementCall)
    assert s0.name == "EncodingSpecificOperations"

    s1 = outer_if.then_body[1]
    assert isinstance(s1, DestructureAssignment)
    assert s1.targets == ["shifted", "carry"]
    assert isinstance(s1.value, FunctionCall)
    assert s1.value.name == "Shift_C"
    assert len(s1.value.args) == 4
    assert isinstance(s1.value.args[0], RegisterAccess)
    assert isinstance(s1.value.args[0].index, Identifier)
    assert s1.value.args[0].index.name == "m"
    assert isinstance(s1.value.args[3], FieldAccess)
    assert s1.value.args[3].base == "APSR"
    assert s1.value.args[3].field == "C"

    s2 = outer_if.then_body[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "result"
    assert isinstance(s2.value, UnaryOp)
    assert s2.value.op == "NOT"

    s3 = outer_if.then_body[3]
    assert isinstance(s3, Assignment)
    assert isinstance(s3.target, RegisterAccess)
    assert isinstance(s3.target.index, Identifier)
    assert s3.target.index.name == "d"
    assert isinstance(s3.value, Identifier)
    assert s3.value.name == "result"

    s4 = outer_if.then_body[4]
    assert isinstance(s4, IfThen)
    assert isinstance(s4.condition, Identifier)
    assert s4.condition.name == "setflags"
    assert len(s4.then_body) == 4

    inner_s0 = s4.then_body[0]
    assert isinstance(inner_s0, Assignment)
    assert isinstance(inner_s0.target, FieldAccess)
    assert inner_s0.target.base == "APSR"
    assert inner_s0.target.field == "N"
    assert isinstance(inner_s0.value, BitIndex)
    assert inner_s0.value.name == "result"
    assert isinstance(inner_s0.value.index, IntegerLiteral)
    assert inner_s0.value.index.value == 31

    inner_s1 = s4.then_body[1]
    assert isinstance(inner_s1, Assignment)
    assert isinstance(inner_s1.target, FieldAccess)
    assert inner_s1.target.base == "APSR"
    assert inner_s1.target.field == "Z"
    assert isinstance(inner_s1.value, FunctionCall)
    assert inner_s1.value.name == "IsZeroBit"

    inner_s2 = s4.then_body[2]
    assert isinstance(inner_s2, Assignment)
    assert isinstance(inner_s2.target, FieldAccess)
    assert inner_s2.target.base == "APSR"
    assert inner_s2.target.field == "C"
    assert isinstance(inner_s2.value, Identifier)
    assert inner_s2.value.name == "carry"

    inner_s3 = s4.then_body[3]
    assert isinstance(inner_s3, Comment)
    assert inner_s3.text == "APSR.V unchanged"


# --- Fixture-based: LSR / ADC register decoder variants ---


def test_parse_lsr_immediate_decoder() -> None:
    source = (FIXTURES / "lsr_immediate_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 4

    s0: Assignment = program.statements[0]
    assert isinstance(s0, Assignment)
    assert s0.target == "d"
    assert isinstance(s0.value, FunctionCall)
    assert s0.value.name == "UInt"
    assert isinstance(s0.value.args[0], Identifier)
    assert s0.value.args[0].name == "Rd"

    s1: Assignment = program.statements[1]
    assert isinstance(s1, Assignment)
    assert s1.target == "m"
    assert isinstance(s1.value, FunctionCall)
    assert s1.value.name == "UInt"
    assert isinstance(s1.value.args[0], Identifier)
    assert s1.value.args[0].name == "Rm"

    s2: Assignment = program.statements[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "setflags"
    assert isinstance(s2.value, UnaryOp)
    assert s2.value.op == "!"
    assert isinstance(s2.value.operand, FunctionCall)
    assert s2.value.operand.name == "InITBlock"
    assert s2.value.operand.args == []

    s3: DestructureAssignment = program.statements[3]
    assert isinstance(s3, DestructureAssignment)
    assert s3.targets == [None, "shift_n"]
    assert isinstance(s3.value, FunctionCall)
    assert s3.value.name == "DecodeImmShift"
    assert len(s3.value.args) == 2
    assert isinstance(s3.value.args[0], BitStringLiteral)
    assert s3.value.args[0].value == "01"
    assert isinstance(s3.value.args[1], Identifier)
    assert s3.value.args[1].name == "imm5"


def test_parse_adc_register_decoder() -> None:
    source = (FIXTURES / "adc_register_t2_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 6

    s0: Assignment = program.statements[0]
    assert isinstance(s0, Assignment)
    assert s0.target == "d"
    assert isinstance(s0.value, FunctionCall)
    assert s0.value.name == "UInt"
    assert isinstance(s0.value.args[0], Identifier)
    assert s0.value.args[0].name == "Rd"

    s1: Assignment = program.statements[1]
    assert isinstance(s1, Assignment)
    assert s1.target == "n"
    assert isinstance(s1.value, FunctionCall)
    assert s1.value.name == "UInt"
    assert isinstance(s1.value.args[0], Identifier)
    assert s1.value.args[0].name == "Rn"

    s2: Assignment = program.statements[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "m"
    assert isinstance(s2.value, FunctionCall)
    assert s2.value.name == "UInt"
    assert isinstance(s2.value.args[0], Identifier)
    assert s2.value.args[0].name == "Rm"

    s3: Assignment = program.statements[3]
    assert isinstance(s3, Assignment)
    assert s3.target == "setflags"
    assert isinstance(s3.value, BinaryOp)
    assert s3.value.op == "=="
    assert isinstance(s3.value.left, Identifier)
    assert s3.value.left.name == "S"
    assert isinstance(s3.value.right, BitLiteral)
    assert s3.value.right.value == 1

    s4: DestructureAssignment = program.statements[4]
    assert isinstance(s4, DestructureAssignment)
    assert s4.targets == ["shift_t", "shift_n"]
    assert isinstance(s4.value, FunctionCall)
    assert s4.value.name == "DecodeImmShift"
    assert len(s4.value.args) == 2
    assert isinstance(s4.value.args[0], Identifier)
    assert s4.value.args[0].name == "type"
    assert isinstance(s4.value.args[1], BinaryOp)
    assert s4.value.args[1].op == ":"
    assert isinstance(s4.value.args[1].left, Identifier)
    assert s4.value.args[1].left.name == "imm3"
    assert isinstance(s4.value.args[1].right, Identifier)
    assert s4.value.args[1].right.name == "imm2"

    s5: IfThen = program.statements[5]
    assert isinstance(s5, IfThen)
    assert isinstance(s5.condition, BinaryOp)
    assert s5.condition.op == "||"
    assert len(s5.then_body) == 1
    assert isinstance(s5.then_body[0], Unpredictable)


def test_parse_adc_register_tuple_decoder() -> None:
    source = (FIXTURES / "adc_register_t1_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 5

    s0: Assignment = program.statements[0]
    assert isinstance(s0, Assignment)
    assert s0.target == "d"
    assert isinstance(s0.value, FunctionCall)
    assert s0.value.name == "UInt"
    assert isinstance(s0.value.args[0], Identifier)
    assert s0.value.args[0].name == "Rdn"

    s1: Assignment = program.statements[1]
    assert isinstance(s1, Assignment)
    assert s1.target == "n"
    assert isinstance(s1.value, FunctionCall)
    assert s1.value.name == "UInt"
    assert isinstance(s1.value.args[0], Identifier)
    assert s1.value.args[0].name == "Rdn"

    s2: Assignment = program.statements[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "m"
    assert isinstance(s2.value, FunctionCall)
    assert s2.value.name == "UInt"
    assert isinstance(s2.value.args[0], Identifier)
    assert s2.value.args[0].name == "Rm"

    s3: Assignment = program.statements[3]
    assert isinstance(s3, Assignment)
    assert s3.target == "setflags"
    assert isinstance(s3.value, UnaryOp)
    assert s3.value.op == "!"
    assert isinstance(s3.value.operand, FunctionCall)
    assert s3.value.operand.name == "InITBlock"

    s4: DestructureAssignment = program.statements[4]
    assert isinstance(s4, DestructureAssignment)
    assert s4.targets == ["shift_t", "shift_n"]
    assert isinstance(s4.value, TupleLiteral)
    assert len(s4.value.elements) == 2
    assert isinstance(s4.value.elements[0], Identifier)
    assert s4.value.elements[0].name == "SRType_LSL"
    assert isinstance(s4.value.elements[1], IntegerLiteral)
    assert s4.value.elements[1].value == 0


# --- Variable extraction: output variables (assignments / definitions) ---


# --- extract_output_variables tests ---


def _extract_output(source: str) -> list[str]:
    return extract_output_variables(parse(source))


def test_extract_output_variables_adc_immediate() -> None:
    source = (FIXTURES / "adc_immediate_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["d", "n", "setflags", "imm32"]


def test_extract_output_variables_lsr_immediate() -> None:
    source = (FIXTURES / "lsr_immediate_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["d", "m", "setflags", "shift_n"]


def test_extract_output_variables_adc_register() -> None:
    source = (FIXTURES / "adc_register_t2_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["d", "n", "m", "setflags", "shift_t", "shift_n"]


def test_extract_output_variables_pop() -> None:
    source = (FIXTURES / "pop_ldm_op.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["address", "SP", "i", "R[i]"]


def test_extract_output_variables_mvn() -> None:
    source = (FIXTURES / "mvn_register_op.pseudo").read_text()
    result = _extract_output(source)
    assert result == [
        "shifted",
        "carry",
        "result",
        "R[d]",
        "APSR.N",
        "APSR.Z",
        "APSR.C",
    ]


def test_extract_output_variables_native_format() -> None:
    source = "x = 42;\n"
    result = extract_output_variables(parse(source))
    assert isinstance(result, list)
    assert result == ["x"]


def test_extract_output_variables_program_input() -> None:
    program = parse("x = UInt(Rd); y = (a == '1');\n")
    result = extract_output_variables(program)
    assert result == ["x", "y"]


def test_extract_boolean_from_not() -> None:
    result = _extract_output("setflags = !InITBlock();\n")
    assert result == ["setflags"]


def test_extract_concat_bits_type() -> None:
    result = _extract_output("imm32 = ThumbExpandImm(i:imm3:imm8);\n")
    assert result == ["imm32"]


def test_extract_bitstring_type() -> None:
    result = _extract_output("x = '01';\n")
    assert result == ["x"]


def test_extract_assignment_chain() -> None:
    result = _extract_output("a = 1; a = 2;\n")
    assert result == ["a"]


# --- Variable extraction: input variables (read but never defined) ---


# --- extract_input_variables tests ---


def _extract_input(source: str) -> list[str]:
    return extract_input_variables(parse(source))


def test_extract_input_variables_adc_immediate() -> None:
    source = (FIXTURES / "adc_immediate_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["Rd", "Rn", "S", "i", "imm3", "imm8"]


def test_extract_input_variables_lsr_immediate() -> None:
    source = (FIXTURES / "lsr_immediate_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["Rd", "Rm", "imm5"]


def test_extract_input_variables_adc_register() -> None:
    source = (FIXTURES / "adc_register_t2_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["Rd", "Rm", "Rn", "S", "imm2", "imm3", "type"]


def test_extract_input_variables_pop() -> None:
    source = (FIXTURES / "pop_ldm_op.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["registers"]


def test_extract_input_variables_mvn() -> None:
    source = (FIXTURES / "mvn_register_op.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["d", "m", "setflags", "shift_n", "shift_t"]


def test_extract_input_native_format() -> None:
    source = "x = y + 1;\n"
    result = extract_input_variables(parse(source))
    assert isinstance(result, list)
    assert result == ["y"]


def test_extract_input_program_input() -> None:
    program = parse("x = a + b;\n")
    result = extract_input_variables(program)
    assert result == ["a", "b"]


def test_extract_input_empty() -> None:
    result = _extract_input("x = 42;\n")
    assert result == []


# --- Fixture-based: EOR / ORR / AND / other instruction decoder parsing ---


def test_parse_eor_immediate_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        Assignment,
        BinaryOp,
        Comment,
        DestructureAssignment,
        FieldAccess,
        FunctionCall,
        IfThen,
        SeeStmt,
        Unpredictable,
    )

    source = (FIXTURES / "eor_immediate_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 7

    s0 = program.statements[0]
    assert isinstance(s0, Comment)

    s1 = program.statements[1]
    assert isinstance(s1, IfThen)
    assert isinstance(s1.condition, BinaryOp)
    assert s1.condition.op == "&&"
    assert isinstance(s1.then_body[0], SeeStmt)
    assert s1.then_body[0].instruction == "TEQ (immediate)"

    s2 = program.statements[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "d"

    s3 = program.statements[3]
    assert isinstance(s3, Assignment)
    assert s3.target == "n"

    s4 = program.statements[4]
    assert isinstance(s4, Assignment)
    assert s4.target == "setflags"

    s5 = program.statements[5]
    assert isinstance(s5, DestructureAssignment)
    assert s5.targets == ["imm32", "carry"]
    assert isinstance(s5.value, FunctionCall)
    assert s5.value.name == "ThumbExpandImm_C"
    assert len(s5.value.args) == 2
    arg1 = s5.value.args[1]
    assert isinstance(arg1, FieldAccess)
    assert arg1.base == "APSR"
    assert arg1.field == "C"

    s6 = program.statements[6]
    assert isinstance(s6, IfThen)
    assert isinstance(s6.then_body[0], Unpredictable)


def test_parse_orr_immediate_op() -> None:
    from arm_transpiller.ast_nodes import (
        Assignment,
        BinaryOp,
        BitIndex,
        Comment,
        FieldAccess,
        FunctionCall,
        Identifier,
        IfThen,
        Program,
        RegisterAccess,
        StatementCall,
    )

    source = (FIXTURES / "orr_immediate_op.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 1

    s0 = program.statements[0]
    assert isinstance(s0, IfThen)
    assert isinstance(s0.condition, FunctionCall)
    assert s0.condition.name == "ConditionPassed"
    assert len(s0.then_body) == 4

    s0s0 = s0.then_body[0]
    assert isinstance(s0s0, StatementCall)
    assert s0s0.name == "EncodingSpecificOperations"

    s0s1 = s0.then_body[1]
    assert isinstance(s0s1, Assignment)
    assert s0s1.target == "result"
    assert isinstance(s0s1.value, BinaryOp)
    assert s0s1.value.op == "OR"
    assert isinstance(s0s1.value.left, RegisterAccess)
    assert isinstance(s0s1.value.right, Identifier)
    assert s0s1.value.right.name == "imm32"

    s0s2 = s0.then_body[2]
    assert isinstance(s0s2, Assignment)
    assert isinstance(s0s2.target, RegisterAccess)

    s0s3 = s0.then_body[3]
    assert isinstance(s0s3, IfThen)
    assert s0s3.condition.name == "setflags"
    assert len(s0s3.then_body) == 4

    s0s3s0 = s0s3.then_body[0]
    assert isinstance(s0s3s0, Assignment)
    assert isinstance(s0s3s0.target, FieldAccess)
    assert s0s3s0.target.base == "APSR"
    assert s0s3s0.target.field == "N"
    assert isinstance(s0s3s0.value, BitIndex)
    assert s0s3s0.value.name == "result"
    assert isinstance(s0s3s0.value.index, IntegerLiteral)
    assert s0s3s0.value.index.value == 31

    s0s3s1 = s0s3.then_body[1]
    assert isinstance(s0s3s1, Assignment)
    assert isinstance(s0s3s1.target, FieldAccess)
    assert s0s3s1.target.base == "APSR"
    assert s0s3s1.target.field == "Z"
    assert isinstance(s0s3s1.value, FunctionCall)
    assert s0s3s1.value.name == "IsZeroBit"

    s0s3s2 = s0s3.then_body[2]
    assert isinstance(s0s3s2, Assignment)
    assert isinstance(s0s3s2.target, FieldAccess)
    assert s0s3s2.target.base == "APSR"
    assert s0s3s2.target.field == "C"
    assert isinstance(s0s3s2.value, Identifier)
    assert s0s3s2.value.name == "carry"

    s0s3s3 = s0s3.then_body[3]
    assert isinstance(s0s3s3, Comment)
    assert s0s3s3.text == "APSR.V unchanged"


def test_extract_output_variables_orr() -> None:
    source = (FIXTURES / "orr_immediate_op.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["result", "R[d]", "APSR.N", "APSR.Z", "APSR.C"]


def test_extract_input_variables_orr() -> None:
    source = (FIXTURES / "orr_immediate_op.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["carry", "d", "imm32", "n", "setflags"]


def test_parse_or_expression() -> None:
    program = parse("x = a OR b;\n")
    assert isinstance(program.statements[0], Assignment)
    val = program.statements[0].value
    assert isinstance(val, BinaryOp)
    assert val.op == "OR"
    assert isinstance(val.left, Identifier)
    assert val.left.name == "a"
    assert isinstance(val.right, Identifier)
    assert val.right.name == "b"


def test_parse_and_register_op() -> None:
    from arm_transpiller.ast_nodes import (
        Assignment,
        BinaryOp,
        BitIndex,
        Comment,
        DestructureAssignment,
        FieldAccess,
        FunctionCall,
        Identifier,
        IfThen,
        Program,
        RegisterAccess,
        StatementCall,
    )

    source = (FIXTURES / "and_register_op.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 1

    s0 = program.statements[0]
    assert isinstance(s0, IfThen)
    assert isinstance(s0.condition, FunctionCall)
    assert s0.condition.name == "ConditionPassed"
    assert len(s0.then_body) == 5

    s0s0 = s0.then_body[0]
    assert isinstance(s0s0, StatementCall)
    assert s0s0.name == "EncodingSpecificOperations"

    s0s1 = s0.then_body[1]
    assert isinstance(s0s1, DestructureAssignment)
    assert s0s1.targets == ["shifted", "carry"]

    s0s2 = s0.then_body[2]
    assert isinstance(s0s2, Assignment)
    assert s0s2.target == "result"
    assert isinstance(s0s2.value, BinaryOp)
    assert s0s2.value.op == "AND"
    assert isinstance(s0s2.value.left, RegisterAccess)
    assert isinstance(s0s2.value.right, Identifier)
    assert s0s2.value.right.name == "shifted"

    s0s3 = s0.then_body[3]
    assert isinstance(s0s3, Assignment)
    assert isinstance(s0s3.target, RegisterAccess)

    s0s4 = s0.then_body[4]
    assert isinstance(s0s4, IfThen)
    assert s0s4.condition.name == "setflags"
    assert len(s0s4.then_body) == 4

    s0s4s0 = s0s4.then_body[0]
    assert isinstance(s0s4s0, Assignment)
    assert isinstance(s0s4s0.target, FieldAccess)
    assert s0s4s0.target.base == "APSR"
    assert s0s4s0.target.field == "N"
    assert isinstance(s0s4s0.value, BitIndex)

    s0s4s3 = s0s4.then_body[3]
    assert isinstance(s0s4s3, Comment)
    assert s0s4s3.text == "APSR.V unchanged"


def test_extract_output_variables_and() -> None:
    source = (FIXTURES / "and_register_op.pseudo").read_text()
    result = _extract_output(source)
    assert result == [
        "shifted",
        "carry",
        "result",
        "R[d]",
        "APSR.N",
        "APSR.Z",
        "APSR.C",
    ]


def test_extract_input_variables_and() -> None:
    source = (FIXTURES / "and_register_op.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["d", "m", "n", "setflags", "shift_n", "shift_t"]


def test_parse_and_expression() -> None:
    program = parse("x = a AND b;\n")
    assert isinstance(program.statements[0], Assignment)
    val = program.statements[0].value
    assert isinstance(val, BinaryOp)
    assert val.op == "AND"
    assert isinstance(val.left, Identifier)
    assert val.left.name == "a"
    assert isinstance(val.right, Identifier)
    assert val.right.name == "b"


def test_extract_output_variables_eor() -> None:
    source = (FIXTURES / "eor_immediate_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["d", "n", "setflags", "imm32", "carry"]


def test_extract_input_variables_eor() -> None:
    source = (FIXTURES / "eor_immediate_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["APSR.C", "Rd", "Rn", "S", "i", "imm3", "imm8"]


def test_parse_sub_immediate_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        SeeStmt,
    )

    source = (FIXTURES / "sub_immediate_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 7

    s0 = program.statements[0]
    assert isinstance(s0, IfThen)
    assert len(s0.then_body) == 1
    assert isinstance(s0.then_body[0], SeeStmt)
    assert s0.then_body[0].instruction == "CMP (immediate)"

    s1 = program.statements[1]
    assert isinstance(s1, IfThen)
    assert len(s1.then_body) == 1
    assert isinstance(s1.then_body[0], SeeStmt)
    assert s1.then_body[0].instruction == "SUB (SP minus immediate)"

    s2 = program.statements[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "d"

    s3 = program.statements[3]
    assert isinstance(s3, Assignment)
    assert s3.target == "n"

    s4 = program.statements[4]
    assert isinstance(s4, Assignment)
    assert s4.target == "setflags"

    s5 = program.statements[5]
    assert isinstance(s5, Assignment)
    assert s5.target == "imm32"

    s6 = program.statements[6]
    assert isinstance(s6, IfThen)
    assert isinstance(s6.then_body[0], Unpredictable)


def test_extract_output_variables_sub_immediate() -> None:
    source = (FIXTURES / "sub_immediate_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["d", "n", "setflags", "imm32"]


def test_extract_input_variables_sub_immediate() -> None:
    source = (FIXTURES / "sub_immediate_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["Rd", "Rn", "S", "i", "imm3", "imm8"]


def test_parse_eor_expression() -> None:
    program = parse("x = J1 EOR S;\n")
    assert isinstance(program.statements[0], Assignment)
    val = program.statements[0].value
    assert isinstance(val, BinaryOp)
    assert val.op == "EOR"
    assert isinstance(val.left, Identifier)
    assert val.left.name == "J1"
    assert isinstance(val.right, Identifier)
    assert val.right.name == "S"


def test_parse_eor_with_not() -> None:
    program = parse("I1 = NOT(J1 EOR S);\n")
    assert isinstance(program.statements[0], Assignment)
    val = program.statements[0].value
    assert isinstance(val, UnaryOp)
    assert val.op == "NOT"
    assert isinstance(val.operand, BinaryOp)
    assert val.operand.op == "EOR"


def test_parse_bl_decoder() -> None:
    source = (FIXTURES / "bl_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 4

    s0: Assignment = program.statements[0]
    assert isinstance(s0, Assignment)
    assert s0.target == "I1"
    assert isinstance(s0.value, UnaryOp)
    assert s0.value.op == "NOT"
    assert isinstance(s0.value.operand, BinaryOp)
    assert s0.value.operand.op == "EOR"
    assert isinstance(s0.value.operand.left, Identifier)
    assert s0.value.operand.left.name == "J1"
    assert isinstance(s0.value.operand.right, Identifier)
    assert s0.value.operand.right.name == "S"

    s1: Assignment = program.statements[1]
    assert isinstance(s1, Assignment)
    assert s1.target == "I2"
    assert isinstance(s1.value, UnaryOp)
    assert s1.value.op == "NOT"
    assert isinstance(s1.value.operand, BinaryOp)
    assert s1.value.operand.op == "EOR"

    s2: Assignment = program.statements[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "imm32"
    assert isinstance(s2.value, FunctionCall)
    assert s2.value.name == "SignExtend"
    assert len(s2.value.args) == 2
    concat = s2.value.args[0]
    assert isinstance(concat, BinaryOp)
    assert concat.op == ":"
    assert isinstance(s2.value.args[1], IntegerLiteral)
    assert s2.value.args[1].value == 32

    s3: IfThen = program.statements[3]
    assert isinstance(s3, IfThen)
    assert isinstance(s3.condition, BinaryOp)
    assert s3.condition.op == "&&"
    assert isinstance(s3.condition.left, FunctionCall)
    assert s3.condition.left.name == "InITBlock"
    assert isinstance(s3.condition.right, UnaryOp)
    assert s3.condition.right.op == "!"
    assert isinstance(s3.condition.right.operand, FunctionCall)
    assert s3.condition.right.operand.name == "LastInITBlock"
    assert len(s3.then_body) == 1
    assert isinstance(s3.then_body[0], Unpredictable)


def test_extract_output_variables_bl_decoder() -> None:
    source = (FIXTURES / "bl_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["I1", "I2", "imm32"]


def test_extract_input_variables_bl_decoder() -> None:
    source = (FIXTURES / "bl_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["J1", "J2", "S", "imm10", "imm11"]


def test_parse_b_t3_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        Assignment,
        BinaryOp,
        BitRange,
        BitStringLiteral,
        FunctionCall,
        IfThen,
        IntegerLiteral,
        SeeStmt,
        Unpredictable,
    )

    source = (FIXTURES / "b_t3_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 3

    s0 = program.statements[0]
    assert isinstance(s0, IfThen)
    assert isinstance(s0.condition, BinaryOp)
    assert s0.condition.op == "=="
    assert isinstance(s0.condition.left, BitRange)
    assert s0.condition.left.name == "cond"
    assert isinstance(s0.condition.left.high, IntegerLiteral)
    assert s0.condition.left.high.value == 3
    assert isinstance(s0.condition.left.low, IntegerLiteral)
    assert s0.condition.left.low.value == 1
    assert isinstance(s0.condition.right, BitStringLiteral)
    assert s0.condition.right.value == "111"
    assert len(s0.then_body) == 1
    assert isinstance(s0.then_body[0], SeeStmt)
    assert s0.then_body[0].instruction == "Related encodings"

    s1 = program.statements[1]
    assert isinstance(s1, Assignment)
    assert s1.target == "imm32"
    assert isinstance(s1.value, FunctionCall)
    assert s1.value.name == "SignExtend"
    assert len(s1.value.args) == 2
    assert isinstance(s1.value.args[0], BinaryOp)
    assert s1.value.args[0].op == ":"
    assert isinstance(s1.value.args[1], IntegerLiteral)
    assert s1.value.args[1].value == 32

    s2 = program.statements[2]
    assert isinstance(s2, IfThen)
    assert isinstance(s2.condition, FunctionCall)
    assert s2.condition.name == "InITBlock"
    assert len(s2.condition.args) == 0
    assert len(s2.then_body) == 1
    assert isinstance(s2.then_body[0], Unpredictable)


def test_extract_output_variables_b_t3() -> None:
    source = (FIXTURES / "b_t3_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["imm32"]


def test_extract_input_variables_b_t3() -> None:
    source = (FIXTURES / "b_t3_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["J1", "J2", "S", "cond", "imm11", "imm6"]


def test_parse_ldrh_register_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        Assignment,
        BinaryOp,
        BitStringLiteral,
        DestructureAssignment,
        FunctionCall,
        Identifier,
        IfThen,
        SeeStmt,
        TupleLiteral,
        Unpredictable,
    )

    source = (FIXTURES / "ldrh_register_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 10

    s0 = program.statements[0]
    assert isinstance(s0, IfThen)
    assert isinstance(s0.condition, BinaryOp)
    assert s0.condition.op == "=="
    assert isinstance(s0.condition.left, Identifier)
    assert s0.condition.left.name == "Rn"
    assert isinstance(s0.condition.right, BitStringLiteral)
    assert s0.condition.right.value == "1111"
    assert len(s0.then_body) == 1
    assert isinstance(s0.then_body[0], SeeStmt)
    assert s0.then_body[0].instruction == "LDRH (literal)"

    s1 = program.statements[1]
    assert isinstance(s1, IfThen)
    assert isinstance(s1.condition, BinaryOp)
    assert s1.condition.op == "=="
    assert isinstance(s1.condition.left, Identifier)
    assert s1.condition.left.name == "Rt"
    assert isinstance(s1.condition.right, BitStringLiteral)
    assert s1.condition.right.value == "1111"
    assert len(s1.then_body) == 1
    assert isinstance(s1.then_body[0], SeeStmt)
    assert s1.then_body[0].instruction == "Related instructions"

    s2 = program.statements[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "t"
    assert isinstance(s2.value, FunctionCall)
    assert s2.value.name == "UInt"

    s3 = program.statements[3]
    assert isinstance(s3, Assignment)
    assert s3.target == "n"

    s4 = program.statements[4]
    assert isinstance(s4, Assignment)
    assert s4.target == "m"

    s5 = program.statements[5]
    assert isinstance(s5, Assignment)
    assert s5.target == "index"

    s6 = program.statements[6]
    assert isinstance(s6, Assignment)
    assert s6.target == "add"

    s7 = program.statements[7]
    assert isinstance(s7, Assignment)
    assert s7.target == "wback"

    s8 = program.statements[8]
    assert isinstance(s8, DestructureAssignment)
    assert s8.targets == ["shift_t", "shift_n"]
    assert isinstance(s8.value, TupleLiteral)
    assert len(s8.value.elements) == 2
    assert isinstance(s8.value.elements[0], Identifier)
    assert s8.value.elements[0].name == "SRType_LSL"
    assert isinstance(s8.value.elements[1], FunctionCall)
    assert s8.value.elements[1].name == "UInt"

    s9 = program.statements[9]
    assert isinstance(s9, IfThen)
    assert isinstance(s9.condition, BinaryOp)
    assert s9.condition.op == "||"
    assert isinstance(s9.then_body[0], Unpredictable)


def test_extract_output_variables_ldrh_register() -> None:
    source = (FIXTURES / "ldrh_register_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["t", "n", "m", "index", "add", "wback", "shift_t", "shift_n"]


def test_extract_input_variables_ldrh_register() -> None:
    source = (FIXTURES / "ldrh_register_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["FALSE", "Rm", "Rn", "Rt", "SRType_LSL", "TRUE", "imm2"]


def test_parse_pop_t3_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        Assignment,
        BinaryOp,
        BitIndex,
        BitLiteral,
        FunctionCall,
        Identifier,
        IfThen,
        IntegerLiteral,
        Unpredictable,
    )

    source = (FIXTURES / "pop_t3_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 5

    s0 = program.statements[0]
    assert isinstance(s0, Assignment)
    assert s0.target == "t"
    assert isinstance(s0.value, FunctionCall)
    assert s0.value.name == "UInt"
    assert len(s0.value.args) == 1
    assert isinstance(s0.value.args[0], Identifier)
    assert s0.value.args[0].name == "Rt"

    s1 = program.statements[1]
    assert isinstance(s1, Assignment)
    assert s1.target == "registers"
    assert isinstance(s1.value, FunctionCall)
    assert s1.value.name == "Zeros"
    assert len(s1.value.args) == 1
    assert isinstance(s1.value.args[0], IntegerLiteral)
    assert s1.value.args[0].value == 16

    s2 = program.statements[2]
    assert isinstance(s2, Assignment)
    assert isinstance(s2.target, BitIndex)
    assert s2.target.name == "registers"
    assert isinstance(s2.target.index, Identifier)
    assert s2.target.index.name == "t"
    assert isinstance(s2.value, BitLiteral)
    assert s2.value.value == 1

    s3 = program.statements[3]
    assert isinstance(s3, Assignment)
    assert s3.target == "UnalignedAllowed"
    assert isinstance(s3.value, Identifier)
    assert s3.value.name == "TRUE"

    s4 = program.statements[4]
    assert isinstance(s4, IfThen)
    assert isinstance(s4.condition, BinaryOp)
    assert s4.condition.op == "||"
    assert isinstance(s4.condition.left, BinaryOp)
    assert s4.condition.left.op == "=="
    assert isinstance(s4.condition.left.left, Identifier)
    assert s4.condition.left.left.name == "t"
    assert isinstance(s4.condition.left.right, IntegerLiteral)
    assert s4.condition.left.right.value == 13
    assert isinstance(s4.condition.right, BinaryOp)
    assert s4.condition.right.op == "&&"
    assert isinstance(s4.then_body[0], Unpredictable)
    assert s4.else_body is None


def test_extract_output_variables_pop_t3() -> None:
    source = (FIXTURES / "pop_t3_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["t", "registers", "UnalignedAllowed"]


def test_extract_input_variables_pop_t3() -> None:
    source = (FIXTURES / "pop_t3_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["Rt", "TRUE"]


def test_parse_mrs_t1_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        Assignment,
        BinaryOp,
        FunctionCall,
        Identifier,
        IfThen,
        InExpr,
        IntegerLiteral,
        Range,
        UnaryOp,
        Unpredictable,
    )

    source = (FIXTURES / "mrs_t1_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 2

    s0 = program.statements[0]
    assert isinstance(s0, Assignment)
    assert s0.target == "d"
    assert isinstance(s0.value, FunctionCall)
    assert s0.value.name == "UInt"
    assert isinstance(s0.value.args[0], Identifier)
    assert s0.value.args[0].name == "Rd"

    s1 = program.statements[1]
    assert isinstance(s1, IfThen)
    assert isinstance(s1.condition, BinaryOp)
    assert s1.condition.op == "||"

    assert isinstance(s1.condition.left, InExpr)
    assert isinstance(s1.condition.left.left, Identifier)
    assert s1.condition.left.left.name == "d"
    assert len(s1.condition.left.set.elements) == 2
    assert isinstance(s1.condition.left.set.elements[0], IntegerLiteral)
    assert s1.condition.left.set.elements[0].value == 13
    assert isinstance(s1.condition.left.set.elements[1], IntegerLiteral)
    assert s1.condition.left.set.elements[1].value == 15

    assert isinstance(s1.condition.right, UnaryOp)
    assert s1.condition.right.op == "!"
    inner_in = s1.condition.right.operand
    assert isinstance(inner_in, InExpr)
    assert isinstance(inner_in.left, FunctionCall)
    assert inner_in.left.name == "UInt"
    assert isinstance(inner_in.left.args[0], Identifier)
    assert inner_in.left.args[0].name == "SYSm"
    assert len(inner_in.set.elements) == 3
    assert isinstance(inner_in.set.elements[0], Range)
    assert inner_in.set.elements[0].start == 0
    assert inner_in.set.elements[0].end == 3
    assert isinstance(inner_in.set.elements[1], Range)
    assert inner_in.set.elements[1].start == 5
    assert inner_in.set.elements[1].end == 9
    assert isinstance(inner_in.set.elements[2], Range)
    assert inner_in.set.elements[2].start == 16
    assert inner_in.set.elements[2].end == 20

    assert isinstance(s1.then_body[0], Unpredictable)


def test_extract_output_variables_mrs_t1() -> None:
    source = (FIXTURES / "mrs_t1_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["d"]


def test_parse_rev_t2_decoder() -> None:
    source = (FIXTURES / "rev_t2_decoder.pseudo").read_text()
    program = parse(source)
    assert len(program.statements) == 4


def test_extract_output_variables_rev_t2() -> None:
    source = (FIXTURES / "rev_t2_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["d", "m"]


def test_extract_input_variables_rev_t2() -> None:
    source = (FIXTURES / "rev_t2_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["Rd", "Rm"]


def test_extract_input_variables_mrs_t1() -> None:
    source = (FIXTURES / "mrs_t1_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["Rd", "SYSm"]


def test_parse_vabs_t1_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        Assignment,
        BinaryOp,
        BitLiteral,
        FunctionCall,
        Identifier,
        IfExpr,
    )

    source = (FIXTURES / "vabs_t1_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 3

    s0: Assignment = program.statements[0]
    assert isinstance(s0, Assignment)
    assert s0.target == "dp_operation"
    assert isinstance(s0.value, BinaryOp)
    assert s0.value.op == "=="
    assert isinstance(s0.value.left, Identifier)
    assert s0.value.left.name == "sz"
    assert isinstance(s0.value.right, BitLiteral)
    assert s0.value.right.value == 1

    s1: Assignment = program.statements[1]
    assert isinstance(s1, Assignment)
    assert s1.target == "d"
    assert isinstance(s1.value, IfExpr)
    assert isinstance(s1.value.condition, Identifier)
    assert s1.value.condition.name == "dp_operation"
    assert isinstance(s1.value.then_value, FunctionCall)
    assert s1.value.then_value.name == "UInt"
    assert len(s1.value.then_value.args) == 1
    assert isinstance(s1.value.then_value.args[0], BinaryOp)
    assert s1.value.then_value.args[0].op == ":"
    assert isinstance(s1.value.then_value.args[0].left, Identifier)
    assert s1.value.then_value.args[0].left.name == "D"
    assert isinstance(s1.value.then_value.args[0].right, Identifier)
    assert s1.value.then_value.args[0].right.name == "Vd"
    assert isinstance(s1.value.else_value, FunctionCall)
    assert s1.value.else_value.name == "UInt"
    assert isinstance(s1.value.else_value.args[0], BinaryOp)
    assert s1.value.else_value.args[0].op == ":"
    assert isinstance(s1.value.else_value.args[0].left, Identifier)
    assert s1.value.else_value.args[0].left.name == "Vd"
    assert isinstance(s1.value.else_value.args[0].right, Identifier)
    assert s1.value.else_value.args[0].right.name == "D"

    s2: Assignment = program.statements[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "m"
    assert isinstance(s2.value, IfExpr)
    assert isinstance(s2.value.condition, Identifier)
    assert s2.value.condition.name == "dp_operation"
    assert isinstance(s2.value.then_value, FunctionCall)
    assert s2.value.then_value.name == "UInt"
    assert len(s2.value.then_value.args) == 1
    assert isinstance(s2.value.then_value.args[0], BinaryOp)
    assert s2.value.then_value.args[0].op == ":"
    assert isinstance(s2.value.then_value.args[0].left, Identifier)
    assert s2.value.then_value.args[0].left.name == "M"
    assert isinstance(s2.value.then_value.args[0].right, Identifier)
    assert s2.value.then_value.args[0].right.name == "Vm"
    assert isinstance(s2.value.else_value, FunctionCall)
    assert s2.value.else_value.name == "UInt"
    assert isinstance(s2.value.else_value.args[0], BinaryOp)
    assert s2.value.else_value.args[0].op == ":"
    assert isinstance(s2.value.else_value.args[0].left, Identifier)
    assert s2.value.else_value.args[0].left.name == "Vm"
    assert isinstance(s2.value.else_value.args[0].right, Identifier)
    assert s2.value.else_value.args[0].right.name == "M"


def test_extract_output_variables_vabs_t1() -> None:
    source = (FIXTURES / "vabs_t1_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["dp_operation", "d", "m"]


def test_extract_input_variables_vabs_t1() -> None:
    source = (FIXTURES / "vabs_t1_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["D", "M", "Vd", "Vm", "sz"]


def test_parse_vcvt_t1_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        Assignment,
        BinaryOp,
        BitIndex,
        IfExpr,
        IfThen,
        PatternMatch,
        SeeStmt,
    )

    source = (FIXTURES / "vcvt_t1_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 4

    s0: IfThen = program.statements[0]
    assert isinstance(s0, IfThen)
    assert isinstance(s0.condition, BinaryOp)
    assert s0.condition.op == "&&"
    assert isinstance(s0.condition.right, UnaryOp)
    assert s0.condition.right.op == "!"
    assert isinstance(s0.condition.right.operand, PatternMatch)
    assert s0.condition.right.operand.expr.name == "opc2"
    assert s0.condition.right.operand.pattern == "10x"
    assert isinstance(s0.then_body[0], SeeStmt)
    assert s0.then_body[0].instruction == "Related encodings"

    s1: Assignment = program.statements[1]
    assert isinstance(s1, Assignment)
    assert s1.target == "to_integer"
    assert isinstance(s1.value, BinaryOp)
    assert s1.value.op == "=="
    assert isinstance(s1.value.left, BitIndex)
    assert s1.value.left.name == "opc2"
    assert isinstance(s1.value.left.index, IntegerLiteral)
    assert s1.value.left.index.value == 2

    s2: Assignment = program.statements[2]
    assert isinstance(s2, Assignment)
    assert s2.target == "dp_operation"

    s3: IfThen = program.statements[3]
    assert isinstance(s3, IfThen)
    assert len(s3.then_body) == 4
    assert s3.then_body[0].target == "unsigned"
    assert s3.then_body[1].target == "round_zero"
    assert isinstance(s3.then_body[2].value, FunctionCall)
    assert isinstance(s3.then_body[3].value, IfExpr)

    assert len(s3.else_body) == 4
    assert s3.else_body[0].target == "unsigned"
    assert s3.else_body[1].target == "round_nearest"
    assert isinstance(s3.else_body[3].value, IfExpr)


def test_extract_output_variables_vcvt_t1() -> None:
    source = (FIXTURES / "vcvt_t1_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == [
        "to_integer",
        "dp_operation",
        "unsigned",
        "round_zero",
        "d",
        "m",
        "round_nearest",
    ]


def test_extract_input_variables_vcvt_t1() -> None:
    source = (FIXTURES / "vcvt_t1_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["D", "FALSE", "M", "Vd", "Vm", "op", "opc2", "sz"]


def test_parse_vrinta_t1_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        Assignment,
        BitStringLiteral,
        CaseOf,
        Identifier,
        WhenClause,
    )

    source = (FIXTURES / "vrinta_t1_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 5

    s2: CaseOf = program.statements[2]
    assert isinstance(s2, CaseOf)
    assert isinstance(s2.expr, Identifier)
    assert s2.expr.name == "RM"
    assert len(s2.clauses) == 4
    assert s2.else_body is None

    c0: WhenClause = s2.clauses[0]
    assert isinstance(c0.pattern, BitStringLiteral)
    assert c0.pattern.value == "00"
    assert c0.comment == "Round to nearest, with ties away"
    assert len(c0.body) == 2
    assert isinstance(c0.body[0], Assignment)
    assert c0.body[0].target == "rmode"

    c3: WhenClause = s2.clauses[3]
    assert isinstance(c3.pattern, BitStringLiteral)
    assert c3.pattern.value == "11"
    assert c3.comment == "Round towards Minus Infinity"
    assert len(c3.body) == 2


def test_extract_output_variables_vrinta_t1() -> None:
    source = (FIXTURES / "vrinta_t1_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["dp_operation", "rmode", "away", "d", "m"]


def test_extract_input_variables_vrinta_t1() -> None:
    source = (FIXTURES / "vrinta_t1_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["D", "FALSE", "M", "RM", "TRUE", "Vd", "Vm", "sz"]


def test_parse_vsel_t1_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        BinaryOp,
        IfExpr,
    )

    source = (FIXTURES / "vsel_t1_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 6

    s1: Assignment = program.statements[1]
    assert s1.target == "dp_operation"

    s2: Assignment = program.statements[2]
    assert s2.target == "cond"
    assert isinstance(s2.value, BinaryOp)
    assert s2.value.op == ":"

    s3: Assignment = program.statements[3]
    assert s3.target == "d"
    assert isinstance(s3.value, IfExpr)

    s4: Assignment = program.statements[4]
    assert s4.target == "n"
    assert isinstance(s4.value, IfExpr)


def test_extract_output_variables_vsel_t1() -> None:
    source = (FIXTURES / "vsel_t1_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["dp_operation", "cond", "d", "n", "m"]


def test_extract_input_variables_vsel_t1() -> None:
    source = (FIXTURES / "vsel_t1_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["D", "M", "N", "Vd", "Vm", "Vn", "cc", "sz"]


def test_parse_vnmla_t1_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        IfExpr,
    )

    source = (FIXTURES / "vnmla_t1_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 5

    s0: Assignment = program.statements[0]
    assert s0.target == "type"
    assert isinstance(s0.value, IfExpr)

    s1: Assignment = program.statements[1]
    assert s1.target == "dp_operation"

    s2: Assignment = program.statements[2]
    assert s2.target == "d"
    assert isinstance(s2.value, IfExpr)

    s3: Assignment = program.statements[3]
    assert s3.target == "n"
    assert isinstance(s3.value, IfExpr)

    s4: Assignment = program.statements[4]
    assert s4.target == "m"
    assert isinstance(s4.value, IfExpr)


def test_extract_output_variables_vnmla_t1() -> None:
    source = (FIXTURES / "vnmla_t1_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["type", "dp_operation", "d", "n", "m"]


def test_extract_input_variables_vnmla_t1() -> None:
    source = (FIXTURES / "vnmla_t1_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == [
        "D",
        "M",
        "N",
        "VFPNegMul_VNMLA",
        "VFPNegMul_VNMLS",
        "Vd",
        "Vm",
        "Vn",
        "op",
        "sz",
    ]


def test_parse_vldm_t1_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        Comment,
        SeeStmt,
        Undefined,
        Unpredictable,
    )

    source = (FIXTURES / "vldm_t1_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 16

    s0: IfThen = program.statements[0]
    assert isinstance(s0.then_body[0], SeeStmt)
    assert s0.then_body[0].instruction == "Related encodings"

    s1: IfThen = program.statements[1]
    assert isinstance(s1.then_body[0], SeeStmt)
    assert s1.then_body[0].instruction == "VPOP"

    s4: IfThen = program.statements[4]
    assert isinstance(s4.then_body[0], Undefined)

    cmt: Comment = program.statements[5]
    assert isinstance(cmt, Comment)
    assert "Remaining combinations" in cmt.text

    s6: Assignment = program.statements[6]
    assert s6.target == "single_regs"

    s8: Assignment = program.statements[8]
    assert s8.target == "wback"

    s12: Assignment = program.statements[12]
    assert s12.target == "regs"

    s13: IfThen = program.statements[13]
    assert isinstance(s13.then_body[0], Unpredictable)

    s14: IfThen = program.statements[14]
    assert isinstance(s14.then_body[0], Unpredictable)

    s15: IfThen = program.statements[15]
    assert isinstance(s15.then_body[0], Unpredictable)


def test_extract_output_variables_vldm_t1() -> None:
    source = (FIXTURES / "vldm_t1_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["single_regs", "add", "wback", "d", "n", "imm32", "regs"]


def test_extract_input_variables_vldm_t1() -> None:
    source = (FIXTURES / "vldm_t1_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["D", "FALSE", "P", "Rn", "U", "Vd", "W", "imm8"]


def test_parse_vrintz_t1_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        BitRange,
        IfExpr,
    )

    source = (FIXTURES / "vrintz_t1_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 4

    s1: Assignment = program.statements[1]
    assert s1.target == "rmode"
    assert isinstance(s1.value, IfExpr)
    else_branch = s1.value.else_value
    assert isinstance(else_branch, BitRange)
    assert else_branch.name == "FPSCR"
    assert else_branch.high == IntegerLiteral(23)
    assert else_branch.low == IntegerLiteral(22)

    s2: Assignment = program.statements[2]
    assert s2.target == "d"
    assert isinstance(s2.value, IfExpr)

    s3: Assignment = program.statements[3]
    assert s3.target == "m"
    assert isinstance(s3.value, IfExpr)


def test_extract_output_variables_vrintz_t1() -> None:
    source = (FIXTURES / "vrintz_t1_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["dp_operation", "rmode", "d", "m"]


def test_extract_input_variables_vrintz_t1() -> None:
    source = (FIXTURES / "vrintz_t1_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["D", "FPSCR", "M", "Vd", "Vm", "op", "sz"]


def test_parse_rsb_immediate_t1_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        Comment,
        FunctionCall,
        UnaryOp,
    )

    source = (FIXTURES / "rsb_immediate_t1_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 5

    s2: Assignment = program.statements[2]
    assert s2.target == "setflags"
    assert isinstance(s2.value, UnaryOp)
    assert s2.value.op == "!"

    s3: Assignment = program.statements[3]
    assert s3.target == "imm32"
    assert isinstance(s3.value, FunctionCall)
    assert s3.value.name == "Zeros"

    cmt: Comment = program.statements[4]
    assert isinstance(cmt, Comment)
    assert cmt.text == "immediate = #0"


def test_extract_output_variables_rsb_immediate_t1() -> None:
    source = (FIXTURES / "rsb_immediate_t1_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["d", "n", "setflags", "imm32"]


def test_extract_input_variables_rsb_immediate_t1() -> None:
    source = (FIXTURES / "rsb_immediate_t1_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["Rd", "Rn"]


def test_parse_str_register_op() -> None:
    from arm_transpiller.ast_nodes import (
        ArrayAccess,
        Assignment,
        BinaryOp,
        FunctionCall,
        Identifier,
        IfThen,
        Program,
        RegisterAccess,
        StatementCall,
    )

    source = (FIXTURES / "str_register_op.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 1

    s0 = program.statements[0]
    assert isinstance(s0, IfThen)
    assert isinstance(s0.condition, FunctionCall)
    assert s0.condition.name == "ConditionPassed"
    assert len(s0.then_body) == 4

    s0s0 = s0.then_body[0]
    assert isinstance(s0s0, StatementCall)
    assert s0s0.name == "EncodingSpecificOperations"

    s0s1 = s0.then_body[1]
    assert isinstance(s0s1, Assignment)
    assert s0s1.target == "offset"
    assert isinstance(s0s1.value, FunctionCall)
    assert s0s1.value.name == "Shift"
    assert isinstance(s0s1.value.args[0], RegisterAccess)

    s0s2 = s0.then_body[2]
    assert isinstance(s0s2, Assignment)
    assert s0s2.target == "address"
    assert isinstance(s0s2.value, BinaryOp)
    assert s0s2.value.op == "+"
    assert isinstance(s0s2.value.left, RegisterAccess)

    s0s3 = s0.then_body[3]
    assert isinstance(s0s3, Assignment)
    assert isinstance(s0s3.target, ArrayAccess)
    assert s0s3.target.name == "MemU"
    assert len(s0s3.target.args) == 2
    assert isinstance(s0s3.target.args[0], Identifier)
    assert isinstance(s0s3.value, RegisterAccess)


def test_extract_output_variables_str_register() -> None:
    source = (FIXTURES / "str_register_op.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["offset", "address"]


def test_extract_input_variables_str_register() -> None:
    source = (FIXTURES / "str_register_op.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["APSR.C", "m", "n", "shift_n", "shift_t", "t"]


# --- Side-effect extraction (UNPREDICTABLE / UNDEFINED / SEE) ---


def test_extract_sideeffects_none() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse("d = UInt(Rd);"))
    assert result == {"unpredictable": False, "undefined": False, "see": False}


def test_extract_sideeffects_unpredictable() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse("UNPREDICTABLE;"))
    assert result == {"unpredictable": True, "undefined": False, "see": False}


def test_extract_sideeffects_undefined() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse("UNDEFINED;"))
    assert result == {"unpredictable": False, "undefined": True, "see": False}


def test_extract_sideeffects_see() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse('SEE "TEST";'))
    assert result == {"unpredictable": False, "undefined": False, "see": True}


def test_extract_sideeffects_nested_if() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse("if TRUE then UNPREDICTABLE;"))
    assert result == {"unpredictable": True, "undefined": False, "see": False}


def test_extract_sideeffects_nested_for() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse("for i = 0 to 5 UNDEFINED;"))
    assert result == {"unpredictable": False, "undefined": True, "see": False}


def test_extract_sideeffects_multiple() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse('UNPREDICTABLE; UNDEFINED; SEE "X";'))
    assert result == {"unpredictable": True, "undefined": True, "see": True}


def test_extract_sideeffects_program_input() -> None:
    from arm_transpiller import extract_side_effects

    program = parse("UNPREDICTABLE;")
    result = extract_side_effects(program)
    assert result["unpredictable"] is True


def test_extract_side_effects_native_format() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse("UNPREDICTABLE;"))
    assert isinstance(result, dict)
    assert result["unpredictable"] is True
    assert result["undefined"] is False
    assert result["see"] is False


def test_extract_sideeffects_runtime_fn_thumbexpandimm() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse("imm32 = ThumbExpandImm(i:imm3:imm8);"))
    assert result == {"unpredictable": True, "undefined": False, "see": False}


def test_extract_sideeffects_runtime_fn_thumbexpandimm_c() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse("(imm32, carry) = ThumbExpandImm_C(x, c);"))
    assert result == {"unpredictable": True, "undefined": False, "see": False}


def test_extract_sideeffects_runtime_fn_inside_if() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse("if TRUE then imm32 = ThumbExpandImm(x);"))
    assert result == {"unpredictable": True, "undefined": False, "see": False}


def test_extract_sideeffects_runtime_fn_ignores_normal_call() -> None:
    from arm_transpiller import extract_side_effects

    result = extract_side_effects(parse("d = UInt(Rd);"))
    assert result == {"unpredictable": False, "undefined": False, "see": False}


# --- Variable extraction: unassigned input (read but never assigned) ---


# --- extract_unassigned_inputs tests ---


def _extract_input_no_assign(source: str) -> list[str]:
    from arm_transpiller.analysis.unassigned_inputs import (
        extract_unassigned_inputs,
    )

    return extract_unassigned_inputs(parse(source))


def test_extract_input_no_assignment_mrs_t1() -> None:
    source = (FIXTURES / "mrs_t1_decoder.pseudo").read_text()
    result = _extract_input_no_assign(source)
    assert result == ["SYSm"]


def test_extract_input_no_assignment_adc_immediate() -> None:
    source = (FIXTURES / "adc_immediate_decoder.pseudo").read_text()
    result = _extract_input_no_assign(source)
    assert result == []


def test_extract_input_no_assignment_native_format() -> None:
    from arm_transpiller.analysis.unassigned_inputs import (
        extract_unassigned_inputs,
    )

    source = "if cond then x = y; else z = 42;\n"
    result = extract_unassigned_inputs(parse(source))
    assert isinstance(result, list)
    assert result == ["cond"]


def test_extract_input_no_assignment_program_input() -> None:
    from arm_transpiller.analysis.unassigned_inputs import (
        extract_unassigned_inputs,
    )

    program = parse("if cond then d = UInt(Rd); else x = 1;\n")
    result = extract_unassigned_inputs(program)
    assert result == ["cond"]


def test_extract_input_no_assignment_empty() -> None:
    result = _extract_input_no_assign("x = 42;\n")
    assert result == []


def test_extract_input_no_assignment_all_rhs() -> None:
    result = _extract_input_no_assign("d = UInt(Rd); n = UInt(Rn);\n")
    assert result == []


# --- VMOV (immediate) T1 ---


def test_parse_vmov_immediate_t1_decoder() -> None:
    from arm_transpiller.ast_nodes import (
        Assignment,
        BinaryOp,
        BitLiteral,
        FunctionCall,
        Identifier,
        IfThen,
        IntegerLiteral,
    )

    source = (FIXTURES / "vmov_immediate_t1_decoder.pseudo").read_text()
    program = parse(source)

    assert isinstance(program, Program)
    assert len(program.statements) == 2

    s0: Assignment = program.statements[0]
    assert isinstance(s0, Assignment)
    assert s0.target == "dp_operation"
    assert isinstance(s0.value, BinaryOp)
    assert s0.value.op == "=="
    assert isinstance(s0.value.left, Identifier)
    assert s0.value.left.name == "sz"
    assert isinstance(s0.value.right, BitLiteral)
    assert s0.value.right.value == 1

    s1: IfThen = program.statements[1]
    assert isinstance(s1, IfThen)
    assert isinstance(s1.condition, Identifier)
    assert s1.condition.name == "dp_operation"
    assert len(s1.then_body) == 2
    assert len(s1.else_body) == 2

    then0: Assignment = s1.then_body[0]
    assert isinstance(then0, Assignment)
    assert then0.target == "d"
    assert isinstance(then0.value, FunctionCall)
    assert then0.value.name == "UInt"
    assert isinstance(then0.value.args[0], BinaryOp)
    assert then0.value.args[0].op == ":"
    assert isinstance(then0.value.args[0].left, Identifier)
    assert then0.value.args[0].left.name == "D"
    assert isinstance(then0.value.args[0].right, Identifier)
    assert then0.value.args[0].right.name == "Vd"

    then1: Assignment = s1.then_body[1]
    assert isinstance(then1, Assignment)
    assert then1.target == "imm64"
    assert isinstance(then1.value, FunctionCall)
    assert then1.value.name == "VFPExpandImm"
    assert len(then1.value.args) == 2
    assert isinstance(then1.value.args[0], BinaryOp)
    assert then1.value.args[0].op == ":"
    assert isinstance(then1.value.args[1], IntegerLiteral)
    assert then1.value.args[1].value == 64

    else0: Assignment = s1.else_body[0]
    assert isinstance(else0, Assignment)
    assert else0.target == "d"
    assert isinstance(else0.value, FunctionCall)
    assert else0.value.name == "UInt"
    assert isinstance(else0.value.args[0], BinaryOp)
    assert else0.value.args[0].op == ":"
    assert isinstance(else0.value.args[0].left, Identifier)
    assert else0.value.args[0].left.name == "Vd"

    else1: Assignment = s1.else_body[1]
    assert isinstance(else1, Assignment)
    assert else1.target == "imm32"
    assert isinstance(else1.value, FunctionCall)
    assert else1.value.name == "VFPExpandImm"
    assert len(else1.value.args) == 2


def test_extract_output_variables_vmov_immediate_t1() -> None:
    source = (FIXTURES / "vmov_immediate_t1_decoder.pseudo").read_text()
    result = _extract_output(source)
    assert result == ["dp_operation", "d", "imm64", "imm32"]


def test_extract_input_variables_vmov_immediate_t1() -> None:
    source = (FIXTURES / "vmov_immediate_t1_decoder.pseudo").read_text()
    result = _extract_input(source)
    assert result == ["D", "Vd", "imm4H", "imm4L", "sz"]
