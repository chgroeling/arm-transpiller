# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
