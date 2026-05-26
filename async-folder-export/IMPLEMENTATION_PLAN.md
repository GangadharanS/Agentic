# Async Folder Export Implementation Plan

## Summary

Transform the synchronous folder export in Trimble Connect to an asynchronous, event-driven architecture using AWS services. The new system will handle large folder exports (up to 10GB) without blocking, provide job status tracking, and generate pre-signed download URLs valid for 48 hours.

## Architecture Overview

```mermaid
flowchart TB
    subgraph client [Client Layer]
        Actor[User/Client]
    end

    subgraph api [API Layer - File Service]
        ExportAPI[POST /export]
        JobsAPI[GET /jobs/jobId]
    end

    subgraph processing [Processing Layer]
        DynamoDB[(DynamoDB - file_service_jobs)]
        DDBStream[DynamoDB Streams]
        InsertHandler[Lambda: ExportInsertHandler]
        UpdateHandler[Lambda: ExportUpdateHandler]
        SQS_FIFO[SQS FIFO: ExportJobQueue]
        ECS[ECS: TcExportProcessor]
        DLQ[DLQ: ExportJobDLQ]
    end

    subgraph notification [Notification Layer]
        SNS[SNS: TcFileServiceTopic]
        RevisionQueue[SQS: ExportRevisionQueue]
        RevisionLambda[Lambda: ExportRevisionLoggerLambda]
        MonolithAPI[Monolith: /logRevisionAsync]
    end

    subgraph storage [Storage Layer]
        GTeamDB[(GTeam DB)]
        EFS[EFS Mount]
        CloudFS[Cloud FileService]
    end

    Actor --> ExportAPI
    Actor --> JobsAPI
    ExportAPI --> DynamoDB
    JobsAPI --> DynamoDB
    DynamoDB --> DDBStream
    DDBStream -->|INSERT| InsertHandler
    DDBStream -->|UPDATE| UpdateHandler
    InsertHandler --> SQS_FIFO
    InsertHandler -->|failure| DLQ
    SQS_FIFO --> ECS
    ECS --> GTeamDB
    ECS --> EFS
    ECS --> CloudFS
    ECS --> DynamoDB
    ECS -->|failure| DLQ
    UpdateHandler --> SNS
    SNS --> RevisionQueue
    RevisionQueue --> RevisionLambda
    RevisionLambda --> MonolithAPI
```

## ECS and SNS boundaries (design validation)

- **TcExportProcessor (ECS)** updates the **jobs DynamoDB item** only (`status`, `result`, `downloadUrl`, `fsUploadId`, `updatedAt`, and so on). It must **not** publish to SNS.
- **ExportUpdateHandler** is the only component that **publishes** export-completion (and optionally export-failure) events to **`TcFileServiceTopic`**, triggered by **DynamoDB Streams** `MODIFY` when `status` transitions to a terminal value (see [schemas/](schemas/) and [sam/template.yaml](sam/template.yaml)).
- **Canonical revision queue name** in this repo and IaC: **`ExportRevisionQueue`**. Do not use alternate names such as `FolderExportRevisionQueue` in new infrastructure.

## API Contract

### POST /export

Creates an asynchronous export job.

**Request Body (File Service shape):**
```json
{
  "items": [
    { "id": "folder-123", "type": "FOLDER" },
    { "id": "file-456", "type": "FILE" }
  ]
}
```

**Validation Rules:**
- Maximum 20 object IDs per request (based on metrics: 99.9% of requests use 6 or fewer IDs)
- Maximum archived file size: 10GB
- User must have READ permission on all objects
- Empty payload returns 400 Bad Request

**Responses:**
- `202 Accepted` with `Location` header containing jobId
- `400 Bad Request` for empty payload or exceeding limits
- `403 Forbidden` if user lacks permissions

### GET /jobs/{jobId}

Retrieves job status and download URL.

**Query Parameters:**
- `fields` (optional): `input`, `result` - additional fields to include
- `wait` (optional): `true`/`false` - enable long polling

**Response (DONE):**
```json
{
  "jobId": "job-abc123",
  "status": "DONE",
  "createdBy": "users:tiduuid:xxxxx",
  "createdAt": "2025-05-07T12:00:00Z",
  "updatedAt": "2025-05-07T12:15:00Z",
  "result": {
    "downloadUrl": "https://..."
  }
}
```

**Response (FAILED):**
```json
{
  "jobId": "job-abc123",
  "status": "FAILED",
  "result": {
    "error": {
      "code": "PERMISSION_DENIED",
      "message": "User does not have permission"
    }
  }
}
```

## DynamoDB Schema

**Table:** `file_service_jobs`

