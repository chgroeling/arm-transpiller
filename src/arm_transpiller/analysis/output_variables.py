"""Output variable extraction for ARM pseudocode.

Output variables are those that are **defined/assigned** in the pseudocode.
Variables with a trailing underscore (e.g. ``I1_``) are considered private
and are excluded.

``extract_output_variables`` is the high-level API.
"""

from __future__ import annotations

from ..ast_nodes import Program
from ._collect import _collect_definitions


def extract_output_variables(program: Program) -> list[str]:
    """Return a list of output variable names.

    Args:
        program: A parsed pseudocode Program AST.

    Returns:
        A list of variable name strings.
    """
    return _collect_definitions(program)
