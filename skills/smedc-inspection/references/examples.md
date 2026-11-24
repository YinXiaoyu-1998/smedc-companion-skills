# Synthetic inspection examples

These placeholders describe a single synthetic store, date, and sheet. Use the exact values from the authorized live calls in a real inspection.

## Create and activate a template

For an explicitly requested saved draft, use `create_draft` with the definition you have so far.

Call `manage_inspection_templates` with a new template ID.

```json
{
  "command": {
    "action": "create_active",
    "templateId": "11111111-1111-4111-8111-111111111111",
    "enterpriseKey": "synthetic-enterprise",
    "definition": {
      "title": "合成巡检示例",
      "copyMode": "single",
      "storeIds": [
        "22222222-2222-4222-8222-222222222222"
      ],
      "questions": [
        {
          "questionId": "33333333-3333-4333-8333-333333333333",
          "title": "合成检查项",
          "category": "合成分类",
          "components": [
            {
              "componentId": "44444444-4444-4444-8444-444444444444",
              "kind": "sop",
              "label": "合成依据",
              "text": "按用户确认的合成步骤核对。"
            },
            {
              "componentId": "55555555-5555-4555-8555-555555555555",
              "kind": "score",
              "label": "合成评分",
              "required": true,
              "minTenths": 0,
              "maxTenths": 100
            },
            {
              "componentId": "88888888-8888-4888-8888-888888888888",
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

## Stage an original photo

Call `upload_inspection_photo` with a readable absolute path. The launcher detects the MIME type when `mediaType` is omitted.

```json
{
  "enterpriseKey": "synthetic-enterprise",
  "storeId": "22222222-2222-4222-8222-222222222222",
  "inspectionDate": "2026-01-15",
  "requestId": "synthetic-photo-1",
  "filePath": "/absolute/path/synthetic-photo.png"
}
```

## Fill a blank score and attach the photo

Call `write_inspections` after reading the actual sheet. Use its fixed version ID and the `photoId` returned by upload. The example assumes the evidence supports 8.5 points and the photo belongs to this component.

```json
{
  "command": {
    "action": "patch",
    "patches": [
      {
        "sheetId": "66666666-6666-4666-8666-666666666666",
        "templateVersionId": "77777777-7777-4777-8777-777777777777",
        "requestId": "synthetic-patch-1",
        "changes": [
          {
            "componentId": "55555555-5555-4555-8555-555555555555",
            "op": "fill",
            "value": 85
          },
          {
            "componentId": "88888888-8888-4888-8888-888888888888",
            "op": "appendPhotos",
            "photoIds": [
              "99999999-9999-4999-8999-999999999999"
            ]
          }
        ]
      }
    ]
  }
}
```
