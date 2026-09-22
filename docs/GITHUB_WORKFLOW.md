# GitHub workflow

`main` is the published baseline.

After bootstrap:
- non-trivial work uses a dedicated branch;
- concurrent AI work uses one branch + one worktree per active task;
- the permanent main worktree remains on `main`;
- branch, HEAD and CLEAN/DIRTY state are checked before writes;
- validation is attributed to the exact tested SHA;
- no blind `git add -A`;
- no routine `reset --hard`, `clean -fdx`, force-push or destructive history rewrite;
- final diff and expected validation are inspected before promotion;
- promotion to `main` is a human decision.

A worktree is never deleted solely because its remote branch disappeared. Its local CLEAN/DIRTY state and preservation status must be known first.
