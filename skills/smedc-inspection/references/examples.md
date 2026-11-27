# Synthetic inspection examples

These placeholders describe one synthetic enterprise, store, inspection date, employees,
departments, and sheets. Use the exact values from the authorized live calls in a real
inspection.

## Create and activate a template

Call `manage_inspection_templates` with a new template ID and the intended `targetType`.
This example uses an employee target. Use `store` or `department` for the other target
modes. A saved draft may omit `targetType`, but activation requires one of the three values.

```json
{
  "command": {
    "action": "create_active",
    "templateId": "11111111-1111-4111-8111-111111111111",
    "enterpriseKey": "synthetic-enterprise",
    "definition": {
      "title": "合成员工巡检示例",
      "targetType": "employee",
      "storeIds": ["22222222-2222-4222-8222-222222222222"],
      "questions": [
        {
          "questionId": "15151515-1515-4515-8515-151515151515",
          "title": "合成检查项",
          "components": [
            {
              "componentId": "12121212-1212-4212-8212-121212121212",
              "kind": "sop",
              "label": "合成依据",
              "text": "按用户确认的合成步骤核对。"
            },
            {
              "componentId": "13131313-1313-4313-8313-131313131313",
              "kind": "score",
              "label": "合成评分",
              "required": true,
              "minTenths": 0,
              "maxTenths": 100
            },
            {
              "componentId": "14141414-1414-4414-8414-141414141414",
              "kind": "photo",
              "label": "合成现场照片",
              "required": true
            }
          ]
        }
      ]
    }
  }
}
```

## List target candidates

For an employee target, use `query_employee_directory` with the inspection store and active
status. Page until `nextCursor` is null. The two employees below share a name; choose by
`employeeUid`, not by display name.

```json
{
  "request": {
    "action": "list_employees",
    "enterpriseKey": "synthetic-enterprise",
    "storeId": "22222222-2222-4222-8222-222222222222",
    "status": "active"
  }
}
```

The response identifies each record by UID, department, and store scope:

```json
{
  "employees": [
    {
      "employeeUid": "33333333-3333-4333-8333-333333333333",
      "name": "合成员工",
      "departmentId": "55555555-5555-4555-8555-555555555555",
      "departmentName": "合成前厅部",
      "scope": {
        "ownership": "store",
        "storeId": "22222222-2222-4222-8222-222222222222",
        "storeName": "合成门店"
      },
      "status": "active",
      "version": "1"
    },
    {
      "employeeUid": "44444444-4444-4444-8444-444444444444",
      "name": "合成员工",
      "departmentId": "16161616-1616-4616-8616-161616161616",
      "departmentName": "合成后厨部",
      "scope": {
        "ownership": "store",
        "storeId": "22222222-2222-4222-8222-222222222222",
        "storeName": "合成门店"
      },
      "status": "active",
      "version": "1"
    }
  ],
  "access": "all",
  "nextCursor": null
}
```

For a department target, use `list_directory` without `management`. The response gives
the active departments shared by stores in the business enterprise.

```json
{
  "request": {
    "action": "list_directory",
    "enterpriseKey": "synthetic-enterprise"
  }
}
```

```json
{
  "enterpriseKey": "synthetic-enterprise",
  "enterpriseName": "合成企业",
  "stores": [
    {
      "storeId": "22222222-2222-4222-8222-222222222222",
      "name": "合成门店",
      "status": "confirmed",
      "version": "1"
    }
  ],
  "departments": [
    {
      "departmentId": "55555555-5555-4555-8555-555555555555",
      "name": "合成前厅部",
      "status": "active",
      "version": "1"
    },
    {
      "departmentId": "16161616-1616-4616-8616-161616161616",
      "name": "合成后厨部",
      "status": "active",
      "version": "1"
    }
  ]
}
```

## Create a sheet for the selected target

Use the template's current `targetType`. For an employee target, send the selected
`employeeUid`. Never send a free-form `name` or both target fields.

```json
{
  "command": {
    "action": "create",
    "enterpriseKey": "synthetic-enterprise",
    "storeId": "22222222-2222-4222-8222-222222222222",
    "inspectionDate": "2026-01-15",
    "templateId": "11111111-1111-4111-8111-111111111111",
    "requestId": "synthetic-employee-create-1",
    "employeeUid": "33333333-3333-4333-8333-333333333333"
  }
}
```

