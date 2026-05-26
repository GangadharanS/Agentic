# SNS / async export schemas

- **`export-completion-event.schema.json`** — JSON Schema for the **string body** published to `TcFileServiceTopic` (the SNS `Message` payload after subscription fan-out wraps it; see fixtures).

## SNS message attributes (filter policies)

Consumers on a shared topic should filter using attributes (recommended names):

| Name        | Type   | Example                   | Purpose                          |
|------------|--------|---------------------------|----------------------------------|
| `eventType`| String | `connect.export.completed`| Route revision vs email vs other |
| `jobType`  | String | `EXPORT`                  | Narrow to export jobs           |
| `schemaVersion` | String | `1.0.0`              | Version subscriptions over time |

Publishers MUST set the same values in the JSON body **and** in **MessageAttributes** for reliable filter policies.

Golden examples: [../fixtures/](../fixtures/).
