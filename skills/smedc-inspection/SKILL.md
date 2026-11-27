---
name: smedc-inspection
description: 使用企业智脑（SMEDC）查询门店巡检卷、按现场证据填报及补图，或把检查标准整理成模板草稿。 Use for SMEDC store inspections and inspection templates.
---

# SMEDC Inspection

## Check the connection

Use the employee's authenticated `smedc` MCP connection. Follow `smedc-mcp` for installation,
login, repair, and the approved launcher pin. Photo staging and one-call attachments require the
matching cutover launcher and service. Inspection target selection requires a connection whose
inspection schemas expose `targetType`; if the connected schema does not, stop and report the
version mismatch instead of guessing a target. Live use requires the matching service and current
access to the target. If any prerequisite fails, identify the missing tool, unavailable service,
or denied scope. Use the inspection tools for inspection data and photos.

| Tool | Actions |
| --- | --- |
| `query_inspections` | `context`, `day`, `sheet`, `photo` |
| `write_inspections` | `create`, `patch`, `void`, `preview_replacement`, `replace`, `stage_photo` |
| `manage_inspection_templates` | `list`, `preview`, `create_active`, `create_draft`, `save`, `activate`, `deactivate` |

Put `action` and its fields inside `command`. See
[synthetic examples](references/examples.md) when choosing a target, building a draft, uploading
a photo, or patching a sheet.

## Choose the inspection target

Use the active template's `targetType` when creating a sheet.

- `store`: omit both selector fields. The service records the inspection store ID and
  official name.
- `employee`: call `query_employee_directory` with `request.action` `list_employees`,
  `enterpriseKey`, the inspection `storeId`, and `status: "active"`. Page with `nextCursor`.
  Choose an active employee with that `scope.storeId` and send their `employeeUid`.
- `department`: call `query_employee_directory` with `request.action` `list_directory`
  and `enterpriseKey`. The ordinary request omits `management` and returns only active
  departments shared by the enterprise's stores. Send the selected `departmentId`.

Employee candidates depend on directory read access. With `partial` access, explain that
the list is limited to visible employees and proceed if the requested target is unambiguous.
If candidates are empty after paging or access is `none`, report that no eligible target
is visible. When several candidates could match, ask which one and give their names and IDs.
For same-name employees, also show their department names.

Use a current directory result for the selector. The service rechecks template eligibility,
store fill access, and the target's activity and ownership for a new create. Employee targets
also require current employee profile access at that store. An ineligible identifier is rejected
even if it came from an earlier lookup. Match existing sheets by `targetType` and `targetId`.
Their `targetName` records the name at creation and can outlast directory changes.

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

- For one-call attachment, use `write_inspections` with `command.action: "patch"` and a change
  with `op: "appendLocalPhotos"`, `componentId`, the current `expectedComponentRevision`, and
  `photos: [{requestId, filePath, mediaType?}]`. Add optional `photoIds` for previously staged
  references. Each local JPEG or PNG needs an absolute path and a stable photo request ID.
- To stage without binding, use `write_inspections` with `command.action: "stage_photo"`,
  `enterpriseKey`, `storeId`, `inspectionDate`, `requestId` and `filePath`. The launcher checks
  current fill access before reading local files. Optional `mediaType` must match the bytes.
  Reuse the staged `photoId` for relevant components or sheets in the same store and date
  before `expiresAt`. Bind staged IDs with `appendPhotos` and the current component revision.
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
- On a conflict such as `nonempty`, `revision`, or `version`, re-read the affected sheet and
  preserve its saved answers. A local attachment can return `failed`, `conflict` or
  `unconfirmed` with `uncommittedPhotoTargets` containing component IDs, staged photo IDs
  and expiry. After verifying
  the current sheet state, reuse valid unbound references with `appendPhotos`, the refreshed
  `expectedComponentRevision`, and a new sheet `requestId` for a changed command.
- For a lost response, replay the identical command and `requestId` within 24 hours.
  A create replay requires current fill access and the original sheet to still be active.
  Reusing the create `requestId` for a different target within the same actor, enterprise,
  store, date, and template causes an idempotency conflict. Use a new key for a changed
  command. If the replay fails or the window has passed, read `day` and compare
  `targetType` and `targetId` before deciding whether a new create is needed.
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
