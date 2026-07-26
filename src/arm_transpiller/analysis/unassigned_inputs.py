"""Unassigned-input variable extraction for ARM pseudocode.

Unassigned-input variables are input variables (read but never assigned) whose
value never flows into another variable's definition — i.e. they are read-only
inputs used in conditions or function arguments but never appear on the
right-hand side of any assignment.

``extract_unassigned_inputs`` is the high-level API.
"""

from __future__ import annotations

from ..ast_nodes import Program
from ._collect import _collect_unassigned_input_variables


def extract_unassigned_inputs(program: Program) -> list[str]:
    """Return a list of input variable names whose values are never used on the
    right-hand side of an assignment.

    These are variables that are read (e.g. in conditions or function arguments
    controlling sub-expressions) but whose value never flows into another
    variable's definition.

    Args:
        program: A parsed pseudocode Program AST.

    Returns:
        A list of variable name strings.
    """
    return _collect_unassigned_input_variables(program)
