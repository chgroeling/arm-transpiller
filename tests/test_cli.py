from __future__ import annotations

import json

from click.testing import CliRunner

from arm_transpiller.__main__ import main


def run(*args: str, stdin: str = "") -> str:
    """Invoke the CLI, feeding *stdin* through the ``-`` input argument."""
    result = CliRunner().invoke(main, [*args, "-"], input=stdin)
    assert result.exit_code == 0, result.output
    return result.output


# --- types command ---


def test_types_command_reports_inputs_and_outputs() -> None:
    output = json.loads(run("types", stdin="d = UInt(Rd);"))
    assert output == {"inputs": {"Rd": "bits4"}, "outputs": {"d": "uint32"}}


def test_types_command_honours_input_types() -> None:
    output = json.loads(
        run("types", "--input-types", "Wibble=bits7", stdin="x = Wibble;")
    )
    assert output == {"inputs": {"Wibble": "bits7"}, "outputs": {"x": "bits7"}}


def test_types_command_reports_unknown_type_as_null() -> None:
    output = json.loads(run("types", stdin="x = Wibble;"))
    assert output["outputs"] == {"x": None}


# --- transpile --input-types ---


def test_transpile_input_types_sets_concat_width() -> None:
    output = run(
        "transpile",
        "--target",
        "python",
        "--input-types",
        "a=bits5,b=bits7",
        stdin="x = a:b;",
    )
    assert output == "x = concat_bits(a, b, 7)\n"


def test_transpile_input_types_accepts_bool() -> None:
    output = run(
        "transpile",
        "--target",
        "c",
        "--input-types",
        "flag=bool",
        stdin="x = NOT(flag);",
    )
    assert output == "x = ((~flag) & 0x1u);\n"


def test_transpile_rejects_malformed_input_types() -> None:
    result = CliRunner().invoke(
        main,
        ["transpile", "--target", "c", "--input-types", "a=bits5,b", "-"],
        input="x = a:b;",
    )
    assert result.exit_code != 0
    assert "name=type pair" in result.output


def test_transpile_rejects_unknown_type_spelling() -> None:
    result = CliRunner().invoke(
        main,
        ["transpile", "--target", "c", "--input-types", "a=int", "-"],
        input="x = a;",
    )
    assert result.exit_code != 0
    assert "not a valid ARM type" in result.output


# --- Type failures are reported, not raised as tracebacks ---


def test_transpile_reports_unknown_type_without_a_traceback() -> None:
    result = CliRunner().invoke(
        main, ["transpile", "--target", "c", "-"], input="x = SignExtend(Wibble, 32);"
    )
    assert result.exit_code == 1
    assert result.output.startswith("Error: Cannot determine the type of 'Wibble'")
    assert "Traceback" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_transpile_reports_unknown_function_return_type() -> None:
    result = CliRunner().invoke(
        main,
        ["transpile", "--target", "python", "-"],
        input="x = SignExtend(FancyDecode(Rd), 32);",
    )
    assert result.exit_code == 1
    assert "FancyDecode" in result.output
    assert "Traceback" not in result.output
