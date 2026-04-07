# CLAUDE.md (tests)

Quick execution memory for `tests/`.

## Focus

- Use the smallest meaningful test slice first.
- Reproduce failures before broadening scope.
- Keep fixtures reusable and explicit.

## Useful paths

- `tests/unit/`
- `tests/integration/`
- `tests/e2e/`

## Common validation targets

- config changes: `tests/unit/test_config_loader.py`
- analyze changes: `tests/unit/test_analyze_media.py`
- apply / rollback changes: `tests/unit/test_apply_changes.py`, `tests/e2e/test_run_rollback_script.py`