| Attribute | Type | Description |
|-----------|------|-------------|
| jobId (PK) | String | UUID |
| jobType | String | EXPORT, FOLDER_DELETION |
| status | String | QUEUED, PROCESSING, DONE, FAILED |
| projectId | String | Associated project |
| createdBy | Map | tc_user_id and tiduuid |
| createdAt | Timestamp | Job creation time |
| updatedAt | Timestamp | Last update time |
| input | Map | Request payload (e.g. `{ "items": [ { "id", "type" } ] }`) |
| result | Map | downloadUrl or error |
| expireAt | Timestamp | TTL (30 days) |
| fsUploadId | String | FileService upload ID |
| downloadUrl | String | Pre-signed URL (48hr validity) |

## Implementation Components

### 1. File Service API (Export Processor)

- Validate request and permissions (project access, admin or READ)
- Feign call to Monolith `/operations` for syncSession/batchId or create new activity
- Create job entry in DynamoDB with status `QUEUED`
- Return 202 with jobId in Location header

### 2. Lambda: ExportInsertHandler

- Triggered by DynamoDB Streams (INSERT events)
- Parse stream event, extract job details
- Validate job entry
- Enqueue to SQS FIFO with `projectId` as MessageGroupId
- Send failures to DLQ

### 3. SQS FIFO: ExportJobQueue

- FIFO queue for ordered processing per project
- Triggers ECS task

### 4. ECS: TcExportProcessor

- Batch size: 1 job per task
- Default: 2 tasks, scales up to 40 based on `ApproximateNumberOfMessagesVisible > 5`
- Processing steps:
  1. Retrieve files, folders, subfolders with hierarchy
  2. Query GTeam DB for metadata per storage_object_id
  3. Check preconditions (associations, checkout, permissions)
  4. If any object lacks READ permission, mark job as FAILED
  5. Archive all files maintaining folder hierarchy
  6. Upload to Cloud FileService (single-part up to 5GB, multi-part for larger)
  7. Update DynamoDB status to DONE/FAILED (and result fields); **do not** call SNS from ECS
  8. Generate pre-signed URL (48hr expiry) and persist on the job record as required

### 5. Lambda: ExportUpdateHandler

- Triggered by DynamoDB Streams (`MODIFY`); in code, only act when **`status` transitions** to `DONE` (and optionally emit a distinct event for `FAILED`—see SNS filter policies in [sam/template.yaml](sam/template.yaml))
- Publish a versioned JSON **message body** (see [schemas/export-completion-event.schema.json](schemas/export-completion-event.schema.json)) to **`TcFileServiceTopic`**
- **Idempotency:** use a small DynamoDB deduplication table (or equivalent) so at-least-once stream delivery does not double-publish (see [lambda/export_update_handler/handler.py](lambda/export_update_handler/handler.py))

### 6. SQS: ExportRevisionQueue

- Subscribed to TcFileServiceTopic
- Triggers ExportRevisionLoggerLambda

### 7. Lambda: ExportRevisionLoggerLambda

- Parse SNS event from SQS
- Call Monolith `POST /logRevisionAsync` for revision logs

### 8. DLQ: ExportJobDLQ

- Captures failed events from InsertHandler and ECS processor

## Metrics Analysis (from download_api_metrics.csv)

Based on 6 months of `/folders/download` API access logs (1,175 requests):

| ID Count | Requests | Percentage |
|----------|----------|------------|
| 1 | 713 | 60.7% |
| 3 | 223 | 19.0% |
| 6 | 227 | 19.3% |
| 2 | 9 | 0.8% |
| 4 | 1 | 0.1% |
| 9 | 1 | 0.1% |
| 22 | 1 | 0.1% |

**Conclusion:** Setting limit to 20 IDs covers 99.9% of use cases. Max observed was 22 (single outlier).

## Scalability Configuration

- Default concurrent ECS tasks: 2
- Maximum concurrent ECS tasks: 10 (adjustable based on performance)
- Scale-up trigger: `ApproximateNumberOfMessagesVisible > 5` in CloudWatch
- Production load: ~2 requests/minute for download API

## Upload Mechanism

- **Single-part upload:** Files up to 5GB
- **Multi-part upload:** Files between 5GB-10GB
  - Part size: 5MB-5GB (except last part)
  - Maximum parts: 10,000

## Future Considerations

- Folder permission inheritance (planned for September 2025) will change permission checking logic
- Remove logic that includes parent folders up to root

## Infrastructure Requirements

- DynamoDB table with TTL enabled
- DynamoDB Streams enabled
- Lambda functions: ExportInsertHandler, ExportUpdateHandler, ExportRevisionLoggerLambda (plus any email/notification consumers on the same SNS topic)
- SQS: **ExportJobQueue** (FIFO) + **ExportRevisionQueue** (standard) + matching **DLQs**
- ECS task definition with auto-scaling
- SNS: existing **`TcFileServiceTopic`**; subscription from topic → **ExportRevisionQueue** with **filter policy** on message attributes (`eventType`, `jobType`) where multiple workloads share the topic
- EFS mount for file processing
- IAM roles for Lambda, ECS with appropriate permissions
- CloudWatch alarms for revision queue depth/age, Lambda errors, DLQ depth (see [sam/template.yaml](sam/template.yaml))
