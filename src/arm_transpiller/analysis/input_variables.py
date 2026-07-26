"""Input variable extraction for ARM pseudocode.

Input variables are those that are **read** (referenced in expressions or
conditions) but never assigned to within the code.

``extract_input_variables`` is the high-level API.
"""

from __future__ import annotations

from ..ast_nodes import Program
from ._collect import _collect_input_variables


def extract_input_variables(program: Program) -> list[str]:
    """Return a list of input variable names.

    Input variables are those that are read (referenced in expressions) but
    never assigned to within the code.

    Args:
        program: A parsed pseudocode Program AST.

    Returns:
        A list of variable name strings.
    """
    return _collect_input_variables(program)
