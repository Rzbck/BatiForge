# AGENTS.md — BatiForge

BatiForge reconstructs real-world buildings from authoritative footprints, LiDAR, imagery and photogrammetry.

This file contains permanent working rules. Current operational state belongs in `HANDOFF.md`.

## Bootstrap for every substantial AI session

1. Fetch the repository and identify the real branch, HEAD and CLEAN/DIRTY state.
2. Read this file.
3. Read `HANDOFF.md`.
4. Read only the architecture/decision/exec-plan documents relevant to the task.
5. Check recent relevant commits, branches, PRs and Issues when they may be newer than the handoff.
6. Inspect the actual code/tests involved before proposing changes.

Never reconstruct current project state only from an old chat.

## Evidence vocabulary

Keep these states distinct:
- `HOST_VALIDATED`: observed from an actual local/runtime execution.
- `REPO_VALIDATED`: durable repository state verified in Git.
- `IMPLEMENTED_NOT_VALIDATED`: code exists but required validation is missing.
- `EXPERIMENTAL`: hypothesis/prototype, not production truth.
- `BLOCKER`: prevents the next safe step.
- `NEXT`: agreed next operation.

Code existing is not equivalent to a validated result.

## Sources of truth

- Git HEAD + active code/config say what exists.
- Tests prove only their tested scope.
- Runtime/host output proves what actually executed.
- `HANDOFF.md` is the compact current snapshot.
- `docs/ARCHITECTURE.md` is durable architecture.
- `docs/decisions/` stores durable architectural decisions.
- `docs/exec-plans/active/` stores bounded ongoing work.

If these disagree, investigate. Do not silently invent a reconciliation.

## Git discipline

`main` is the published baseline.

After bootstrap, non-trivial work uses a dedicated branch. When several AI tasks are active concurrently: **1 active task = 1 branch = 1 dedicated worktree**.

Before writing in a worktree, verify repository, path, branch, HEAD and CLEAN/DIRTY state.

Never force-push to clean history, use destructive reset/clean as routine recovery, overwrite concurrent changes, use blind `git add -A`, or claim validation for a SHA other than the exact SHA tested.

Promotion to `main` remains a human decision.

## Geospatial/data invariants

Coordinates, CRS, datum, units, georeferencing, provenance and source identifiers are first-class data. Never change them silently.

Large source data and generated geometry stay outside Git. Git stores code, configuration, source identifiers/URLs, checksums when useful, reproducible recipes and compact validation results.

Do not version workspaces, downloaded LiDAR/imagery, COLMAP databases/results, native tool distributions, caches or large generated meshes.

## Providers and licensing

Each provider integration must document API/source, provenance, relevant license/terms, coordinate conventions and failure/rate-limit behavior. Do not bulk-download before these are understood.

## Validation

Deterministic tests must be reproducible from the repository. Visual, photogrammetric and host-specific results keep separate evidence. Before attributing a verifier result to a candidate, verify the exact candidate SHA.

## PowerShell

Prefer short, complete copy/paste blocks. Avoid interactive multi-line constructs that can leave PowerShell at the `>>` continuation prompt. For substantial scripts, version a `.ps1` under `scripts/` and invoke it instead of pasting hundreds of lines into the console.

## Handoff maintenance

Update `HANDOFF.md` after material events only: meaningful validation/rejection, new blocker, architectural decision, promotion/release or genuine change of next step.

Do not paste conversation transcripts into the repository. Historical reasoning belongs in commits, PRs, Issues, decisions and completed exec plans.
