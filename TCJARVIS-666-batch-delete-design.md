# Design Document: Public Batch File Delete API

**Ticket:** TCJARVIS-666 (Exploration) / TCJARVIS-623 (Implementation)
**Author:** JarvisAgent
**Status:** Draft

---

## 1. Summary

### Objective
Create a new public API endpoint for synchronous batch file deletion in Trimble Connect Platform, replacing the existing private `DELETE /folders/children` endpoint.

### Endpoint
```
DELETE /2.0/files/batch?projectId={projectId}
```

### Request Body
```json
{
  "fileIds": ["fileId1", "fileId2", "fileId3"]
}
```

### Key Characteristics
- **Synchronous** deletion (not queued/async)
- **Multiple files** from any hierarchy (not restricted to a single folder)
- **No file limit** on the number of files per request
- **Per-file validation** — permission, existence, project membership
- **All-or-nothing (transactional)** — if any file fails validation, the entire operation is aborted and no files are deleted

### Why DELETE with Body?
The `DELETE` method with a request body is technically valid per HTTP/1.1 spec (RFC 7231 does not prohibit it). This approach is used because:
- Semantically correct — the operation is a deletion
- The list of file IDs can be large, making query parameters impractical
- Aligns with existing patterns in the codebase (e.g., private `/folders/children` endpoint)

---

## 2. Impact Analysis

### 2.1 Components Affected

| Component | Impact | Details |
|-----------|--------|---------|
| **FilesResource.java** | New endpoint | Add `DELETE /2.0/files/batch` handler after line 478 |
| **StorageObjectBusAdapter.java** | New method | Add `batchDeleteStorageObjects()` with validation + deletion |
| **BatchDeleteRequestDto.java** | New file | Request DTO with `fileIds` list |
| **BatchDeleteResponseDto.java** | New file | Response DTO with per-file results |
| **TDSFSStore.java** | Future | Batch delete wrapper for NextGen FS projects |
| **FileOperationsService.java** | Future | Batch delete in cloud-files-service-utils |
| **TCWEB** | Migration | Migrate from private to public endpoint |

### 2.2 Existing Functionality Impact

| Area | Impact Level | Description |
|------|-------------|-------------|
| Single file delete | None | Existing `DELETE /2.0/files/{fileId}` is unchanged |
| Private `/folders/children` | Deprecated | Will be replaced but remains during migration |
| Permissions model | None | Uses existing per-file permission checks |
| Activity logging | Low | Each deleted file generates an activity entry (existing behavior) |
| Sync sessions | Low | Optional `syncSessionId` param supported for sync clients |
| NextGen FS projects | Deferred | FS integration planned as a follow-up |

### 2.3 Performance Impact

| Scenario | Concern | Mitigation |
|----------|---------|------------|
| Large batch (100+ files) | DB load from per-file validation | Batch permission queries where possible |
| Very large batch (1000+ files) | Request timeout | Document recommended batch size; no hard limit enforced |
| Concurrent batch deletes | DB contention | Existing transaction isolation handles this |
| Storage cleanup | S3 object deletion | Handled asynchronously by existing cleanup jobs |

### 2.4 Backward Compatibility

- **No breaking changes** — new endpoint, existing APIs unaffected
- **Private endpoint** remains functional during migration period
- **Default behavior** unchanged for all existing clients

---

## 3. Error Handling

### 3.1 Transactional Behavior — Fail-Fast, All-or-Nothing

The batch delete operation is **transactional** and follows the same **fail-fast** pattern as the existing private `DELETE /folders/children` endpoint. The operation fails on the **first invalid file** and rolls back the entire transaction — no files are deleted.

This is consistent with the current codebase behavior in `StorageObjectBus.deleteObjectsOnly()`.

**Flow:**
1. Iterate through files sequentially
2. Validate each file (existence, type, project, permission, lock status)
3. If a file fails validation → throw `AppException` immediately, transaction rolls back, no files deleted
4. If all files are valid → delete all within the same transaction
5. If a deletion fails mid-execution → transaction rolls back, no files deleted

