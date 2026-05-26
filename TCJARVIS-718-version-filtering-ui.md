# TCJARVIS-718: Cursor-based Version Listing & versionFiltering Implementation Guide

## Repository
**Trimble-Connect/trimble-web-apps** (`clients/apps/tcweb`)

## Ticket
**TCJARVIS-718:** [Versioning] Migrate to cursor-based version listing API and add versionFiltering support in TCWEB

---

## 1. Scope Overview

Two changes are required:

| # | Change | Description |
|---|--------|-------------|
| 1 | **Range-based to cursor-based migration** | TCWEB currently uses range-based listing for file versions. Migrate to cursor-based endpoint. |
| 2 | **versionFiltering query param** | Pass `versionFiltering=true` or `false` based on context at each call site. |

---

## 2. Code Changes Required

### 2.1 API Service Layer — Cursor-based + versionFiltering

**File:** `clients/apps/tcweb/src/axios/tcps/tcps.service.ts`

**Current code (line ~2369) — Range-based:**
```typescript
export const getFileVersions = async (origin: string, id: string): Promise<AxiosResponse<IFileDetails[]>> => {
  const url = `${getOriginUrl(origin, false)}/files/${id}/versions?tokenThumburl=false`;
  return await TCPSServiceInstance.getRequest(url);
};
```

**Proposed change — Cursor-based with versionFiltering:**
```typescript
export interface IVersionListResponse {
  items: IFileDetails[];
  nextCursor: string | null;
  hasMore: boolean;
}

export const getFileVersions = async (
  origin: string,
  id: string,
  versionFiltering: boolean = false,
  cursor?: string,
  limit: number = 50
): Promise<AxiosResponse<IVersionListResponse>> => {
  let url = `${getOriginUrl(origin, false)}/files/${id}/versions?tokenThumburl=false`;
  url += `&versionFiltering=${versionFiltering}`;
  url += `&limit=${limit}`;
  if (cursor) {
    url += `&cursor=${encodeURIComponent(cursor)}`;
  }
  return await TCPSServiceInstance.getRequest(url);
};
```

**What this does:**
- Replaces range-based pagination with cursor-based (`cursor` + `limit` params)
- Adds `versionFiltering` parameter (default `false` for backward compatibility)
- Returns `IVersionListResponse` with `items`, `nextCursor`, and `hasMore`
- No breaking change to existing callers when `cursor` is not provided (first page load)

---

### 2.2 Pagination Helper (New)

Create a reusable hook or helper for cursor-based version pagination:

```typescript
// Example: useCursorPagination hook pattern
const useVersionPagination = (origin: string, fileId: string, versionFiltering: boolean) => {
  const [versions, setVersions] = useState<IFileDetails[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);

  const fetchPage = async (nextCursor?: string) => {
    setLoading(true);
    const response = await getFileVersions(origin, fileId, versionFiltering, nextCursor);
    const data = response.data;
    
    setVersions(prev => nextCursor ? [...prev, ...data.items] : data.items);
    setCursor(data.nextCursor);
    setHasMore(data.hasMore);
    setLoading(false);
  };

  const loadMore = () => {
    if (hasMore && cursor && !loading) {
      fetchPage(cursor);
    }
  };

  const reset = () => {
    setVersions([]);
    setCursor(null);
    setHasMore(true);
    fetchPage();
  };

  return { versions, loading, hasMore, loadMore, reset };
};
```

---

### 2.3 Call Site Updates

**Step 1:** Search for all imports/usages of `getFileVersions` across the codebase:
```bash
rg "getFileVersions" clients/apps/tcweb/src --glob '*.{ts,tsx}'
```

**Step 2:** For each call site:
1. Replace range-based logic with cursor-based pagination
2. Determine the correct `versionFiltering` value based on context

| Context | `versionFiltering` | Pagination |
|---------|--------------------|------------|
| Version history panel (showing all versions) | `false` | Cursor-based with "Load more" |
| Places showing only major/significant versions | `true` | Cursor-based with "Load more" |
| File details / properties panel | Depends on context | May be single page |
| Download specific version | `false` | Not paginated |

**Step 3:** Update each call site:
```typescript
// First page load — no cursor
const response = await getFileVersions(origin, fileId, false);

// Load next page — pass cursor from previous response
const nextPage = await getFileVersions(origin, fileId, false, response.data.nextCursor);

// Major versions only
const majorVersions = await getFileVersions(origin, fileId, true);
```

---

### 2.4 Remove Range-based Code

At each call site, remove:
- Range header logic (`Range: items=0-49`)
- Offset/page-number based pagination state
- Range-based response parsing

Replace with:
- `cursor` state variable
- `hasMore` boolean
- `nextCursor` from API response

---

## 3. Files to Modify

| # | File Path | Change |
|---|-----------|--------|
| 1 | `clients/apps/tcweb/src/axios/tcps/tcps.service.ts` | Rewrite `getFileVersions()` with cursor + versionFiltering params |
| 2 | New: Response type interface | Add `IVersionListResponse` type |
| 3 | All call sites importing `getFileVersions` | Migrate to cursor-based pagination, pass `versionFiltering` |
| 4 | Components with "load more" / infinite scroll | Use `nextCursor` instead of range offset |
| 5 | Unit tests for `getFileVersions` | Test cursor pagination + both versionFiltering values |
| 6 | Unit tests for call site components | Verify cursor handling and correct filter param |

---

## 4. Backend API Reference

- **Endpoint:** `GET /files/{fileId}/versions`
- **Query params:**
  - `versionFiltering` — `true` or `false` (default: `false`)
  - `cursor` — Cursor string from previous response (omit for first page)
  - `limit` — Number of items per page (default: `50`)
  - `tokenThumburl` — `false` (existing param)
- **Response:** `{ items: [...], nextCursor: "xxx", hasMore: true }`
- **Backend ticket:** TCJARVIS-437 (Closed, deployed to prod)
- **Design doc:** [Link](https://docs.google.com/document/d/16txPzwu4nJ89cH3s4BH0Nwyip9oNpnbGND4NOx4EfNE/edit?tab=t.0)

---

## 5. Testing Checklist

### Cursor-based migration
- [ ] First page loads without cursor param
- [ ] "Load more" sends `cursor` from previous response
- [ ] Pagination stops when `hasMore` is `false`
- [ ] Empty file (no versions) handled gracefully
- [ ] No range headers sent in requests
- [ ] No regression in version listing UI

### versionFiltering
- [ ] `versionFiltering=false`: Shows all versions (existing behavior)
- [ ] `versionFiltering=true`: Shows only major versions
- [ ] Cursor pagination works correctly with both values
- [ ] Each call site passes the correct value based on its context
- [ ] Empty state handled when `versionFiltering=true` returns no results

---

## 6. Edge Cases

1. **File with no versions:** Both cursor-based and filter should return empty list gracefully
2. **File with no major versions:** `versionFiltering=true` returns empty — handle at call site
3. **Single version file:** Both `true` and `false` should return the same single version
4. **Pagination consistency:** Ensure `versionFiltering` value is the same across all paginated requests for a single view
5. **Concurrent requests:** If user navigates away mid-pagination, cancel pending requests
6. **Cursor expiry:** Handle case where server returns error for expired/invalid cursor (reset and re-fetch)
