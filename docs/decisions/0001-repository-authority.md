# ADR 0001 — Repository is the durable project authority

Status: accepted

A previous chat is not the source of truth for BatiForge.

The durable restart path is:

Git state -> `AGENTS.md` -> `HANDOFF.md` -> relevant architecture/decision/exec-plan -> active code/tests/evidence.

`HANDOFF.md` is a compact current snapshot, not a transcript or historical diary.

Git commits, PRs, Issues, architectural decisions and completed execution plans carry history.
