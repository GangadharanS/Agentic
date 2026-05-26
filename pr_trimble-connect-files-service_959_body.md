# Pull Request Template (filled)

## Description

This change introduces **asynchronous multi-object export** for File Service so large folder/file selections are processed off the request path, with job status and a **time-limited download URL** returned to the client.

**Design reference:** *Design: Connect Asynchronous Export Functionality* (DOCX: *Design: Connect Asynchronous Folder Export Functionality*), updated Jul 21, 2025.

**API (per design):**

- `POST /v2/fs/exports` — body `{ "items": [ { "id", "type": "FILE" | "FOLDER" }, … ] }`; `202 Accepted` with `Location` (job id); authZ for project access, **READ** when not admin; empty body `400`; insufficient permission `403`.
- `GET /projects/{projectId}/fs/exports/{exportId}` — optional `fields=input,result`; only **creator** (`createdBy`) may read full job; download URL default validity **48h**, masked to Trimble domain in response.

**Processing pipeline (per design):**

- Job record in **DynamoDB** → **Streams** → **Lambda (ExportInsertHandler)** → **SQS FIFO** (`MessageGroupId` = `projectId`) → **ECS Fargate (TcExportProcessor)**.
- Processor walks hierarchy (same structure as Connect sync archive), enforces permissions/associations/checkout rules, builds archive, uploads via Cloud FS (`/upload` — single-part up to 5 GB, multipart 5 MB–5 GB per part, max 10 000 parts).
- On success: status **DONE** → Streams → **SNS (TcFileServiceTopic)** → **SQS (ExportRevisionQueue)** → **Lambda (ExportRevisionLoggerLambda)** → monolith **`POST /logRevisionAsync`**.
- **DLQs** on failure paths; optional **Feign** to monolith **`/operations-`** for sync session / batch / activity before job creation.

**Limits (per design conclusion):**

- Archived export size cap **~10 GB** (initial, aligned with FS Java SDK validation).
- Max **20** items in `POST` body (usage metrics max 7; 20 as headroom).

**Future behaviour (documented in design, not necessarily in this PR):**

- Permission-denied handling may change after folder permission inheritance.
- May stop including parent folders to root; empty folders still included to match Connect today.

## Jira ticket number

**Epic (design doc):** TCPP-3114  
**Program tracking / epic (Jira):** TCPP-5593 — link the **story/task key** that covers this PR (e.g. `TCJARVIS-xxxx`) when filed.

## Types of changes

- [ ] 🐛 Bugfix (non-breaking change which fixes an issue)
- [x] :sparkles: Feature (non-breaking change which adds functionality)
- [ ] :boom: Breaking change (fix or feature that would cause existing functionality to change)
- [x] 📈 Performance improvement
- [ ] :wrench: Build related changes
- [ ] :green_heart: CI related changes
- [x] 📝 Documentation content changes
- [ ] :art: Code style update (formatting, local variables)
- [ ] :hammer: Refactoring (no functional changes, no API changes)
- [x] :white_check_mark: Tests (unit or functional tests related changes)
- [ ] :bulb: Other... Please describe:

## Motivation and Context

Synchronous multi-object download does not scale for deep/large hierarchies and keeps clients waiting. File Service needs **batch export** parity with Connect’s `GET /download?…&id=[…]` while preserving **folder hierarchy** (external flat blob export is insufficient). Moving work to **async jobs** improves responsiveness and aligns with existing FS patterns (DynamoDB job + Streams + FIFO + processor + revision logging).

## How Has This Been Tested?

- Unit tests for new/changed FS services, controllers, and job/export helpers (Gradle).
- Integration or contract checks for `POST` / `GET` export endpoints (status transitions, authZ, creator-only GET).
- Verified FIFO **per-project** ordering under concurrent enqueue.
- Smoke path: enqueue job → processor completes → job **DONE** → pre-signed URL (or masked URL) returned; failure path → **FAILED** + structured `result.error`.

### Impact Areas

- File Service REST API (`/v2/fs/exports`, export status routes).
- DynamoDB job persistence and **TTL** (`expireAt`, ~30 days in design).
- New/updated Lambda(s), SQS FIFO queue(s), ECS task definition/scaling for export processor.
- SNS / revision logging integration with **`/logRevisionAsync`**.
- Optional monolith **`/operations-`** linkage for activity/session correlation.
- CDK / IaC for wired resources.

### Quantitative Performance Benefits (if appropriate)

Export requests return **quickly** with `202` and a job handle instead of blocking on full archive creation. Processor scales with queue depth (e.g. default **2** concurrent Fargate tasks, up to **~40**, scaling signal e.g. `ApproximateNumberOfMessagesVisible`; tunable vs. `/download` traffic). Fargate cold start (**~30–60 s**) is acceptable for fully async workflows.

## Possible Drawbacks

- **Operational surface:** more moving parts (Dynamo Streams, FIFO, ECS, DLQs).
- **Caps:** 10 GB archive and 20 `items` may require revisiting after telemetry.
- **Permission model:** “fail whole job if any child lacks READ” until inheritance work lands (per design).
- **Fargate cold start** adds latency before processing starts (invisible if only async UX is promised).

## Screenshots (if appropriate)

_N/A unless UI or Swagger/OpenAPI screenshots are attached in the PR._

## Checklist

- [x] My change requires a change to the documentation(README/CONTRIBUTING/API Specification) and it has updated accordingly.
- [x] I have added tests that prove my fix is effective or that my feature works.
- [ ] Any dependent changes have been merged and published in downstream modules. _(Confirm Connect / consumers using new API — link PRs if any.)_
- [x] I have commented my code, particularly in hard-to-understand areas.
