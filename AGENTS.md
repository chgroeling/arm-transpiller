# AGENTS.md — arm-pseudocode-transpiller

## Project overview

A Python CLI tool that transpiles ARM Architecture Reference Manual pseudocode into C or Python. Input is the pseudocode language used in the ARM ARM (e.g. instruction encoding/decoding and operation descriptions). Output is functionally equivalent C or Python code.

## Tech stack

- **Language:** Python ≥ 3.12
- **Package/dependency manager:** [uv](https://docs.astral.sh/uv/)
- **Parsing:** [Lark](https://github.com/lark-parser/lark) (EBNF-based parser generator)
- **Testing:** pytest (unit tests required for every parser rule, AST node, and code generator)
- **Linting / formatting:** Ruff (linter + formatter)
- **Type checking:** mypy (strict mode)

## Getting started

```bash
uv sync                    # create venv & install dependencies
uv run pytest              # run all tests
uv run ruff check .        # lint
uv run ruff format --check .  # check formatting
uv run mypy src/           # type check
```

The Python runtime template (`src/arm_transpiller/armruntime/armruntime.py.template`)
is also checked and auto-formatted by Ruff — keep it clean alongside the rest of the
Python source.

## Release process

### Semantic versioning

This project follows [SemVer](https://semver.org/) (`MAJOR.MINOR.PATCH`):

| Bump | When |
|---|---|
| `MAJOR` | Incompatible API changes (renamed/removed functions, changed signatures, removed behaviour) |
| `MINOR` | New backwards-compatible features |
| `PATCH` | Backwards-compatible bug fixes |

### Commit conventions

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Meaning | Version bump |
|---|---|---|
| `feat:` | New feature | MINOR |
| `fix:` | Bug fix | PATCH |
| `feat!:` / `fix!:` | Breaking change (or `BREAKING CHANGE:` footer) | MAJOR |
| `refactor:` | Code change without behaviour change | none |
| `docs:` | Documentation only | none |
| `test:` | Tests only | none |
| `chore:` | Tooling, CI, dependencies | none |
| `perf:` | Performance improvement | PATCH |

### Changelog

Every tagged release updates `CHANGELOG.md`.  The format follows
[Keep a Changelog](https://keepachangelog.com/) with these sections per
release:

- **`Added`** — new features
- **`Changed`** — changes in existing functionality
- **`Removed`** — removed features
- **`Fixed`** — bug fixes

The changelog is the source of truth for what ships in each version.
Entries are written in the past tense, user-facing, and grouped by
category.

## Project structure

```
src/arm_transpiller/           # main package
    __init__.py
    __main__.py                # CLI entry point (uv run arm-transpiller ...)
    grammar.lark               # Lark EBNF grammar for ARM pseudocode
    parser.py                  # Lark parser setup & AST construction
    ast_nodes.py               # AST node dataclasses
    known_types.py             # ARM type model (bitsN/uintN/sintN/bool) + known input types
    runtime_types.py           # runtime return types, read from the .py.template annotations
    type_inference.py          # infers the type of every expression and variable
    generators/
        __init__.py
        base.py                # abstract code generator
        c_generator.py         # AST → C transpiler
        python_generator.py    # AST → Python transpiler
    analysis/                       # AST analysis passes
        __init__.py
        _collect.py                 # shared AST-walking helpers (definitions, reads, inputs)
        conditionally_assigned.py   # definite-assignment analysis
        input_variables.py          # input variable extraction
        output_variables.py         # output variable extraction
        side_effects.py             # side-effect detection (UNPREDICTABLE, UNDEFINED, SEE)
        subsumed_variables.py       # subsumed-variable analysis
        unassigned_inputs.py        # unassigned-input extraction
    armruntime/                     # runtime library (armruntime.h.template, armruntime.py.template)
tests/
    conftest.py
    test_parser.py             # one test per grammar rule
    test_c_generator.py        # integration tests: pseudocode → C
    test_python_generator.py   # integration tests: pseudocode → Python
    test_type_inference.py     # type model, known types, runtime annotations, inference
    test_cli.py                # CLI commands and options
    test_definite_assignment.py # definite-assignment analysis tests
    test_subsumed_variables.py  # subsumed-variable analysis tests
    test_generator_types.py     # type-annotation consistency tests
    fixtures/
        *.pseudo               # pseudocode snippets for testing
```

## ARM pseudocode language characteristics

The input is the pseudocode from the ARM Architecture Reference Manual. The full index of pseudocode functions and procedures is documented at:
https://developer.arm.com/documentation/ddi0406/c/Appendices/Pseudocode-Index/Pseudocode-functions-and-procedures

Key features:

- **Bit extraction/concat:** `UInt(reg)`, `SInt(reg)`, `bits<N>` slices, `expr1:expr2` bitfield concatenation, `'0'` / `'1'` bit literals
- **Register references:** `R[d]`, `SP`, `LR` — 0-indexed integer registers
- **Immediates:** integer literals, hex with `0x`, `Replicate(…)`, `ThumbExpandImm(…)`, `Align(…)`
- **Assignments:** `=`, `:=` (architecturally visible vs. internal)
- **Control flow:** `if … then … elsif … else …`, `for`, `while`, `repeat … until`
- **Special statements:** `UNPREDICTABLE`, `UNDEFINED`, `CONSTRAINED UNPREDICTABLE`, `return`, `case … when … of`
- **Comments:** `//` single-line, `/* */` multi-line
- **Type annotations:** `boolean`, `integer`, `bits(N)`, `enum`
- **Function calls & declarations:** user-defined functions with parameters and return types

See `tests/fixtures/` for representative snippets.

## Variable extraction

The analysis modules can extract **output** and **input** variables from
pseudocode, detect side-effects, and perform deeper analysis.

### Functions

| Function | Returns |
|---|---|
| `extract_output_variables(program)` | `list[str]` of output variables (those **defined/assigned** in the code) |
| `extract_input_variables(program)` | `list[str]` of input variables (those **read** but never defined) |
| `extract_unassigned_inputs(program)` | `list[str]` of input variables whose value never flows into an assignment |
| `extract_side_effects(program)` | `dict[str, bool]` — flags for UNPREDICTABLE, UNDEFINED, SEE |
| `extract_conditionally_assigned(program, input_types=None)` | `list[str]` — output variables NOT assigned on every path |
| `extract_subsumed_variables(program, input_types=None)` | `list[str]` — output variables subsumed by another output |
| `extract_variable_types(program, input_types=None)` | `dict[str, dict[str, str\|None]]` with the **type** of every input and output variable |
| `infer_types(program, input_types=None)` | `dict[str, ArmType]` for every variable the code defines |

All take an already-parsed :class:`Program` AST.  Call :func:`parse` first to
obtain one from a source string.

### Dotted field access

ARM pseudocode dotted identifiers like `APSR.N`, `APSR.C` are parsed as
``FieldAccess`` AST nodes.  Both generators emit proper field access using the
target language's `.` operator: the base identifier is lowercased (``APSR`` →
``apsr``) to follow snake_case naming, and the field name is kept verbatim
(e.g. ``apsr.N``, ``apsr.C``).  In C this requires a struct definition in the
preamble; in Python it works with a class or any object with matching
attributes.

### CLI usage

```bash
# Output variables (defined in the code)
uv run python -c "from arm_transpiller import parse, extract_output_variables; print(extract_output_variables(parse('d = UInt(Rd); n = UInt(Rn); setflags = (S == chr(39)+'1'+chr(39)+');')))"

# Input variables (read but never defined)
uv run python -c "from arm_transpiller import extract_input_variables, parse; print(extract_input_variables(parse('d = UInt(Rd);')))"
```



## Type system

Values are typed with a **width-carrying** type: `bitsN` (ARM's `bits(N)`),
`uintN`, `sintN`, `bool` (1 bit) or `tuple[T, ...]`.  The same spelling is used
everywhere — runtime annotations, `--input-types` overrides, and the JSON of
`arm-transpiller types`.

`bitsN` is the default for everything.  `uintN` appears **only** as the
result of `UInt()`, `sintN` **only** from `SInt()` and negation, `bool` only
from comparisons and boolean constants.  Joining keeps the most specific kind
(`sint` > `uint` > `bits` > `bool`) and the wider width.

| Source of a type | Where |
|---|---|
| Input variables (read but never assigned) | table in `known_types.py`; `imm<N>` → `bits<N>` by pattern |
| User overrides (win over the table) | `--input-types "Rdn=bits3"` / `CGenerator(input_types={"Rdn": "bits3"})` |
| Runtime function results | **return annotations** in `armruntime/armruntime.py.template` |
| Everything else | inferred by `type_inference.py` from the assigned expressions |

Rules to keep in mind when changing code:

- **Every new runtime function must be added** to the ``_RUNTIME_RETURN_TYPES``
  table in ``runtime_types.py`` with its ARM return type.  Only ``UInt()``
  returns ``uintN`` and only ``SInt()`` returns ``sintN``.  A missing entry
  makes inference raise ``UnknownFunctionTypeError``.
- **The C runtime uses standard fixed-width types** (``uint32_t``, ``int32_t``,
  ``bool``, ``void``) and ``Tuple2Ret`` for tuple returns.  A comment next to
  the signature carries the ARM tuple type.
  ``test_type_inference.py`` checks the two runtimes agree on every function.
- Generators must not guess widths: they ask ``self._get_expr_width(expr)``
  (raises on unknown) or ``self._get_bitwise_width(expr)`` (falls back to 32).
- Signedness goes through ``self._is_signed(expr)``.  The C generator casts both
  operands of ``<``, ``>``, ``<=``, ``>=``, ``/``, ``DIV``, ``MOD`` to
  ``sint32`` when either side is signed; Python needs nothing, its integers are
  already signed.
- The CLI reports ``UnknownTypeError`` as a ``click.ClickException`` (message
  and exit status 1); the API keeps raising, so callers can handle it.
- ``generate()`` calls ``self._infer_types(program)`` before walking the AST.
- Unknown types are surfaced as errors (``UnknownVariableTypeError``), never
  silently defaulted, so wrong masks/shifts cannot slip through.

## Code conventions

- **Dataclasses for AST nodes:** every grammar rule gets a frozen `@dataclass` node in `ast_nodes.py`.
- **Names match the grammar:** rule `?bitfield_concat` → class `BitfieldConcat`.
- **Generators use a visitor pattern** (Lark `Transformer` or manual `match/case` dispatch on the AST).
- **Runtime functions are defined in `armruntime/armruntime.py.template`** (Python) and `armruntime/armruntime.h.template` (C) — they emulate the ARM pseudocode runtime (e.g. `UInt(x)` returns an unsigned integer value, matching the spec).
- **Tests are always written alongside feature code.** Every new grammar rule needs at least one parser test and one output test per target language.
- **Generated C code follows [Google C++ Style Guide](https://google.github.io/styleguide/cppguide.html) naming:**
  - Struct/types: `PascalCase` (e.g. `Tuple2Ret`)
  - Variables/functions (including generated temporaries): `snake_case` (e.g. `tuple_2_ret_1`)
  - No leading underscores (`_` is reserved); `_` only used for destructure wildcards in Python output.
- **Python source code (this package) follows PEP 8** enforced by Ruff.
- **Package data (e.g. `grammar.lark`) lives inside the package and is loaded with `importlib.resources`, never via `__file__` paths.** Keep data files under `src/arm_transpiller/` so they ship as package data, and read them like:
  ```python
  from importlib.resources import files
  text = files("arm_transpiller").joinpath("grammar.lark").read_text(encoding="utf-8")
  ```
  This is zip-safe and install-location independent. No `force-include` in `pyproject.toml` is needed — hatchling already ships all files under the package.

## Commands (quick reference)

| Command | Purpose |
|---|---|
| `uv sync` | Install all deps into venv |
| `uv run pytest` | Run all tests |
| `uv run pytest -xvs` | Run tests verbosely, stop on first failure |
| `uv run ruff check .` | Lint |
| `uv run ruff format .` | Auto-format |
| `uv run mypy src/` | Type check |
| `uv run arm-transpiller transpile --target c \| python input.pseudo` | Transpile to C or Python |
| `uv run arm-transpiller types input.pseudo` | Infer the type of every variable |
| `uv run arm-transpiller output-variables input.pseudo` | Extract output variables |
| `uv run arm-transpiller input-variables input.pseudo` | Extract input variables |
| `uv run arm-transpiller side-effects input.pseudo` | Detect side-effects |
| `uv run arm-transpiller unassigned-inputs input.pseudo` | Extract unassigned input variables |
| `uv run arm-transpiller conditionally-assigned input.pseudo` | Find conditionally assigned variables |
| `uv run arm-transpiller subsumed-variables input.pseudo` | Find subsumed variables |
| `uv run arm-transpiller runtime --target c \| python` | Output the runtime library |
