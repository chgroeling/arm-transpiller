from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from typing import IO, Iterator

import click

from .generators.base import CodeGenerator
from .generators.c_generator import CGenerator
from .generators.python_generator import PythonGenerator
from .known_types import ArmType, TypeSyntaxError, UnknownTypeError, parse_type
from .parser import parse


def _parse_input_types(
    _ctx: click.Context, _param: click.Parameter, value: str | None
) -> dict[str, ArmType] | None:
    if value is None:
        return None
    result: dict[str, ArmType] = {}
    for pair in value.split(","):
        name, sep, type_text = pair.partition("=")
        if not sep:
            raise click.BadParameter(f"'{pair.strip()}' is not a name=type pair")
        try:
            result[name.strip()] = parse_type(type_text)
        except TypeSyntaxError as exc:
            raise click.BadParameter(str(exc)) from exc
    return result


_INPUT_TYPES_HELP = (
    "Comma-separated name=type pairs overriding input variable types "
    "(e.g. Rdn=bits3,setflags=bool)"
)


@contextmanager
def _reported_type_errors() -> Iterator[None]:
    """Turn a type failure into a clean CLI error instead of a traceback."""
    try:
        yield
    except UnknownTypeError as exc:
        raise click.ClickException(str(exc)) from exc


@click.group()
def main() -> None:
    """Transpile ARM pseudocode to C or Python."""


@main.command()
@click.option(
    "--target",
    type=click.Choice(["c", "python"]),
    required=True,
    help="Target language",
)
@click.option(
    "--input-types",
    default=None,
    help=_INPUT_TYPES_HELP,
    callback=_parse_input_types,
)
@click.argument("input", type=click.File(), required=False, default=sys.stdin)
def transpile(
    target: str, input_types: dict[str, ArmType] | None, input: IO[str]
) -> None:
    """Transpile INPUT pseudocode file to C or Python."""
    source = input.read()
    program = parse(source)

    generator: CodeGenerator
    match target:
        case "c":
            generator = CGenerator(input_types=input_types)
        case "python":
            generator = PythonGenerator(input_types=input_types)

    with _reported_type_errors():
        output = generator.generate(program)
    click.echo(output, nl=False)


@main.command("types")
@click.option(
    "--input-types",
    default=None,
    help=_INPUT_TYPES_HELP,
    callback=_parse_input_types,
)
@click.argument("input", type=click.File(), required=False, default=sys.stdin)
def types_cmd(input_types: dict[str, ArmType] | None, input: IO[str]) -> None:
    """Infer the type of every variable in INPUT pseudocode.

    Input variable types come from the known-types table (or --input-types);
    output variable types are inferred from the expressions assigned to them.
    """
    from .type_inference import extract_variable_types  # noqa: PLC0415

    source = input.read()
    program = parse(source)
    with _reported_type_errors():
        output = extract_variable_types(program, input_types)
    click.echo(json.dumps(output, indent=2), nl=False)


@main.command("side-effects")
@click.argument("input", type=click.File(), required=False, default=sys.stdin)
def side_effects_cmd(input: IO[str]) -> None:
    """Detect side-effects (UNPREDICTABLE, UNDEFINED, SEE) in INPUT pseudocode."""
    from .analysis.side_effects import extract_side_effects  # noqa: PLC0415

    source = input.read()
    program = parse(source)
    click.echo(json.dumps(extract_side_effects(program), indent=2), nl=False)


@main.command("output-variables")
@click.argument("input", type=click.File(), required=False, default=sys.stdin)
def output_variables_cmd(input: IO[str]) -> None:
    """Extract output variables from INPUT pseudocode."""
    from .analysis.output_variables import extract_output_variables  # noqa: PLC0415

    source = input.read()
    program = parse(source)
    click.echo(json.dumps(extract_output_variables(program), indent=2), nl=False)


@main.command("input-variables")
@click.argument("input", type=click.File(), required=False, default=sys.stdin)
def input_variables_cmd(input: IO[str]) -> None:
    """Extract input variables (read but never assigned) from INPUT pseudocode."""
    from .analysis.input_variables import extract_input_variables  # noqa: PLC0415

    source = input.read()
    program = parse(source)
    click.echo(json.dumps(extract_input_variables(program), indent=2), nl=False)


@main.command("conditionally-assigned")
@click.option(
    "--input-types",
    default=None,
    help=_INPUT_TYPES_HELP,
    callback=_parse_input_types,
)
@click.argument("input", type=click.File(), required=False, default=sys.stdin)
def conditionally_assigned_cmd(
    input_types: dict[str, ArmType] | None, input: IO[str]
) -> None:
    """List output variables NOT assigned on every execution path."""
    from .analysis.conditionally_assigned import (  # noqa: PLC0415
        extract_conditionally_assigned,
    )

    source = input.read()
    program = parse(source)
    with _reported_type_errors():
        output = extract_conditionally_assigned(program, input_types)
    click.echo(json.dumps(output, indent=2), nl=False)


@main.command("subsumed-variables")
@click.option(
    "--input-types",
    default=None,
    help=_INPUT_TYPES_HELP,
    callback=_parse_input_types,
)
@click.argument("input", type=click.File(), required=False, default=sys.stdin)
def subsumed_variables_cmd(
    input_types: dict[str, ArmType] | None, input: IO[str]
) -> None:
    """List output variables subsumed by another retained output variable."""
    from .analysis.subsumed_variables import (  # noqa: PLC0415
        extract_subsumed_variables,
    )

    source = input.read()
    program = parse(source)
    with _reported_type_errors():
        output = extract_subsumed_variables(program, input_types)
    click.echo(json.dumps(output, indent=2), nl=False)


@main.command("unassigned-inputs")
@click.argument("input", type=click.File(), required=False, default=sys.stdin)
def unassigned_inputs_cmd(input: IO[str]) -> None:
    """Extract input variables whose value never flows into an assignment.

    These are read-only inputs used in conditions or function arguments
    but never appear on the right-hand side of any assignment.
    """
    from .analysis.unassigned_inputs import (  # noqa: PLC0415
        extract_unassigned_inputs,
    )

    source = input.read()
    program = parse(source)
    click.echo(json.dumps(extract_unassigned_inputs(program), indent=2), nl=False)


@main.command()
@click.option(
    "--target",
    type=click.Choice(["c", "python"]),
    required=True,
    help="Target language",
)
def runtime(target: str) -> None:
    """Output the armruntime library file."""
    from .runtime_types import get_runtime_source  # noqa: PLC0415

    click.echo(get_runtime_source(target), nl=False)
