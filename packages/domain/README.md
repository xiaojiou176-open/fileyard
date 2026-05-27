# packages/domain

This is the rule layer.

## Responsibilities

- manifest and schema constants
- error codes and state enums
- naming, normalization, and rollback integrity rules
- domain semantics for AI-facing prompts and results

## Boundary

- define rules only
- do not perform I/O here
- change contracts here before changing higher layers
