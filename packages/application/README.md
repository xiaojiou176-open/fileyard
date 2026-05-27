# packages/application

This is the orchestration layer.

## Responsibilities

- `analyze_media.py`: build manifests
- `apply_command.py`: execute by manifest
- `rollback_command.py`: revert executed changes
- `reporting.py`: produce summaries and reports

## Boundary

- may call infrastructure
- must not move provider or I/O details back into CLI or API entrypoints
- must not add AI decision-making into `apply` or `rollback`