For a department target, send the selected `departmentId` from the active list. This example
assumes the active template uses `targetType` `department`.

```json
{
  "command": {
    "action": "create",
    "enterpriseKey": "synthetic-enterprise",
    "storeId": "22222222-2222-4222-8222-222222222222",
    "inspectionDate": "2026-01-15",
    "templateId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "requestId": "synthetic-department-create-1",
    "departmentId": "55555555-5555-4555-8555-555555555555"
  }
}
```

For a store target, send neither target field. The service uses the inspection store and its
official name. This example assumes the active template uses `targetType` `store`.

```json
{
  "command": {
    "action": "create",
    "enterpriseKey": "synthetic-enterprise",
    "storeId": "22222222-2222-4222-8222-222222222222",
    "inspectionDate": "2026-01-15",
    "templateId": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    "requestId": "synthetic-store-create-1"
  }
}
```

## Find and read a sheet by target

A `day` read lists template entries and active sheet summaries. The summaries below belong to
the two same-name employees; they have different `sheetId` and `targetId` values but the same
`targetName` snapshot. A `sheet` detail returns the same three target fields.

```json
{
  "items": [
    {
      "kind": "template",
      "templateId": "11111111-1111-4111-8111-111111111111",
      "templateVersionId": "77777777-7777-4777-8777-777777777777",
      "activeRevision": 1,
      "title": "合成员工巡检示例",
      "targetType": "employee"
    },
    {
      "kind": "sheet",
      "sheetId": "88888888-8888-4888-8888-888888888888",
      "templateVersionId": "77777777-7777-4777-8777-777777777777",
      "sheetRevision": 1,
      "templateId": "11111111-1111-4111-8111-111111111111",
      "templateTitle": "合成员工巡检示例",
      "targetType": "employee",
      "targetId": "33333333-3333-4333-8333-333333333333",
      "targetName": "合成员工",
      "progress": "unfilled"
    },
    {
      "kind": "sheet",
      "sheetId": "99999999-9999-4999-8999-999999999999",
      "templateVersionId": "77777777-7777-4777-8777-777777777777",
      "sheetRevision": 1,
      "templateId": "11111111-1111-4111-8111-111111111111",
      "templateTitle": "合成员工巡检示例",
      "targetType": "employee",
      "targetId": "44444444-4444-4444-8444-444444444444",
      "targetName": "合成员工",
      "progress": "unfilled"
    }
  ],
  "nextCursor": null
}
```

## Stage an original photo

Call `write_inspections` with a readable absolute path. The launcher detects the MIME type when
`mediaType` is omitted. Use the returned `photoId` before its `expiresAt`.

```json
{
  "command": {
    "action": "stage_photo",
    "enterpriseKey": "synthetic-enterprise",
    "storeId": "22222222-2222-4222-8222-222222222222",
    "inspectionDate": "2026-01-15",
    "requestId": "synthetic-photo-1",
    "filePath": "/absolute/path/synthetic-photo.png"
  }
}
```

## Fill a blank score and attach a local photo in one call

Call `write_inspections` after reading the sheet's fixed version ID and current photo component
revision. The example assumes the evidence supports 8.5 points and the photo belongs to this
component. Omit `photoIds` if there are no staged references to attach with the local original.

```json
{
  "command": {
    "action": "patch",
    "patches": [
      {
        "sheetId": "88888888-8888-4888-8888-888888888888",
        "templateVersionId": "77777777-7777-4777-8777-777777777777",
        "requestId": "synthetic-patch-1",
        "changes": [
          {
            "componentId": "13131313-1313-4313-8313-131313131313",
            "op": "fill",
            "value": 85
          },
          {
            "componentId": "14141414-1414-4414-8414-141414141414",
            "op": "appendLocalPhotos",
            "expectedComponentRevision": 1,
            "photos": [
              {
                "requestId": "synthetic-photo-2",
                "filePath": "/absolute/path/synthetic-photo-2.png"
              }
            ],
            "photoIds": [
              "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
            ]
          }
        ]
      }
    ]
  }
}
```

If the patch reports a conflict with an uncommitted photo reference, re-read the sheet. Reuse the
reference with `appendPhotos` and that component's current revision under a new sheet request ID.
For an uncertain response, verify the current answer before deciding which photos still need binding.
