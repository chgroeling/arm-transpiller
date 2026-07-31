# arm-transpiller

Transpile [ARM Architecture Reference Manual](https://developer.arm.com/documentation/ddi0403/ee/) pseudocode into **C** or **Python**.

The ARM manual defines instruction decode and operation behaviour in a domain‑specific pseudocode language. `arm‑transpiller` parses that pseudocode and emits functionally equivalent C or Python, so spec snippets can be compiled, executed, and tested.

```text
in   (pseudocode)   if d IN {13,15} then UNDEFINED;

out  --target c      if (((d == 13) || (d == 15))) { sideffect_flags |= SIDEFFECT_UNDEFINED; };
out  --target python  if (d in (13, 15)): sideffect_flags |= SIDEFFECT_UNDEFINED
```

---

## Quick start

```bash
# install dependencies
uv sync

# transpile a file
uv run arm-transpiller transpile --target python input.pseudo

# pipe from stdin
echo "d = UInt(Rd);" | uv run arm-transpiller transpile --target c

# give the transpiler the types of fields it does not know
uv run arm-transpiller transpile --target c --input-types "Rdm=bits3,flag=bool" input.pseudo

# detect side-effects statically (no compilation needed)
uv run arm-transpiller side-effects input.pseudo

# extract variables defined or read in the code
uv run arm-transpiller output-variables input.pseudo
uv run arm-transpiller input-variables input.pseudo
uv run arm-transpiller unassigned-inputs input.pseudo

# infer the type (and therefore bit-width) of every variable
uv run arm-transpiller types input.pseudo
uv run arm-transpiller types --input-types "Rdn=bits3,flag=bool" input.pseudo

# find variables not assigned on every execution path
uv run arm-transpiller conditionally-assigned input.pseudo

# export the runtime library
uv run arm-transpiller runtime --target c      > armruntime.h
uv run arm-transpiller runtime --target python > armruntime.py
```

Requires **Python ≥ 3.12** and [uv](https://docs.astral.sh/uv/).

---

## Example

**Input** — ARM pseudocode:

```
d = UInt(Rd);
imm32 = ThumbExpandImm(i:imm3:imm8);
if d IN {13,15} || n IN {13,15} then UNPREDICTABLE;
```

**Output** — C (`--target c`):

```c
d = UInt(Rd);
imm32 = ThumbExpandImm(&sideffect_flags, concat_bits(concat_bits(i, imm3, 3), imm8, 8));
if ((((d == 13) || (d == 15)) || ((n == 13) || (n == 15)))) {
    sideffect_flags |= SIDEFFECT_UNPREDICTABLE;
};
```

**Output** — Python (`--target python`):

```python
d = UInt(Rd)
imm32 = ThumbExpandImm(sideffect_flags, concat_bits(concat_bits(i, imm3, 3), imm8, 8))
if ((d in (13, 15)) or (n in (13, 15))):
    sideffect_flags |= SIDEFFECT_UNPREDICTABLE
```

---

## CLI reference

### Commands

| Command                     | Description                                                     |
|-----------------------------|-----------------------------------------------------------------|
| `transpile`                 | Transpile pseudocode to C or Python                             |
| `side-effects`              | Detect side-effects (UNPREDICTABLE, UNDEFINED, SEE)             |
| `output-variables`          | List output variables produced by the code                      |
| `input-variables`           | List input variables consumed by the code                       |
| `unassigned-inputs`         | List input variables whose value never flows into an assignment |
| `conditionally-assigned`    | List output variables NOT assigned on every execution path      |
| `types`                     | Infer the type of every input and output variable               |
| `runtime`                   | Output the runtime library for a given target language          |

### `transpile`

| Option            | Value              | Description                                      |
|-------------------|--------------------|--------------------------------------------------|
| `--target`        | `c`, `python`      | Target language (required)                       |
| `--input-types`   | `name=type,…`      | Override input variable types (e.g. `Rdn=bits3`) |
| `INPUT`           | file path          | Input file; reads stdin when omitted             |

`--input-types` is not cosmetic: the types decide the shift in a concatenation,
the mask on a bitwise result, the source width of a sign extension, and whether
a comparison or division is signed (see [Type system](#type-system)).  The same
source transpiles differently depending on how wide its inputs are:

```console
$ echo "x = SignExtend(a:b, 32);" | uv run arm-transpiller transpile --target c --input-types "a=bits5,b=bits7"
x = SignExtend(concat_bits(a, b, 7), 12);

$ echo "x = SignExtend(a:b, 32);" | uv run arm-transpiller transpile --target c --input-types "a=bits1,b=bits3"
x = SignExtend(concat_bits(a, b, 3), 4);
```

Names covered by the known-types table (`Rd`, `imm8`, …) need no option.  A name
with no type at all is an error rather than a guess, so a missing `--input-types`
entry fails loudly instead of emitting a wrong width:

```console
$ echo "x = SignExtend(a:b, 32);" | uv run arm-transpiller transpile --target c
Error: Cannot determine the type of 'a'. Add it to known_types.py (exact match or imm<N> pattern) or pass it as an input type override (e.g. a=bits4).
$ echo $?
1
```

### `side-effects`

| Argument  | Value      | Description                          |
|-----------|------------|--------------------------------------|
| `INPUT`   | file path  | Input file; reads stdin when omitted |

Outputs a JSON object with boolean flags for each side-effect type:

| Flag             | Meaning                                                                                |
|------------------|----------------------------------------------------------------------------------------|
| `unpredictable`  | The pseudocode contains an `UNPREDICTABLE` statement or a ``ThumbExpandImm*`` call |
| `undefined`      | The pseudocode contains an `UNDEFINED` statement                                        |
| `see`            | The pseudocode contains a `SEE` (Software Engineer Exercise) annotation                 |

All three flags default to `false` when no side-effect appears in the code.  The
detection is purely static — it walks the AST, so it catches side-effects
regardless of whether they are reachable at runtime.

```console
$ echo "if d IN {13,15} then UNPREDICTABLE;" | uv run arm-transpiller side-effects
{
  "unpredictable": true,
  "undefined": false,
  "see": false
}

$ echo "UNDEFINED;" | uv run arm-transpiller side-effects
{
  "unpredictable": false,
  "undefined": true,
  "see": false
}
```

### `output-variables`

| Argument  | Value      | Description                          |
|-----------|------------|--------------------------------------|
| `INPUT`   | file path  | Input file; reads stdin when omitted |

Outputs a JSON list of output variable names — every variable that the
pseudocode defines or assigns to.

### `input-variables`

| Argument  | Value      | Description                          |
|-----------|------------|--------------------------------------|
| `INPUT`   | file path  | Input file; reads stdin when omitted |

Outputs a JSON list of input variable names — every variable that is read but
never assigned within the pseudocode.  External inputs like ``Rd``, ``Rn``, and
bit-field extracts (``imm3``, ``imm8``, …) are typical input variables.

### `unassigned-inputs`

| Argument  | Value      | Description                          |
|-----------|------------|--------------------------------------|
| `INPUT`   | file path  | Input file; reads stdin when omitted |

Outputs a JSON list of input variable names that never appear on the
right-hand side of any assignment.  These are read-only inputs used in
conditions or function arguments whose value does not flow into another
variable's definition.

### `conditionally-assigned`

| Option            | Value              | Description                                      |
|-------------------|--------------------|--------------------------------------------------|
| `--input-types`   | `name=type,…`      | Override input variable types (for case exhaustiveness) |
| `INPUT`           | file path          | Input file; reads stdin when omitted             |

Outputs a JSON list of output variable names that are **not** assigned on every
execution path through the block.  This identifies members of a generated
instruction struct that a particular encoding does not produce, so a consumer
can pre‑initialise them to their zero value before the transpiled block runs.

An `if`/`else` where both branches assign a variable, or an exhaustive `case`
over a typed selector where all clauses assign it, makes a variable definitely
assigned and excludes it from the list.  `UNPREDICTABLE` / `UNDEFINED` / `SEE`
in a branch make that branch terminating, so the other branch's assignments
stand.

```console
$ uv run arm-transpiller conditionally-assigned tests/fixtures/vmov_immediate_t1_decoder.pseudo
[
  "imm64",
  "imm32"
]
```

### `types`

| Option            | Value              | Description                                      |
|-------------------|--------------------|--------------------------------------------------|
| `--input-types`   | `name=type,…`      | Override input variable types (e.g. `Rdn=bits3`) |
| `INPUT`           | file path          | Input file; reads stdin when omitted             |

Outputs a JSON object with two maps — ``"inputs"`` and ``"outputs"`` — giving
the type of every variable the pseudocode references:

- **``"inputs"``** — variables that are *read* but never assigned (e.g. ``Rd``,
  ``imm8``).  Their types come from the known-types table (see
  [Type system](#type-system)) and can be overridden with ``--input-types``.
- **``"outputs"``** — variables the pseudocode *defines*.  Their types are
  inferred from the expressions assigned to them.

A ``null`` type means the type could not be determined — supply it with
``--input-types``, the same option ``transpile`` takes, so this command is a
quick way to work out which overrides a snippet needs before transpiling it.

```console
$ uv run arm-transpiller types tests/fixtures/adc_immediate_decoder.pseudo
{
  "inputs": {
    "Rd": "bits4",
    "Rn": "bits4",
    "S": "bits1",
    "i": "bits1",
    "imm3": "bits3",
    "imm8": "bits8"
  },
  "outputs": {
    "d": "uint32",
    "n": "uint32",
    "setflags": "bool",
    "imm32": "bits32"
  }
}
```

### `runtime`

| Option     | Value           | Description                           |
|------------|-----------------|---------------------------------------|
| `--target` | `c`, `python`   | Output the runtime for this language  |

---

## Programmatic API

```python
from arm_transpiller import (
    parse,
    CGenerator,
    PythonGenerator,
    extract_output_variables,
    extract_input_variables,
    extract_unassigned_inputs,
    extract_side_effects,
    extract_variable_types,
    extract_conditionally_assigned,
    extract_subsumed_variables,
    infer_types,
)

program = parse("d = UInt(Rd);")

# transpile
print(CGenerator().generate(program))
print(PythonGenerator().generate(program))

# override input variable types (e.g. for non-standard register fields)
print(CGenerator(input_types={"Rdn": "bits3"}).generate(program))

# infer the type of every variable in scope
print(infer_types(parse("d = UInt(Rd); imm32 = ThumbExpandImm(imm12);")))
# → {'d': ScalarType(kind='uint', width=32),
#    'Rd': ScalarType(kind='bits', width=4),
#    'imm32': ScalarType(kind='bits', width=32),
#    'imm12': ScalarType(kind='bits', width=12)}

print(extract_variable_types(parse("d = UInt(Rd);")))
# → {"inputs": {"Rd": "bits4"}, "outputs": {"d": "uint32"}}

# inspect variables
print(extract_output_variables(parse("d = UInt(Rd); n = UInt(Rn);")))
# → ["d", "n"]

print(extract_output_variables(parse("x_ = 1; d = UInt(Rd);")))
# → ["x_", "d"]

# find undeclared variables (read but never assigned)
print(extract_input_variables(parse("d = UInt(Rd);")))
# → ["Rd"]

# find conditionally assigned variables
print(extract_conditionally_assigned(
    parse("if cond then\n    x = 1; y = 2;\nelse\n    x = 3;")))
# → ["y"]

# detect side-effects statically
print(extract_side_effects(parse("UNPREDICTABLE; UNDEFINED;")))
# → {"unpredictable": True, "undefined": True, "see": False}

# ask a generator how it spells a type in its target language
gen = PythonGenerator()
print(gen.type_annotation(BOOL))   # → "bool"
print(gen.zero_value(BOOL))        # → "False"
gen_c = CGenerator()
print(gen_c.type_annotation(BOOL)) # → "bool"
print(gen_c.zero_value(BOOL))       # → "false"
```

To load the runtime library:

```python
from arm_transpiller import get_runtime_source

c_runtime    = get_runtime_source("c")
py_runtime   = get_runtime_source("python")
```

---

## Type system

Every value has a type that **carries its bit width** — that width is what the
generators need to mask bitwise results, to shift the operands of `:`, and to
sign-extend correctly.

| Type          | Meaning                                              | Example                               |
|---------------|------------------------------------------------------|---------------------------------------|
| `bitsN`       | Raw bit vector, `N` bits wide — ARM's `bits(N)`       | `Rd` → `bits4`                        |
| `uintN`       | Unsigned integer — **only** from `UInt()`            | `UInt(Rd)` → `uint32`                 |
| `sintN`       | Signed integer — **only** from `SInt()` and negation | `SInt(Rd)` → `sint32`                 |
| `bool`        | Truth value, 1 bit                                   | `setflags` → `bool`                   |
| `tuple[T, …]` | Several values at once                               | `Shift_C(…)` → `tuple[bits32, bits1]` |

`bitsN` is the default: encoding fields, register and memory contents,
literals, concatenations, bitwise results and everything the runtime returns
are bit vectors with no numeric interpretation.  A value only becomes a number
when the pseudocode says so — `UInt()` reads the bits as unsigned, `SInt()` as
signed — and only comparisons produce `bool`.  Where types merge, the most
specific interpretation wins (`sint` > `uint` > `bits` > `bool`) and the width
widens.

Both halves of a type reach the generated code.  The **width** fixes the shift
in a concatenation, the mask on a bitwise result, and the source width of a
sign extension.  The **kind** decides signedness: a `sintN` operand makes C's
`<`, `>`, `<=`, `>=`, `/`, `DIV` and `MOD` signed operations, since C's usual
arithmetic conversions would otherwise turn the signed side unsigned.

```console
$ echo "off = SInt(R[n]); x = off < 0; y = off DIV imm3;" | uv run arm-transpiller transpile --target c
off = SInt(R[n], 32);
x = ((sint32)off < (sint32)0);
y = ((sint32)off / (sint32)imm3);
```

Python needs no casts — its integers are already signed and arbitrarily wide —
so the same input transpiles to plain `off < 0` and `off // imm3`.  `==` and
`!=` are never cast: every value lives in a 32-bit container, so comparing the
bit patterns gives the same answer either way.

Types come from three places:

1. **Input variables** — `src/arm_transpiller/known_types.py` maps the names
   used in the ARM manual to their types (`Rd` → `bits4`, `registers` →
   `bits16`, any `imm<N>` → `bits<N>`, `TRUE`/`FALSE` → `bool`, …).
   Anything not listed can be supplied with `--input-types` / `input_types=`,
   which also overrides the table.
2. **Runtime functions** — the annotations in
   `armruntime/armruntime.py.template` are the single source of truth for what
   a call yields (`def ThumbExpandImm(ctx: Context, imm: bits12) -> bits32`).
   Annotate a function there and inference picks it up; a call to a function
   with no ARM return type raises `UnknownFunctionTypeError`.  The C runtime
   declares the same types as `typedef`s, so the header reads the same way
   (`static inline bits32 ThumbExpandImm(Context *ctx, bits12 x)`); a test
   checks the two runtimes agree on every function.
3. **Inference** — every variable the pseudocode defines gets the type of the
   expression assigned to it, propagated through concatenation (widths add),
   bitwise operators (widest operand wins), comparisons (`bool`), destructuring
   of tuple results, `for` loop bounds, and branch joins.

```console
$ echo "I1 = NOT(J1 EOR S); imm32 = SignExtend(S:I1:imm10:'0', 32);" \
      | uv run arm-transpiller types
{
  "inputs": {
    "J1": "bits1",
    "S": "bits1",
    "imm10": "bits10"
  },
  "outputs": {
    "I1": "bits1",
    "imm32": "bits32"
  }
}
```

A variable whose type cannot be determined is reported as `null`; using it
where a width is required (a concatenation operand, `SignExtend`, a bit range)
raises `UnknownVariableTypeError` instead of silently guessing 32 bits.

### Inference rules

Expressions:

| Pseudocode                        | Inferred type                              |
|-----------------------------------|--------------------------------------------|
| `13`, `0xFF`                      | `bits<bit-length>` (`bits4`, `bits8`)      |
| `'1'`, `'0101'`                   | `bits1`, `bits4` (one bit per character)   |
| `Rd`, `imm8`, `TRUE`              | from the known-types table or `--input-types` |
| `APSR.C`                          | `bits1`                                    |
| `R[n]`                            | `bits32`                                   |
| `registers<3>`                    | `bits1`                                    |
| `registers<7:4>`                  | `bits4`; non-literal bounds fall back to the base variable's width |
| `MemA[address,2]`, `MemU[…]`      | `bits16` — 8 bits per byte of the size argument |
| `a:b`                             | `bits(width a + width b)` — widths add     |
| `a EOR b`, `OR`, `AND`, `XOR`     | `bits(max width)`                          |
| `NOT(a)`, `~a`                    | `bits(width a)`                            |
| `-a`                              | `sint(width a)`                            |
| `a + b`, `-`, `*`, `/`, `MOD`, `DIV` | join of both operands (widest width, most specific kind) |
| `a == b`, `!=`, `<`, `>`, `<=`, `>=`, `&&`, `\|\|`, `!a` | `bool`      |
| `a IN {13,15}`, `a IN "10x"`      | `bool`                                     |
| `if c then a else b`              | join of both branches                      |
| `(a, b)`                          | `tuple[type a, type b]`                    |
| `UInt(x)` / `SInt(x)`             | `uint32` / `sint32` — `SInt` is emitted with the operand's width, so `SInt(imm8)` sign-extends from bit 7 |
| `SignExtend(x, 32)`, `ZeroExtend(x, 16)`, `Zeros(12)`, `Ones(4)` | `bits32`, `bits16`, `bits12`, `bits4` — the literal argument gives the width |
| `Replicate(x, 4)`                 | `bits(width x × 4)`                        |
| any other call                    | the runtime function's declared return type |

Statements:

| Pseudocode                     | Effect                                                    |
|--------------------------------|-----------------------------------------------------------|
| `x = expr`                     | `x` takes the type of `expr`; assigning twice joins the two |
| `(a, b) = expr`                | `a` and `b` take the elements of `expr`'s tuple type; `-` is skipped |
| `for i = 0 to 14`              | `i` is the join of the bounds — here `bits4`              |
| `if … then … else …`, `case …` | each branch is typed in its own scope, then joined into the enclosing one |
| `R[d] = …`, `APSR.N = …`       | architectural targets: not defined by the code, so the type comes from the table (`bits32`, `bits1`) |

### Type API

The type system has three layers: **create/lookup** types, **infer** them from
code, and **query** individual expressions through a `TypeInferencer` instance.

```python
from arm_transpiller import (
    TypeInferencer, infer_types, extract_variable_types,
    parse, parse_type, get_type, bits, uint, sint, BOOL,
    ScalarType, TupleType, runtime_return_types,
)

# ── Creating and inspecting types ──────────────────────────────
parse_type("bits12")                      # → ScalarType(kind='bits', width=12)
str(uint(32))                             # → 'uint32'
bits(4).width                             # → 4
bits(4).kind                              # → 'bits'

# ── Looking up input variable types ────────────────────────────
get_type("Rd")                            # → bits4
get_type("Rdm", {"Rdm": bits(3)})         # → bits3 (override wins)

# ── Runtime function return types ──────────────────────────────
runtime_return_types()["ThumbExpandImm"]  # → bits32
runtime_return_types().get("FancyDecode") # → None

# ── Inferring a whole program ──────────────────────────────────
program = parse("d = UInt(Rd); imm32 = ThumbExpandImm(imm12);")
infer_types(program)
# → {'d': uint32, 'Rd': bits4, 'imm32': bits32, 'imm12': bits12}

# overrides affect inference — here the concatenation gets 3 + 3 bits
infer_types(parse("x = Rdm:imm3;"), {"Rdm": "bits3"})
# → {'x': bits6, 'Rdm': bits3, 'imm3': bits3}

# ── Querying after inference ───────────────────────────────────
inferencer = TypeInferencer({"Rdm": "bits3"})
inferencer.infer(program)
inferencer.lookup("d")                    # → uint32
inferencer.type_of(program.statements[0].value)   # → uint32
inferencer.width_of_expr(program.statements[0].value)  # → 32
inferencer.try_type_of(program.statements[0].value)    # → uint32 (or None)

# ── Input/output split (CLI-ready) ─────────────────────────────
extract_variable_types(program)
# → {"inputs": {"Rd": "bits4", …}, "outputs": {"d": "uint32", …}}
```

Failures are explicit rather than defaulted:

| Exception                   | Raised when                                              |
|-----------------------------|----------------------------------------------------------|
| `UnknownVariableTypeError`  | a name is neither overridden, in the table, nor `imm<N>`  |
| `UnknownFunctionTypeError`  | a called function has no ARM return type in the runtime   |
| `TypeSyntaxError`           | a type string is not `bool` / `bits<N>` / `uint<N>` / `sint<N>` / `tuple[…]` |

There are four exception classes:
`UnknownVariableTypeError` and `UnknownFunctionTypeError` (which inherit from
`UnknownTypeError`) and `TypeSyntaxError` (which inherits from `ValueError`).
Generators can catch `UnknownTypeError` for type-inference failures and accept
a fallback — masks default to 32 bits, everything else propagates.  The CLI
turns them into a plain message and exit status 1:

```console
$ echo "x = SignExtend(a:b, 32);" | uv run arm-transpiller transpile --target c
Error: Cannot determine the type of 'a'. Add it to known_types.py (exact match or imm<N> pattern) or pass it as an input type override (e.g. a=bits4).
```

---

## Runtime model

Generated code calls into a small runtime library that emulates ARM pseudocode primitives (`UInt`, `SInt`, `ThumbExpandImm`, `SignExtend`, …). Side‑effecting statements operate on a standalone `sideffect_flags` variable and architectural state through a `Context` object. Both must be provided by the caller:

| Mechanism                | Behaviour                                                                                                                |
|--------------------------|--------------------------------------------------------------------------------------------------------------------------|
| **Architectural state**  | `apsr` (N/Z/C/V flags), `istate` (IT‑block state)                                                                        |
| **Side‑effects**         | `UNPREDICTABLE` sets `SIDEFFECT_UNPREDICTABLE`; `UNDEFINED` sets `SIDEFFECT_UNDEFINED`; `SEE` sets `SIDEFFECT_SEE`       |
| **Side‑effect detection**| `extract_side_effects(program)` walks the AST and detects side‑effects statically (no compilation needed)              |
| **Memory hooks**         | `MemA_read`/`MemA_write` (aligned) use `mem_a_read_hook`/`mem_a_write_hook`; `MemU_read`/`MemU_write` (unaligned) use `mem_u_read_hook`/`mem_u_write_hook` |
| **User data**            | `ctx.user_data` — attach arbitrary per‑context state                                                                     |
| **Return types**         | Each runtime function is annotated with the ARM type it produces — Python annotations, C `typedef`s (`bits32`, `uint32`, `sint32`, …); type inference reads the Python ones (see [Type system](#type-system)) |

### Caller contract

Before invoking transpiled code, the caller must provide:

- **`sideffect_flags`** — a zero‑initialised side‑effect bitfield:
  - **C:** `SideffectFlags sideffect_flags = 0;`
  - **Python:** `sideffect_flags: SideffectFlags = 0`
- **`Context`** — a context object holding architectural state:
  - **C:** `Context _ctx = {0}; Context *ctx = &_ctx;`
  - **Python:** `ctx = Context()`

The transpiled code reads and writes `sideffect_flags` and `ctx` directly.  Any called code
(e.g. the runtime library functions `ThumbExpandImm` / `ThumbExpandImm_C`) also takes
`sideffect_flags` as an explicit argument.

---

## Supported language subset

| Category          | Pseudocode                                     |
|-------------------|------------------------------------------------|
| Assignment        | `x = expr`, `x := expr`, `R[i] = expr`         |
| Destructure       | `(shift_t, shift_n) = expr`, `(-, y) = expr`   |
| Conditionals      | `if cond then … else …`                        |
| Inline if-expr    | `x = if cond then a else b`                    |
| Pattern match     | `x IN "10x"` (don't-care bits with `x`)        |
| Case/when         | `case expr when … when …`                      |
| For loops         | `for i = expr to expr …`                       |
| Logical           | `||`, `&&`, `!`, `NOT`                         |
| Comparison        | `==`, `!=`, `<`, `>`, `<=`, `>=`               |
| Membership        | `x IN {a, b}`, `x IN {3..5, 8}`               |
| Arithmetic        | `+`, `-`, `*`, `/`, `MOD`, `DIV`               |
| Bitwise           | `EOR`, `OR`, `AND`, `XOR`                      |
| Bit concat        | `a:b:c`                                        |
| Bit index         | `registers<i>`                                 |
| Memory access     | `MemA[addr, size]`, `MemU[addr, size]`         |
| Registers         | `R[expr]`                                      |
| Function calls    | `UInt(x)`, `ThumbExpandImm(x)`, …              |
| APSR fields       | `APSR.N`, `APSR.C`, …                          |
| Special           | `UNPREDICTABLE`, `UNDEFINED`, `SEE "…"`        |
| Comments          | `// …`, `/* … */`                              |

See `tests/fixtures/` for end‑to‑end examples: ADC, EOR, SUB, LSR, BL, LDRH, MRS, POP, REV, STR, AND, ORR, MVN, VABS, VCVT, VRINTA, VSEL.

> The grammar is a working subset. `while` / `repeat … until`, `elsif`, and type annotations are on the roadmap.

---

## How it works

```
pseudocode  ──▶  Lark parser  ──▶  AST (dataclasses)  ──▶  type inference  ──▶  CGenerator / PythonGenerator  ──▶  C / Python
                grammar.lark      ast_nodes.py           type_inference.py
                parser.py                                known_types.py
                                                         runtime_types.py

runtime  ──▶  armruntime.h.template / armruntime.py.template
```

1. **Parsing** — An [Earley](https://lark-parser.readthedocs.io/) grammar recognises the pseudocode. An indentation preprocessor converts scope‑by‑indentation into explicit `begin`/`end` blocks. A Lark `Transformer` builds a typed AST.
2. **AST** — Every construct is a frozen `@dataclass` (`Assignment`, `IfThen`, `BinaryOp`, `FunctionCall`, …).
3. **Type inference** — Every variable and expression gets a width‑carrying type (`bitsN` / `uintN` / `sintN` / `bool` / `tuple[…]`) from the known‑types table, the runtime's return annotations, and the code itself.
4. **Code generation** — Each target implements `CodeGenerator` and walks the AST with `match`/`case` dispatch, using the inferred types for masks, shifts, and sign extension.
5. **Runtime library** — C header (`armruntime.h.template`) and Python module (`armruntime.py.template`) provide all built‑ins.

---

## Development

```bash
uv run pytest        # all tests
uv run ruff check .  # lint
uv run ruff format . # auto‑format
uv run mypy src/     # type check (strict)
```

See [`AGENTS.md`](AGENTS.md) for the full contributor guide (naming conventions, test patterns, grammar rules).
