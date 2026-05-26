# Next-gen FS vs Connect permission — API analysis

**Related work:** [TCJARVIS-688](https://jira.trimble.com/browse/TCJARVIS-688) — verify that when `isNextGenFSOperationsEnabled(project)` is true, legacy Connect file-service `hasPermission` is correctly skipped in favor of TDSFS permission handling; document gaps and traceability from REST → adapter → bus.

**Scope flags (product):**

- **`isNextGenFSOperationsEnabled(project)`** — `nextGenFs_operations_enabled` **and** `project.fs_user_context`.
- **`isNextGenFSReadOperationsEnabled(project)`** — operations flag **and** `nextGenFsReadOperationsEnabled` config.

**Rule of thumb for this document:** For **user-context** API calls, FS may be the single authority for file/folder ACL; **Connect** `permissionBus.hasPermission` / `hasPermissionWithCheckout` should be conditional where redundant. **App/service context** flows may still require Connect enforcement (FS may not 403 the service principal).

---

## 1. Get file details

**API:** `GET /2.0/files/{fileId}` (`FilesResource.getFileDetails`)

| Layer | Behavior |
|-------|----------|
| **Adapter** | `validateFileApiInternal` — if next-gen flag path applies, **`hasNextGenFsPermissionForFile`** (FS ACL via `fsPermissionBus` + share/release/session rules). **Note:** `action` is often **`null`** on this route, so the adapter chooses **`isNextGenFSOperationsEnabled`** (not the read-specific flag) for the “use FS permission” branch — verify product intent. |
| **Bus (details)** | `fetchSODetails` → `getObjectDetails` → when read flag + `fileServiceId`, **`getObjectDetailsFS`**. |
| **Connect after FS path** | **`getObjectDetailsFS`** still calls **`permissionBus.hasPermission(..., RELEASE_READ)`** before loading FS metadata — **duplicate gate** vs adapter FS check. |
| **DTO permission** | `getUserPermission` / share weight logic still **Connect**-sourced for `_actions` / permission display. |

**Jira alignment:** Identify whether `hasPermission` in `getObjectDetailsFS` should be skipped or guarded when next-gen read + user context already passed adapter FS validation.

**Suggested remediation:** Single authority for READ (adapter **or** bus); align `action`/read flag usage; optionally derive DTO permission from FS for user-context projects.

---

## 2. Get folder details

**API:** `GET /2.0/folders/{folderId}` (`FoldersResource.getFolderDetails`)

| Layer | Behavior |
|-------|----------|
| **Adapter** | **`validateFolderApi`** — **`permissionBus.hasPermission`** on folder (**Connect only**); no `hasNextGenFsPermissionForFile` equivalent for folders at this layer. |
| **Bus (details)** | `fetchSODetails` → `getObjectDetails` → **`getObjectDetailsFS`** for folder with FS id when read flag applies. |
| **Connect after FS path** | **`getObjectDetailsFS`** again **`permissionBus.hasPermission(..., RELEASE_READ)`** on the folder. |

**Jira alignment:** Folder GET is **double Connect**-biased; FS folder fetch runs only after Connect RELEASE_READ.

**Suggested remediation:** Add FS-backed folder permission check (or skip Connect when FS folder GET with user token is authoritative); remove redundant `getObjectDetailsFS` Connect check when aligned.

---

## 3. Delete file / folder

**APIs:**

- `DELETE /2.0/files/{fileId}` (`FilesResource.deleteStorageObjects`)
- `DELETE /2.0/folders/{folderId}` (`FoldersResource.deleteStorageObjects`)

| Layer | Behavior |
|-------|----------|
| **Adapter** | **File:** `validateFileApi` with `Operation.DELETE` — may use **`hasNextGenFsPermissionForFile(DELETE)`** when next-gen on. **Folder:** **`validateFolderApi`** with `FOLDER_DELETE` — **Connect** only. |
| **Bus** | **`deleteObjectsOnly`** — **`hasPermissionWithCheckout(..., Operation.DELETE)`** (**Connect**) before FS delete; then **`tdsfsStore.deleteFileById` / `deleteFolderInFS`** when next-gen on. |

**Jira alignment:** Same pattern as ticket’s **`deleteObjectsOnly`** — Connect DELETE and next-gen FS both run.

**Suggested remediation:** When user-context FS delete enforces ACL, guard or skip Connect **`hasPermissionWithCheckout(DELETE)`** for eligible objects; keep checkout checks if still product-required.

---

## 4. Move / rename (file and folder)

**APIs:**

- `PATCH /2.0/files/{fileId}` (`FilesResource.patchFile`)
- `PATCH /2.0/folders/{folderId}` (`FoldersResource.patchFolder`)

| Layer | Behavior |
|-------|----------|
| **Adapter** | **`canInvokeNextGenFSFileOperation`** → **`skipPermissionChecks`** may bypass **Connect UPDATE** on source and destination for move. **Checkout hierarchy** still **Connect**. |
| **Bus** | **`moveObjects`:** FS **`moveFileInFS`** when next-gen; **source** may still hit **Connect** `hasPermission` (UPDATE) — known gap vs destination. **`renameObject`:** FS **`renameFileInFS`** when next-gen; **Connect** `hasPermissionWithCheckout` still present in rename flow. |

**Jira alignment:** Matches ticket emphasis on **`renameObject`** / **`moveObjects`** — `hasPermission` near FS branches.

**Suggested remediation:** Extend skip/guard to **move source** and **rename** bus checks when FS is authoritative; document folder PATCH vs file PATCH parity.

---

## 5. Create folder

**API:** `POST /2.0/folders` (`FoldersResource.createFolder` → `StorageObjectBusAdapter.addFolder`)

**Other entry points (same bus permission):**

- **BCF** — hidden/issue folders via `StorageObjectBus.addFolder` (e.g. `BcfBus`).
- **Sync** — `SyncBus` → `addFolder` with activity / filespace.
- **Legacy webapp** — `webapp/resources/FoldersResource` create folder (if still deployed).

| Layer | Behavior |
|-------|----------|
| **Bus** | **`StorageObjectBus.addFolder(StorageObjectDto, User, Activity, boolean isTcc, String filespaceId, boolean isFsUserContext)`** (the overload used after the activity is built) enforces **Connect** access to create the child under the parent via **`permissionBus.hasPermissionWithCheckout(user.getUserId(), parent.getStorageObjectId(), ObjectType.FOLDER, Operation.CREATE, ObjectType.FOLDER, Optional.ofNullable(parent.getProjectId()))`**. If that returns no permission, the call fails before FS. When **`folderCheckOut`** is enabled, it also rejects create if checkout state on the parent implies another user’s lock (**`PermissionWithCheckout`** from the same call). After that gate, **`addObject`** may call **`tdsfsStore.createFolder`** when next-gen FS is on. |
| **Response** | Adapter calls **`getObjectDetails`** — possible second **Connect `RELEASE_READ`** via **`getObjectDetailsFS`**. |

**Jira alignment:** FS creates folder in filespace; **permission to create under the parent** is decided by **`hasPermissionWithCheckout`** (CREATE on parent), not by FS create alone.

**Suggested remediation:** FS-backed “create in parent” permission when user-context; reduce duplicate READ on response if FS details path trusted.

---

## 6. Download

**APIs:**

- `GET /2.0/files/fs/{fileId}/downloadurl` (`FilesResource.downloadUrl`)
- `GET /2.0/data/{objectdata}/{details}` with `ActivityAction.FILE_DOWNLOAD` (`DataResource.processDataUrl` → `StorageObjectBusAdapter.streamFile`)
- `GET /2.0/tcc/files/{fileId}/content` (`TccResource.downloadFile`)

**Out of scope for this subsection:** Project-only access checks, TAM, **`/files/thumb`**, **`/{fileId}/thumbnail`**, **`/support/files`**, **`POST /releases/downloadFiles`**, and other **`/data`** actions (e.g. user/company thumbnail tokens).

| Layer | Behavior |
|-------|----------|
| **Scope** | Document **only** flows where **`isNextGenFSOperationsEnabled`** and/or **`isNextGenFSReadOperationsEnabled`** appears on the path **and** Connect **`permissionBus.hasPermission`** / **`hasSharePermission`** on the **file** runs **before** **`tdsfsStore`** / FS serves bytes. |
| **Adapter / bus — download URL** | **`validateFileApi(..., FILE_GET)`** uses **`isNextGenFSReadOperationsEnabled`** to choose FS vs Connect in **`validateFileApiInternal`**. **`StorageObjectBus.getDownloadUrl`**: when **`isNextGenFSOperationsEnabled`**, **`hasPermission(RELEASE_READ)`** / **`hasSharePermission`** then FS (support file, version, path, or presigned fallback). |
| **Adapter / bus — data `FILE_DOWNLOAD`** | **`validateFileApiInternal`** with **`Action` = `null`** → FS permission branch gated by **`isNextGenFSOperationsEnabled`**. **`downloadContentFile`** / **`downloadFile`**: Connect **`hasPermission`** on the **`StorageObject`** before bus; **`downloadFiles`** repeats **`hasPermission` / `hasSharePermission`** per file when **`!includeDeleted`**; **`downloadFiles`** may use **`isNextGenFSOperationsEnabled`** for version/support-file FS reads. |
| **Adapter / bus — TCC content** | No **`validateFileApi`**; **`isNextGenFSReadOperationsEnabled`** not on entry. **`downloadContentFile`** / **`downloadFile`** enforce Connect READ on the file; **`isNextGenFSOperationsEnabled`** appears inside **`downloadFiles`** on some branches. |
| **Byte stream vs checkout** | Stream/URL gates (**`validateFileApiInternal`**, **`getDownloadUrl`**, **`downloadContentFile`**, **`downloadFile`**, **`downloadFiles`**) use **`hasPermission`** / **`hasSharePermission`** or FS ACL — **not** **`hasPermissionWithCheckout`**. |
| **Metadata / filename (`processDownloadFiles`)** | **`getFileDetails`** (plain **`hasPermission`**) → **`getObjectDetails`**. **Legacy** **`getObjectDetails`** (when **`getObjectDetailsFS`** is not used): **`hasPermissionWithCheckout(..., RELEASE_READ)`** and checkout-on-hierarchy on DTO; **`getObjectDetailsFS`** uses **`hasPermission`** only. |

**Jira alignment:** **`getDownloadUrl`**, **`downloadContentFile`**, **`downloadFile`**, **`downloadFiles`**, **`getObjectDetails`** (via **`getFileDetails`** in **`processDownloadFiles`**) — FS + Connect READ overlap; checkout-aware READ only on legacy **`getObjectDetails`**.

**Suggested remediation:** Single authority for READ where redundant; follow-up #5 (**`skipPermissionCheck`** vs **`downloadFiles`**).

---

## 7. Copy file

**API:** `POST /2.0/files/` (`FilesResource.copyFromExistingFile` → `StorageObjectBusAdapter.copyStorageObject`)

| Layer | Behavior |
|-------|----------|
| **Adapter** | **`hasPermissionWithCheckout`** on **source** (and parent/destination logic) — **Connect**. |
| **Bus** | **`copyObject`** — **`copyFileVersionInFS`** when next-gen + filespace + version lookup; else legacy DO path. |

**Jira alignment:** **`copyObject`** called out in ticket for verification.

**Suggested remediation:** FS copy permission vs Connect source READ/CREATE; conditional Connect when user-context FS validates.

---

## 8. Check-in / check-out file

**APIs:**

- `POST /2.0/files/{fileId}/checkout`
- `POST /2.0/files/{fileId}/checkin`

| Layer | Behavior |
|-------|----------|
| **Adapter** | **`validateFileApi`** with **`Operation.READ`** + **`Action.FILE_LOCK`** — may use FS permission path for file READ depending on flags/action. |
| **Bus** | **`checkOutInFile`:** **`hasPermissionWithCheckout(..., Operation.UPDATE)`** — **Connect first**. If **`sObjectList.size() == 1`** and next-gen + `fileServiceId`, **`tdsfsStore.checkoutFile` / `checkInFile`**; **folder checkout** expanding to many files **does not** call FS checkout per file under that condition. |

**Jira alignment:** Ticket **`checkOutInFile`** — Connect vs FS.

**Suggested remediation:** When FS owns lock, relax Connect UPDATE for user-context single-file flow; extend FS lock calls for multi-file/folder scenarios if required by product.

---

## Traceability summary (Jira matrix)

| API | Connect `hasPermission` / `hasPermissionWithCheckout` | FS permission / operation | Redundancy / gap |
|-----|------------------------------------------------------|----------------------------|------------------|
| GET file details | Adapter FS or Connect; **bus `getObjectDetailsFS`** RELEASE_READ | FS metadata fetch | **High** — double READ |
| GET folder details | **`validateFolderApi`** + **`getObjectDetailsFS`** | FS folder details | **High** — no FS at adapter |
| DELETE file/folder | Adapter + **`deleteObjectsOnly`** DELETE | FS delete | **High** |
| PATCH move/rename | Partial skip in adapter; bus rename/move | FS move/rename | **Medium** — source move, rename |
| POST create folder | **`StorageObjectBus.addFolder`:** **`hasPermissionWithCheckout`** on parent (**CREATE**); response **`getObjectDetails`** may add **RELEASE_READ** | FS **`createFolder`** | **Medium** |
| Download (§6) | **`downloadurl`**, **`/data` FILE_DOWNLOAD**, **`/tcc/.../content`** — next-gen flag **+** Connect **`hasPermission`** before FS bytes; **`hasPermissionWithCheckout(RELEASE_READ)`** only on legacy **`getObjectDetails`** via **`processDownloadFiles` → `getFileDetails`** | FS getFile / support / versions | **High** — double READ; stream vs metadata gates differ |
| POST copy | Adapter Connect | FS copy version | **High** |
| POST checkout/checkin | Adapter + bus UPDATE; FS lock only single-file list | FS checkout/in | **Medium** |

---
