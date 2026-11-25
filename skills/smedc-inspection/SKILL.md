---
name: smedc-inspection
description: 使用企业智脑（SMEDC）查询门店巡检卷、按现场证据填报及补图，或把检查标准整理成模板草稿。 Use for SMEDC store inspections and inspection templates.
---

# SMEDC Inspection

## Check the connection

Use the employee's authenticated `smedc` MCP connection. Follow `smedc-mcp` for installation,
login, repair, and the approved launcher pin. The published launcher 0.23.0 includes all four
inspection tools. Inspection target selection also requires a launcher and service whose
inspection schemas expose `targetType`; if the connected schema does not, stop and report the
version mismatch instead of guessing a target. Live use requires the matching service and current
access to the target. If any prerequisite fails, identify the missing tool, unavailable service,
or denied scope. Use the inspection tools for inspection data and photos.

| Tool | Actions |
| --- | --- |
| `query_inspections` | `context`, `day`, `sheet`, `photo` |
| `write_inspections` | `create`, `patch`, `void`, `preview_replacement`, `replace` |
| `manage_inspection_templates` | `list`, `preview`, `create_active`, `create_draft`, `save`, `activate`, `deactivate` |
| `upload_inspection_photo` | Flat upload input, with no action |

Put `action` and its fields inside `command` for the first three tools. See
[synthetic examples](references/examples.md) when choosing a target, building a draft, uploading
a photo, or patching a sheet.

## Choose the inspection target

A template has one `targetType`: `store`, `employee`, or `department`. It may be absent from
a draft and must be set before activation. Create a sheet from the active template's current
`targetType`; do not infer it from the user's account, an older sheet, or a typed name. A sheet
keeps its target when it is filled, replaced, voided, or after the template changes.

- `store`: send neither `employeeUid` nor `departmentId`. The sheet uses the inspection store
  and its official name.
- `employee`: use `query_employee_directory` with `request.action` `list_employees`,
  `request.enterpriseKey`, `request.storeId` set to the inspection store, and
  `request.status` set to `active`. Page with `nextCursor`. Select an employee whose
  `scope.storeId` is that store; group-level, other-store, departed, and unauthorized records
  are not candidates. Send its `employeeUid`.
- `department`: use `query_employee_directory` with `request.action` `list_directory` and
  `request.enterpriseKey`. Select a department with `status` `active`; do not use
  `management: true` or a retired department. Send its `departmentId`. Stores in one
  business enterprise share this department list.

Candidate reads need directory read access. `list_employees` returns `employees`, `access`
(`none`, `partial`, or `all`), and `nextCursor`. If access is not `all`, or the page is
empty, state the visible scope and ask the user to choose from the returned candidates.
Inspection sheet read access does not open a searchable employee roster. Never send a free-form
name, type a name, or reuse an identifier from another store, enterprise, or object type.

Same-name people are different targets. Show the employee name, department name,
`departmentId`, and `employeeUid`, and choose by `employeeUid`. For departments, show the
department name and `departmentId`. Never distinguish candidates only by display name.

The service rechecks the template, store fill access, and the target's visibility, activity,
and ownership in the create transaction. A cached or guessed identifier is still rejected. Use
`targetId`, not `targetName`, to match a live candidate: a sheet keeps its creation snapshot
and stays readable under inspection read access after the employee leaves, changes name or
store, or the department retires.

## Find the sheet

1. Use `context` to resolve the exact enterprise and official store IDs. Read access covers
   sheets and their authorized photos. Fill access is required for writes and uploads.
   Template maintenance authorizes drafts for that enterprise. Use the user's inspection date
   and keep to their selected scope.
2. Use `day` with `enterpriseKey`, `storeId`, and `inspectionDate` to find sheets and eligible
   template entries. Page until `nextCursor` is null. Each template entry carries
   `targetType`. Each sheet summary carries the creation snapshot `targetType`, `targetId`,
   and `targetName`. If several sheets match, ask which one by its target and `sheetId`. A
   read request ends with the requested read results.
3. When asked to create a sheet, use the scope, `templateId`, `requestId`, and the field for the
   template's `targetType`: `employeeUid` for employee, `departmentId` for department, or
   neither for store. Never send both target fields or a `name`. There is at most one active
   sheet for a template, store, inspection date, and target. A create for that key returns the
   active sheet, so treat it as resuming the same sheet; a different target creates a separate
   sheet.
4. Read the selected `sheetId` through all relevant question pages. Use the sheet's fixed
   `templateVersionId`, SOP, answers, and revisions when preparing changes. The detail returns
   the same `targetType`, `targetId`, and `targetName` snapshot. Restart at the first page
   on `stale_cursor` and re-evaluate against the current revision.