### 3.2 HTTP Status Codes

| Status | Condition | Response Body |
|--------|-----------|---------------|
| **204 No Content** | All files validated and deleted successfully | Empty |
| **400 Bad Request** | Invalid request (empty body, missing projectId, malformed fileIds) | Error message with `ErrorCode` |
| **400 Bad Request** | Object already deleted (`INVALID_OPERATION_DELETED`) | Error message |
| **400 Bad Request** | Invalid operation on moved object (`INVALID_OPERATION_MOVED`) | Error message |
| **401 Unauthorized** | User not authenticated | Standard auth error |
| **403 Forbidden** | User has no access to the project OR no delete permission on a file | `PERMISSION_DENIED` error message |
| **404 Not Found** | Project not found (`PROJECT_NOT_FOUND`) or file not found (`OBJECT_NOT_FOUND`) | Error message |
| **500 Internal Server Error** | Unexpected error during deletion — transaction rolled back | Error message |

### 3.3 Error Codes (consistent with existing codebase)

| ErrorCode | HTTP Status | Description | Current Usage |
|-----------|-------------|-------------|---------------|
| `MISSING_REQUIRED_PARAMS` | 400 | Empty fileIds or missing projectId | Same as existing APIs |
| `OBJECT_NOT_FOUND` | 404 | File ID does not exist | Same as `deleteObjectsOnly` line 7534 |
| `PERMISSION_DENIED` | 403 | User lacks delete permission on a file | Same as `deleteObjectsOnly` line 7518 |
| `INVALID_OPERATION_DELETED` | 400 | Object has already been deleted | Same as `deleteObjectsOnly` line 7538 |
| `INVALID_OPERATION_MOVED` | 400 | Invalid operation on moved object | Same as `deleteObjectsOnly` line 7540 |
| `PROJECT_NOT_FOUND` | 404 | Project does not exist | Same as `deleteObjectsOnly` line 7435 |
| `INTERNAL_ERROR` | 500 | File Service deletion failed | Same as `deleteObjectsOnly` line 7761 |

### 3.4 Error Response Structure

Errors follow the existing `AppException` format used throughout the codebase:

```json
{
  "code": "PERMISSION_DENIED",
  "message": "You do not have permission for this operation. You do not have permission to delete some of the file(s)/folder(s)."
}
```

```json
{
  "code": "OBJECT_NOT_FOUND",
  "message": "Object your trying to delete was not found"
}
```

### 3.5 Error Handling Strategy

1. **Fail-fast** — Iterate through files sequentially. On the first validation failure, throw `AppException` immediately. This is the same behavior as the existing `deleteObjectsOnly()` method.
2. **@Transactional** — The entire operation runs within a single database transaction. Any exception causes a full rollback — no partial deletions.
3. **Consistent error codes** — Uses the same `ErrorCode` enum values as the existing codebase (`PERMISSION_DENIED`, `OBJECT_NOT_FOUND`, etc.) so clients handle errors the same way.

### 3.6 Comparison with Existing `/folders/children`

| Aspect | Current `/folders/children` | New `/files/batch` |
|--------|----------------------------|---------------------|
| Failure behavior | Fail-fast, throw on first bad file | Same — fail-fast |
| Transaction | `@Transactional`, rollback on error | Same |
| Error format | `AppException` with `ErrorCode` | Same |
| HTTP status codes | 400/403/404/500 | Same |
| Partial deletion | Never — all or nothing | Same |

---

## 4. Low-Level Design (LLD)

### 4.1 Request DTO

```java
// BatchDeleteRequestDto.java
public class BatchDeleteRequestDto {
    @NotNull
    @Size(min = 1)
    private List<String> fileIds;
    
    // getters, setters
}
```

No response DTO needed — success returns 204 (empty body), failure throws `AppException` (handled by existing `GenericExceptionMapper`).

### 4.2 Endpoint Handler

