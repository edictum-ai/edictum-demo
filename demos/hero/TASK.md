# Hero Demo Task

Add a deterministic `--verbose` flag to the sample CLI used by the hero demo.

Acceptance criteria:

- Read the task brief and the workspace README before editing.
- Create a feature branch before implementation.
- Run a baseline verification command before making changes.
- Implement the verbose flag in `src/hero_cli.py`.
- Trigger at least one blocked action during implementation so the workflow emits a visible block event.
- Run local verification after the change.
- Send the change through external review.
- The first review must request a reset back to `implement`.
- The second review must approve the change.
- Update the README after approval.
- Stage, commit, push, open a PR, and check CI.

The hero demo intentionally uses deterministic file and bash tool behavior so the run can be repeated and compared.
