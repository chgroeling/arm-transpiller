"""Return types of the runtime functions, declared explicitly.

The ARM types that runtime functions produce are maintained here as the single
source of truth.  Functions returning ``None`` or ``void`` are not listed.
"""

from __future__ import annotations

import re
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType
from typing import Mapping

from .known_types import (
    BOOL,
    ArmType,
    TupleType,
    bits,
    sint,
    uint,
)

_RUNTIME_RETURN_TYPES: Mapping[str, ArmType] = MappingProxyType(
    {
        # Bit manipulation builtins
        "UInt": uint(32),
        "Replicate": bits(32),
        "concat_bits": bits(32),
        "BitCount": bits(6),
        "IsZeroBit": BOOL,
        # Sign/zero extension
        "SInt": sint(32),
        # Alignment
        "Align": bits(32),
        # Architectural state
        "ConditionPassed": BOOL,
        "Consistent": BOOL,
        "MemA_read": bits(32),
        "MemU_read": bits(32),
        # IT block helpers
        "InITBlock": BOOL,
        "LastInITBlock": BOOL,
        # Shift helpers
        "DecodeImmShift": TupleType((bits(3), bits(6))),
        "Shift": bits(32),
        "Shift_C": TupleType((bits(32), bits(1))),
        # Thumb expand with carry
        "ThumbExpandImm_C": TupleType((bits(32), bits(1))),
        "ThumbExpandImm": bits(32),
        # VFP
        "VFPExpandImm": bits(32),
        "VFPSmallRegisterBank": BOOL,
    }
)


@lru_cache(maxsize=1)
def runtime_return_types() -> Mapping[str, ArmType]:
    """Return a mapping of runtime function name → annotated ARM return type."""
    return _RUNTIME_RETURN_TYPES


_RUNTIME_TARGET_FILES: dict[str, str] = {
    "c": "armruntime.h.template",
    "python": "armruntime.py.template",
}


def get_runtime_source(target: str) -> str:
    """Return the armruntime library source for *target* (``"c"`` or ``"python"``).

    Raises:
        ValueError: if *target* is not a known language.
    """
    filename = _RUNTIME_TARGET_FILES.get(target)
    if filename is None:
        raise ValueError(f"Unknown target: {target!r}. Expected 'c' or 'python'.")
    return (
        files("arm_transpiller")
        .joinpath("armruntime")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )


_C_FUNCTION_RE = re.compile(
    r"^static inline\s+([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE
)


def read_c_runtime() -> str:
    """Return the source of the C runtime library template."""
    return get_runtime_source("c")


@lru_cache(maxsize=1)
def c_runtime_return_types() -> Mapping[str, str]:
    """Return a mapping of C runtime function name → declared return type name.

    The C header now uses ``uint32_t`` / ``int32_t`` / ``bool`` / ``void`` /
    ``Tuple2Ret`` directly.  Functions returning ``void`` are not listed.
    """
    return MappingProxyType(
        {
            name: return_type
            for return_type, name in _C_FUNCTION_RE.findall(read_c_runtime())
        }
    )