## Fill with evidence

Use observed facts, readable source material, or the user's account of what they saw. Leave gaps
where the available evidence cannot establish an answer or the SOP calls for an on-site
demonstration. Use score tenths (`85` for 8.5 points), status option IDs, and nonblank comments.
Use `fill` for an empty score, status, or comment and `appendPhotos` for relevant photo IDs.
If new evidence conflicts with an existing answer, show the discrepancy and request direction
unless the user already authorized that correction. Use the current `expectedComponentRevision`
with `set`, `clear`, or `removePhotos`.

### Photo evidence

- Upload an original JPEG or PNG with flat `enterpriseKey`, `storeId`, `inspectionDate`,
  `requestId`, and an absolute, readable `filePath`. The launcher checks current fill access
  before reading the file. `mediaType` is optional and must match the bytes when supplied.
  Use the returned `photoId` before its staging `expiresAt`. Reuse the ID for relevant
  components or sheets in the same store and date.
- For an existing photo, `query_inspections` action `photo` takes `photoId`. The launcher
  verifies the original and returns `localPath` with `photoId`, `mediaType`, `byteLength`,
  and `sha256`. Open that file if available to the agent. An upload takes `filePath`.
- If the model can see the image but the launcher cannot read the original, save the supported
  textual findings and leave the photo component open. Give the employee the official store
  name, inspection date, template title, target type, target name (and `targetId` when names
  repeat), question title, and photo component label so they can find the field in the web app.
  When titles or labels repeat, include the question's position across the full ordered sheet
  and the component's position within that question. Include `sheetId`, `questionId`, and
  `componentId` for traceability. Base observations on the evidence you could actually see.

### Save and reconcile

Use `patch` for 1–10 distinct sheets with 1–50 distinct component changes per sheet. Each
entry carries `sheetId`, `templateVersionId`, and its own `requestId`. The service applies
each sheet atomically and returns results in request order.

- `applied` gives the committed revision, progress, optional score, total required gaps, and
  the first 20 gaps. Page the sheet detail when you need the full list.
- On a conflict such as `nonempty`, `revision`, or `version`, re-read the affected sheet,
  preserve its saved answers, and use a new key for a changed command.
- For a lost response, replay the identical command and `requestId` within the first 24 hours
  while the target remains authorized. After that window, inspect the target before deciding
  on a new command. For an uncertain create, read `day` and compare `targetType` and
  `targetId` before attempting another create. Reusing a `requestId` with a different
  target or scope is an idempotency conflict; use a new request for a different target.
  Report inaccessible or failed targets separately and preserve successful results.
- The web app and MCP read and write the same sheet contract. A sheet created in either entry
  point appears in the other with the same `sheetId` and target snapshot.

Report applied and pending work by sheet and target, including missing evidence and unassigned
photos. Use the service's progress and scoring results. Pass/fail judgments, red lines, and
on-site exceptions require the evidence and human decisions specified in the SOP.

## Maintain templates and sheet versions

Template maintenance uses the selected enterprise's current permission. When drafting from a
provided rubric, extract the actual criteria, exclude sample answers and duplicate totals, and
preserve conditional evidence and red-line guidance in the SOP. Flag unresolved criteria or
score discrepancies to the maintainer.

For a new usable template, confirm the intended stores and `targetType`, then use
`create_active` with a complete definition and a new `templateId`. A draft may omit
`targetType`; activation requires one of `store`, `employee`, or `department`. A successful
request creates the template and activates its first version. If validation returns missing
fields, report them and correct the definition before retrying. Check the template by the same
ID if the response is lost.

Use `create_draft` only when the user explicitly asks to save a draft for review. Check the
connected tool schema for both actions. When formal creation is unavailable, report the
missing capability. The older `create` action saves a draft and is suitable only for an
explicit draft request.

Use `list` and paged `preview` for saved drafts, then `save` with the complete definition
and `expectedDraftRevision`. Preserve IDs for retained questions and components. Check
preview issues, `targetType`, store IDs, and maximum score before presenting the draft. With
explicit approval, `activate` the previewed revision. Use `deactivate` with the current
revision to stop new sheets from this template. Existing sheets remain usable.

For an explicit sheet replacement, use `preview_replacement` with `includeTitles: true`. Show the retained,
cleared, added, and removed questions by title, including the previous and current titles for renamed items. Submit `replace` only after authorization for that comparison,
using both previewed versions, `expectedActiveRevision`, `expectedSheetRevision`, and
`requestId`. Replacement keeps the sheet's original target. Changing a template's
`targetType` affects only newly created sheets. Void only on explicit direction with the
current `expectedSheetRevision` and `requestId`.
