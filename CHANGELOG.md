# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.0.0] — 2026-07-31

### Changed

- **Breaking:** `sideeffect` field removed from `Context`.  Transpiled code uses a
  standalone `sideffect_flags` variable (type `SideffectFlags`, aliased from
  `uint32_t` in C and `int` in Python) instead of `ctx->sideeffect` /
  `ctx.sideeffect`.  Runtime functions `ThumbExpandImm` and `ThumbExpandImm_C`
  take `sideffect_flags` as an explicit first argument.  The caller must provide
  `sideffect_flags = 0` and a `Context` before invoking transpiled code
  (documented as caller contract in the README).

## [2.0.1] — 2026-08-02

### Fixed

- Inline comments (trailing `//` on a code line) are now emitted on the same line
  as their associated statement in generated C and Python output, instead of on a
  separate line.

## [2.0.0] — 2026-08-02

### Changed

- **Breaking:** Side-effect flags are now passed as a standalone `sideffect_flags`
  variable instead of being embedded in `Context`.

## [1.1.1] — 2026-07-27

### Fixed

- `pyproject.toml` version was not bumped in the 1.1.0 release.

## [1.1.0] — 2026-07-27

### Added

- SSAT T1 decoder test fixture and supporting runtime infrastructure
  (`HaveDSPExt`, `sh`, `sat_imm` types).

### Changed

- Renamed `VFPExpandImm` parameter `N` → `n` in both runtime templates to fix
  ruff N803 warning.

### Fixed

- Armruntime Python template now passes ruff lint and format checks.

## [1.0.0] — Initial Release
