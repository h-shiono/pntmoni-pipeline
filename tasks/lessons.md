# Pipeline Lessons Learned

This file accumulates pipeline-specific lessons. Cross-cutting
lessons that apply to multiple repositories should be promoted to
`pntmoni-docs/50-operations/` (see ADR 0002 "Lessons sharing").

Format:

```markdown
## [YYYY-MM-DD] <category>: <short title>

**Mistake:** What went wrong.
**Root cause:** Why it happened.
**Fix applied:** What was done.
**Rule:** One-line rule to prevent recurrence.
**Tags:** #python #claslib #mrtklib #quarto #parquet #cost #uv
```

Tags help filter relevant lessons at the start of a session. Read
all lessons tagged for your current work domain before starting.

If a lesson is violated twice: escalate its rule into
`pntmoni-pipeline/CLAUDE.md` Core Principles or promote to
`pntmoni-docs/50-operations/` for cross-repo visibility.

---

(No lessons recorded yet — this file will accumulate as the pipeline
develops. Initial lessons inherited from `pntmoni-cloud/tasks/lessons.md`
that may apply here:

- Be careful with parallel build resource consumption (cmake -j)
- Prefer native command tools over shell-piped variants for reproducibility
- Always verify paths and submodules in fresh checkout scenarios

These will be re-recorded here with pipeline-specific context as
they manifest.)