```java
// FilesResource.java — after line 478
@DELETE
@Path("/batch")
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
public Response batchDeleteFiles(
        @Context SessionBus session,
        @QueryParam("projectId") String projectVid,
        @QueryParam("syncSessionId") String syncSessionId,
        BatchDeleteRequestDto request) {
    
    // 1. Validate request
    if (request == null || request.getFileIds() == null || request.getFileIds().isEmpty()) {
        throw new AppException("fileIds list is required", ErrorCode.MISSING_REQUIRED_PARAMS);
    }
    
    Identity<Project> projectId = resourceHelper.validateStringId("projectId", projectVid);
    
    // 2. Permission check — user must have project access
    PermissionBus.ProjectAccessCheckResult accessCheck = 
        permissionBus.checkProjectAccessAndAdminAccess(
            session.getUser().getUserId(), projectId.getId(), false);
    
    // 3. TAM enforcement
    if (accessCheck.accessPolicyCheckRequired()) {
        tamServiceBus.evaluateInProjectContext(
            Feature.PROJECT.getValue(), projectVid, Action.PROJECT_UPDATE);
    }
    
    // 4. Execute batch delete
    BatchDeleteResponseDto response = storageObjectBusAdapter
        .batchDeleteStorageObjects(
            session.getUser(), projectId, request.getFileIds(), syncSessionId);
    
    // 5. Return 204 — all files deleted successfully
    return Response.noContent().build();
}
```

### 4.3 Business Logic — Reuse Existing `deleteObjectsOnly()` (Fail-Fast)

The new endpoint **reuses the existing `StorageObjectBus.deleteObjectsOnly()`** method, which already handles:
- File existence checks (throws `OBJECT_NOT_FOUND`)
- Permission checks (throws `PERMISSION_DENIED`)
- Deleted object checks (throws `INVALID_OPERATION_DELETED`)
- Moved object checks (throws `INVALID_OPERATION_MOVED`)
- File Service deletion with rollback
- `@Transactional` annotation for all-or-nothing behavior

No new business logic class or custom exception needed.

### 4.4 Endpoint Handler

```java
// FilesResource.java — add after existing file endpoints
@DELETE
@Path("/batch")
@Consumes(MediaType.APPLICATION_JSON)
@Produces(MediaType.APPLICATION_JSON)
public Response batchDeleteFiles(
        @Context SessionBus session,
        @QueryParam("projectId") String projectVid,
        @QueryParam("syncSessionId") String syncSessionId,
        BatchDeleteRequestDto request) {
    
    // 1. Validate request
    if (request == null || request.getFileIds() == null || request.getFileIds().isEmpty()) {
        throw new AppException("fileIds list is required", ErrorCode.MISSING_REQUIRED_PARAMS);
    }
    
    Identity<Project> projectId = resourceHelper.validateStringId("projectId", projectVid);
    
    // 2. Permission check — user must have project access
    PermissionBus.ProjectAccessCheckResult accessCheck = 
        permissionBus.checkProjectAccessAndAdminAccess(
            session.getUser().getUserId(), projectId.getId(), false);
    
    // 3. TAM enforcement
    if (accessCheck.accessPolicyCheckRequired()) {
        tamServiceBus.evaluateInProjectContext(
            Feature.PROJECT.getValue(), projectVid, Action.PROJECT_UPDATE);
    }
    
    // 4. Convert visible IDs to internal IDs
    List<Long> fileOrigIds = new ArrayList<>();
    for (String fileId : request.getFileIds()) {
        fileOrigIds.add(Identity.getLongId(fileId));
    }
    
    // 5. Delete all files — reuse existing deleteObjectsOnly()
    //    Fails fast on first invalid file, @Transactional rolls back all
    storageObjectBus.deleteObjectsOnly(
        projectId.getId(), fileOrigIds, session.getUser(),
        false, true, syncSessionId, null, null);
    
    // 6. All files deleted successfully
    return Response.noContent().build();  // 204
}
```

### 4.5 How Errors Propagate

