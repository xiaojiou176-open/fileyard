# Security Policy

Think of this file like the fire alarm instructions in a building: it tells
you which channel is safe to use first, and which channels you must not use.

## Supported Scope

This repository is maintained as a limited-maintenance public project.
We welcome responsible vulnerability reports, but we do not offer
enterprise support SLAs, guaranteed patch windows, or long-term support
for historical releases.

The default supported scope is:

- The latest commit on the `main` branch
- The latest state of the current major version

## Private Reporting

GitHub Private Vulnerability Reporting is the primary private reporting
channel for this repository. If it is enabled, use that private channel
first.

Private reporting URL:

- https://github.com/xiaojiou176-open/fileorganize/security/advisories/new

No separate fallback private email is currently configured for this
repository. Repository owners must publish a real private reporting channel
here before claiming a non-GitHub fallback.

Today, that means the private route is:

1. Open GitHub Private Vulnerability Reporting if it is available.
2. Do not use public issues, public pull requests, public discussions,
   screenshots, or chat threads for vulnerability details.
3. If the GitHub private route is unavailable, stop there and wait for this
   policy to be updated with a real fallback channel.

If the GitHub private channel is unavailable, do not treat placeholder
addresses as valid and do not disclose vulnerability details publicly.
Wait until this policy is updated with a real private fallback channel.

Do not report security vulnerabilities in public GitHub issues, public pull
requests, discussions, screenshots, or chat threads.

## What To Include

- Affected version, branch, or commit
- Reproduction steps with the smallest safe proof
- Expected behavior versus actual behavior
- Impact summary, such as data exposure, privilege escalation, arbitrary
  file write, command execution, or supply-chain risk
- Any known mitigation or temporary workaround

## Out Of Scope

- Missing credentials that only make live features unavailable
- Documentation wording issues that do not create a security consequence
- Local custom scripts or environments that differ from the repository's
  default supported workflow

## Response Posture

We will review the report, validate whether the issue is real, and respond
with a fix, mitigation, or explicit risk statement when possible.
Please treat this repository like a small workshop, not a 24/7 help desk:
you will get a careful response, but not a guaranteed on-call rotation.
