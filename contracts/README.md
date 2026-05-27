# contracts

This directory is the contract layer.

## Structure

- `contracts/api/`: public API contracts
- `contracts/runtime/`: filesystem, env, and runtime contracts
- `contracts/governance/`: public surface, required checks, root policies
- `contracts/docs/`: docs rendering and docs-scope contracts
- `contracts/upstreams/`: upstream and compatibility contracts
- `contracts/ai/`: AI-eval inputs and baselines

## Boundary

High-drift facts should land here before they are projected into docs or gates.
