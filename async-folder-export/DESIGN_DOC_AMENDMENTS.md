# Amendments for “Connect Asynchronous Folder Export” design (DOCX / Google Doc)

Sync these bullets into the official design document so builders do not diverge from the validated flow.

## Flow correction

- **ECS does not publish to SNS.** After export work completes, **TcExportProcessor** only **updates the job row in DynamoDB** (e.g. `status`, `result`, `downloadUrl`, `fsUploadId`, `updatedAt`).
- **SNS publish** is performed by **ExportUpdateHandler**, a **DynamoDB Streams** consumer on `MODIFY` events, when it detects the appropriate **status transition** (e.g. to `DONE`). Replace any wording that implies “ECS publishes to SNS” with this sequence.

## Naming

- Use a **single** revision queue name everywhere: **`ExportRevisionQueue`**. Retire alternate labels such as `FolderExportRevisionQueue` in diagrams and runbooks.

## API and JSON examples

- Fix JSON samples for valid syntax (quoted keys, commas, matching braces). Example `result` shape:

```json
{
  "downloadUrl": "https://example.invalid/presigned"
}
```

- Align **POST /export** body with File Service: `{ "items": [ { "id": "…", "type": "FILE|FOLDER" } ] }` and align **GET job** response field names (`id` vs `jobId`) with the implementation OpenAPI.

## FAILED jobs and SNS

- Decide explicitly whether **`FAILED`** terminal state emits an SNS message (e.g. `connect.export.failed`). If **`TcFileServiceTopic` is shared**, use **SNS message attributes** and **subscription filter policies** so **ExportRevisionQueue** receives only events intended for **`/logRevisionAsync`**, and email or other subscribers stay isolated.

## Reference implementation in this repo

- Message contract: [schemas/export-completion-event.schema.json](schemas/export-completion-event.schema.json) and [fixtures/](fixtures/).
- IaC and alarms: [sam/template.yaml](sam/template.yaml).
- Lambda handlers: [lambda/export_update_handler/](lambda/export_update_handler/) and [lambda/export_revision_logger/](lambda/export_revision_logger/).
