---
id: "add-functionality-to-add-session-cookies-on-sessio-2026-09-24"
status: "done"
priority: "medium"
assignee: null
epic: null
dueDate: null
created: "2026-09-24T10:32:05.156Z"
modified: "2026-09-24T13:30:00.000Z"
completedAt: "2026-09-24T13:30:00.000Z"
labels: []
order: "a2"
---
# Add Functionality To add session cookies on Sessions tab

As we can not use the browser based method reliably. so get the cookies local run and than dump them usin g ui

## Done

- Export: `GET /api/sessions/{name}/storage-state` + UI **Export** button
- Import: `POST /api/sessions/import` + `PUT /api/sessions/{name}/storage-state` + UI **Import session cookies** panel
