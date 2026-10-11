# Contributing to crashvault

Thanks for helping make this log recovery and storage project easier to inspect and reproduce.
Small documentation fixes and reproducible bug reports are useful contributions.

## Before changing behavior

Read the README, input/model contract and measured-results report. Open an issue for a
substantial behavior or format change so the scope can be discussed first. These are
educational engineering projects; production readiness is not established.

## Report a bug

Include: Exact tab-separated command sequence, sync mode, OS/filesystem, Python/compiler versions, error output and a minimal synthetic log. Never upload real keys or personal data.

Use the smallest synthetic input that reproduces the problem. State expected and actual
behavior, and include the exact command and commit/version. Screenshots may supplement
text output, but should not replace a reproducible command.

## Development checks

Follow the README build instructions for your OS, then run:

```sh
python -m unittest discover -s tests -v
```

Keep C11 builds warning-free using the flags in the README. Linux CI also runs address
and undefined-behavior sanitizers. A documentation-only change needs a link/command
review; a behavior change needs a regression check that exercises the changed behavior.

Example entry point (run from the repository root):

```sh
python python/crashvault.py demo.log
```

## Evidence required for behavior changes

Preserve byte-for-byte Python/C format parity and the distinction between incomplete tails and complete corruption. State the sync boundary. Changes to recovery need repaired-byte and recovered-state checks; do not claim power-loss coverage from process termination alone.

For performance claims, retain the raw samples, workload, environment, measurement
boundary and reproduction command. Do not generalize one workload into a universal
speedup. Avoid committing large generated files unless they are an agreed reference.

## Starter ideas

### Add C storage-call fault injection

Propose an injectable write/sync seam before coding; verify that failures do not acknowledge success and that reopen behavior remains defined.

### Document a synthetic recovery walkthrough

Show a small PUT/overwrite/DEL sequence, a copied prefix-truncated log and recovery results without modifying the original example log.

These are suggestions, not assigned tasks or promised roadmap commitments. Check open
issues before starting. A pull request should explain the problem, change, validation
and limitations. Keep unrelated edits separate and respond respectfully to review.

AI-assisted contributions are welcome when the author checks the code and can explain
the implementation and evidence. Contributions are made under this repository's MIT license.