Since `deleteObjectsOnly()` throws `AppException` on any failure, the existing `GenericExceptionMapper` handles the error response automatically:

```
Client → FilesResource.batchDeleteFiles()
           → storageObjectBus.deleteObjectsOnly()
               → throws AppException("Object not found", OBJECT_NOT_FOUND)
           → GenericExceptionMapper catches AppException
        ← HTTP 404 { "code": "OBJECT_NOT_FOUND", "message": "Object your trying to delete was not found" }
```

No custom exception handling needed in the endpoint — the existing exception mapper handles everything.

### 4.6 Sequence Diagram

```
Client                  FilesResource                    StorageObjectBus
  |                          |                                |
  |--DELETE /files/batch---->|                                |
  |                          |--validate request (body/params)|
  |                          |                                |
  |                          |--deleteObjectsOnly()---------->|
  |                          |                                |
  |                          |  For each file (sequentially): |
  |                          |    Check existence              |
  |                          |    Check not deleted/moved      |
  |                          |    Check permissions             |
  |                          |    Delete file + FS delete      |
  |                          |                                |
  |                          |  File invalid?                 |
  |                          |    → AppException thrown        |
  |                          |    → @Transactional rollback   |
  |<---403/404/400/500-------|  (no files deleted)            |
  |                          |                                |
  |                          |  All files valid + deleted?    |
  |<---204 NO CONTENT--------|  (all files deleted)           |
```

### 4.7 Future: NextGen FileServices Integration

For projects using NextGen FS, the delete call will route through `TDSFSStore`:

```java
// TDSFSStore.java (future)
public void batchDeleteFiles(String spaceId, List<String> fileServiceIds, Project project) {
    String userToken = getUserToken(project);
    fileOperationsService.batchDeleteFiles(spaceId, fileServiceIds, userToken);
}
```

This is deferred and will be implemented when NextGen FS batch delete support is available.

---

## 5. Unit Test Plan

| Test Class | Test Case | Expected |
|------------|-----------|----------|
| `FilesResourceTest` | `testBatchDelete_AllSuccess_Returns204` | 204 No Content, all files deleted |
| `FilesResourceTest` | `testBatchDelete_EmptyRequest_Returns400` | 400 `MISSING_REQUIRED_PARAMS` |
| `FilesResourceTest` | `testBatchDelete_NoProjectId_Returns400` | 400 `INVALID_PARAM` |
| `FilesResourceTest` | `testBatchDelete_OneNotFound_Returns404_NoneDeleted` | 404 `OBJECT_NOT_FOUND`, zero files deleted |
| `FilesResourceTest` | `testBatchDelete_PermissionDenied_Returns403_NoneDeleted` | 403 `PERMISSION_DENIED`, zero files deleted |
| `FilesResourceTest` | `testBatchDelete_AlreadyDeleted_Returns400_NoneDeleted` | 400 `INVALID_OPERATION_DELETED`, zero files deleted |
| `FilesResourceTest` | `testBatchDelete_MovedObject_Returns400_NoneDeleted` | 400 `INVALID_OPERATION_MOVED`, zero files deleted |
| `FilesResourceTest` | `testBatchDelete_ProjectNotFound_Returns404` | 404 `PROJECT_NOT_FOUND` |
| `FilesResourceTest` | `testBatchDelete_FSDeletionFails_Returns500_RolledBack` | 500 `INTERNAL_ERROR`, transaction rolled back |
| `FilesResourceTest` | `testBatchDelete_ThirdFileFails_FirstTwoRolledBack` | Error on 3rd file, files 1 & 2 rolled back |

---

## 6. Migration Plan

| Step | Action | Dependency |
|------|--------|------------|
| 1 | Deploy new `DELETE /2.0/files/batch` endpoint | None |
| 2 | Update TCWEB to use new public endpoint | Step 1 deployed |
| 3 | Add deprecation notice to `DELETE /folders/children` | Step 2 complete |
| 4 | Monitor private endpoint usage | Step 3 |
| 5 | Remove private endpoint | All clients migrated |
