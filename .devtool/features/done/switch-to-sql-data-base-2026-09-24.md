---
id: "switch-to-sql-data-base-2026-09-24"
status: "done"
priority: "medium"
assignee: null
epic: null
dueDate: null
created: "2026-09-24T05:38:23.211Z"
modified: "2026-09-24T08:35:00.000Z"
completedAt: "2026-09-24T08:35:00.000Z"
labels: []
order: "a0"
---
# SWITCH TO SQL DATA BASE

Migrated file-backed JSON stores to SQLite.

- DB module: `backend/db.py`
- Default path: `data/hexawealth.db`
- Override: `HEXAWEALTH_DB_PATH`
- One-time import of existing `data/{sessions,sources,schedules,automations,profiles,engagements}/*.json`
- Run logs stored in `run_logs` (append-only) instead of rewriting whole run files
