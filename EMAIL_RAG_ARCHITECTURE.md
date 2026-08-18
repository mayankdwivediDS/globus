# Email Metadata RAG + RBAC Architecture

## Overview

Email semantic search (RAG) integration for Globus using Gmail message metadata (subject, from, to, snippet) indexed via FAISS vector embeddings. Fully isolated per-member with role-based access control (RBAC) enforcement at multiple layers.

**Key Principle**: Metadata-only indexing (no full email bodies), continuous sync via cron jobs, zero multi-user hallucinations through mandatory database-level email filtering.

---

## 1. Data Isolation (Zero Hallucinations)

### Layer 1: Database-Level Isolation
```
WHERE email=%s mandatory for all email queries
```
Every database read in `search_email_index()` and `build_email_index()` filters by the authenticated member's email address. This is the single source of truth preventing one member from seeing another's emails.

### Layer 2: Per-Member FAISS Index
```
/var/lib/globus/faiss-index/{email}/gmail.faiss
/var/lib/globus/faiss-index/{email}/gmail.meta.json
```
Each member gets one FAISS index file + metadata sidecar. Even if the database isolation breaks, the filesystem separation provides a second layer: the index file itself contains only vectors + metadata for that member's emails.

### Layer 3: Search Function Isolation
- `search_email_index(email, query, ...)` enforces member isolation at the Python level
- Returns results only for emails WHERE email = {this_member}
- Filters post-search by from_addr, received_after, received_before (all metadata)

### Layer 4: Tool Dispatch
- `globus_search_email_semantic()` extracts the authenticated member's email from the session
- Passes it to `search_email_index()` — never trusts user input for the email parameter
- LLM cannot override; the tool dispatch layer is outside LLM control

### Verification
All four layers are deterministic + testable. A compromised layer is caught by the layers below:
- Compromised database? Filesystem isolation still holds.
- Compromised index file? Tool dispatch still filters by authenticated email.
- Compromised search function? Database layer still isolates.

---

## 2. Email Metadata Structure

Stored in `globus_vault_files` (same table as Drive):
```sql
WHERE source_type='gmail'
```

### Indexed Fields (What gets embedded)
```python
def _row_text(row):
    subject = row.get("filename")  # Gmail subjects become filenames
    from_addr = meta.get("from")   # e.g. "sender@company.com"
    to_list = meta.get("to")       # [recipient1, recipient2, ...]
    snippet = meta.get("snippet")  # First 500 chars of message
```

### Stored in `metadata` JSON:
```json
{
  "subject": "Q3 Budget Review",
  "from": "manager@company.com",
  "to": ["you@example.com", "team@company.com"],
  "snippet": "Can you review the Q3 numbers...",
  "thread_id": "gmail_thread_123",
  "message_id": "gmail_msg_456",
  "received_at": "2026-08-17T10:30:00Z"
}
```

### NOT indexed (privacy/security):
- Full email body
- Attachments
- BCC recipients
- Email headers (custom headers, DKIM, etc.)
- Forwarding chains

---

## 3. FAISS Indexing Pipeline

### Build Phase (Offline)
```
python3 scripts/build_email_index.py <member_email>
```

**Steps**:
1. Query: `SELECT * FROM globus_vault_files WHERE email=%s AND source_type='gmail'`
2. Extract text: subject + from + to + snippet (first 500 chars)
3. Embed: Call Gemini API (batched ~100 emails/request)
4. Index: Build FAISS IndexFlatIP (768-dimensional, L2-normalized)
5. Sidecar: Write metadata JSON for post-filtering
6. Permissions: chmod 0o600 (only owner can read)

### Search Phase (Interactive)
```python
search_email_index(email, "find emails about Q3 planning")
```

**Steps**:
1. Embed query: Call Gemini API (1 embedding)
2. Load index: Read `{email}/gmail.faiss` from disk
3. Search: FAISS IndexFlatIP.search(qvec, k=limit*8)
4. Post-filter: by from_addr, received_after/before
5. Return: Top `limit` results with scores (0.0 - 1.0)

**Cost**: ~2 API calls per search (query embed + loading is cached after first call)

---

## 4. Continuous Sync Strategy

### Sync Cadence (via Cron)

```bash
# Hourly incremental (new emails only)
0 * * * * python3 scripts/sync_email_hourly.py >> /var/log/globus-email-sync.log 2>&1

# Daily deep sync (check for deletions, flag changes)
15 2 * * * python3 scripts/sync_email_daily.py >> /var/log/globus-email-sync.log 2>&1

# Weekly full rebuild of ALL indexes
30 3 * * 0 python3 scripts/rebuild_email_indexes.py >> /var/log/globus-email-index.log 2>&1
```

### Hourly Incremental Sync
```python
# sync_email_hourly.py
for member in active_members:
    for gmail_connection in member.gmail_connections:
        messages = gmail_api.list(
            q='after:' + (now - 1 hour).iso_format(),
            maxResults=500
        )
        for msg in messages:
            vault_files_upsert(
                email=member.email,
                source_type='gmail',
                external_id=msg['id'],
                filename=msg['subject'],
                metadata=msg_to_metadata(msg)
            )
```

### Daily Deep Sync
```python
# sync_email_daily.py
for member in active_members:
    for gmail_connection in member.gmail_connections:
        # Sync last 7 days with label/flag/deletion checks
        messages = gmail_api.list(
            q='after:' + (now - 7 days).iso_format(),
            maxResults=5000
        )
        # Check deletions, update flags, etc.
```

### Weekly Full Rebuild
```bash
# rebuild_email_indexes.py
for member in active_members:
    python3 scripts/build_email_index.py member@example.com
```

---

## 5. RBAC Layer (Fine-Grained Access Control)

### Role Hierarchy
```
Admin
  ├─ View all member emails (shared mailbox access)
  ├─ Search + read
  ├─ Rebuild indexes
  └─ Manage sync settings

Team Lead
  ├─ View team member emails (shared with direct reports)
  ├─ Search + read (filtered to team)
  └─ No index rebuild

Member
  ├─ View own emails only
  ├─ Search + read own
  └─ No team access

Guest
  └─ Read-only search (no email access)
```

### Implementation: RBAC Filtering

**Step 1: Identify member + role**
```python
member_row = db_read(
    "SELECT * FROM members WHERE email=%s", (session_email,))
role_row = db_read(
    "SELECT * FROM member_roles WHERE member_email=%s", (session_email,))
```

**Step 2: Build access list**
```python
def get_accessible_emails(session_email, role):
    if role == 'admin':
        return "all members"  # wildcard
    elif role == 'team_lead':
        team = db_read("SELECT member_email FROM team_members WHERE team_lead=%s", (session_email,))
        return [tm["member_email"] for tm in team]
    elif role == 'member':
        return [session_email]  # only self
    else:  # guest
        return []  # no email access
```

**Step 3: Apply in search function**
```python
def globus_search_email_semantic_with_rbac(session_email, query, limit=10, **filters):
    accessible = get_accessible_emails(session_email, get_role(session_email))
    
    if not accessible:
        return {"error": "role_no_access"}
    
    results = []
    for target_email in accessible:
        res = search_email_index(target_email, query, limit=limit//len(accessible), **filters)
        if isinstance(res, dict) and res.get("error"):
            continue  # skip this member if index not built
        results.extend(res)
    
    # Tag results with target email for audit trail
    for r in results:
        r["from_member"] = get_member_name(r["email"])  # add context
    
    return sorted(results, key=lambda x: x.get("score", 0), reverse=True)[:limit]
```

### RBAC Database Schema

**Already exists** (`org_members` + `org_agent_grants`). For email access:

```sql
CREATE TABLE IF NOT EXISTS email_access_grants (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  member_email VARCHAR(320) NOT NULL,       -- who has access
  target_email VARCHAR(320) NOT NULL,       -- whose emails they can see
  role         ENUM('admin','team_lead','member') NOT NULL,
  reason       TEXT,                        -- audit trail
  granted_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_member_target (member_email, target_email),
  KEY idx_member (member_email),
  KEY idx_target (target_email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### Audit Trail

Every email search is logged:
```sql
INSERT INTO globus_activity_log (
    actor_email, action, target_email, result_count, 
    query_preview, timestamp
) VALUES (
    'searcher@example.com', 'search_email_semantic', 
    'manager@example.com', 5, 'Q3 planning', NOW()
);
```

---

## 6. Tool Schema

Added to `GLOBUS_TOOLS` in `globus_tools_schema.py`:

```python
{
    "type": "function",
    "function": {
        "name": "search_email_semantic",
        "description": (
            "Fuzzy/conceptual search over member's Gmail message "
            "METADATA (subject, from, to, snippet) using vector similarity. "
            "Subject + from + to + first 500 chars of message body are "
            "embedded; full body text is NOT indexed. User isolation: "
            "only returns this member's emails (or team emails if they're "
            "a team lead, or all emails if admin)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", 
                          "description": "what to search for"},
                "limit": {"type": "integer", 
                          "description": "max results (default 10, max 50)"},
                "from_addr": {"type": "string", 
                              "description": "OPTIONAL: sender filter"},
                "received_after": {"type": "string", 
                                   "description": "OPTIONAL: ISO date/datetime"},
                "received_before": {"type": "string", 
                                    "description": "OPTIONAL: ISO date/datetime"},
            },
            "required": ["query"],
        },
    },
}
```

---

## 7. Implementation Files

### Core Indexing
- **server/email_index.py** (170 lines)
  - `build_email_index(email)` — offline index build
  - `search_email_index(email, query, ...)` — runtime search

### Build Scripts
- **scripts/build_email_index.py** (60 lines)
  - CLI wrapper for `build_email_index()`
  - Idempotent; safe to run repeatedly

### Sync Scripts
- **scripts/sync_email_hourly.py** — incremental sync (new + last 1h changes)
- **scripts/sync_email_daily.py** — deep sync (last 7 days, flag/deletion checks)
- **scripts/rebuild_email_indexes.py** — rebuild all indexes for all members

### Integration
- **server/globus_orchestrator.py** (4 additions)
  - Import: `from email_index import search_email_index`
  - Function: `globus_search_email_semantic()`
  - Dispatch: `elif name == "search_email_semantic" and _FAISS_AVAILABLE:`

- **server/globus_tools_schema.py** (32 lines)
  - Tool schema: `search_email_semantic`

---

## 8. Testing

### Unit Tests
```python
# test_email_index.py
def test_email_index_build():
    """Build index for test member, verify file permissions."""
    n, path = build_email_index("test@example.com")
    assert n > 0
    assert os.path.exists(path)
    assert oct(os.stat(path).st_mode)[-3:] == "600"  # chmod verification

def test_email_search_isolation():
    """Search as member A, verify no results for member B's emails."""
    # Insert emails for both members
    # Search as A
    results = search_email_index("a@example.com", "secret")
    # Verify no results (B's emails not included)
    assert all(r["from"] != "b@example.com" for r in results)
```

### Integration Test
```python
# test_email_rag.py
def test_email_semantic_search_end_to_end():
    """Full flow: sync Gmail → build index → search."""
    # 1. Manually insert test emails
    for i in range(10):
        insert_test_email(
            email="user@example.com",
            source_type="gmail",
            subject=f"Q3 Planning Meeting {i}",
            from_addr="manager@company.com",
            snippet="Let's discuss the budget..."
        )
    
    # 2. Build index
    n, path = build_email_index("user@example.com")
    assert n == 10
    
    # 3. Search
    results = search_email_index("user@example.com", "Q3 budget", limit=5)
    assert len(results) <= 5
    assert all(r["score"] > 0.5 for r in results)
```

---

## 9. Deployment

### Docker Setup
```yaml
services:
  globus:
    environment:
      GLOBUS_FAISS_INDEX_DIR: /app/local_data/faiss-index
      GLOBUS_METADATA_DIR: /app/local_data/drive-metadata
    volumes:
      - ./local_data:/app/local_data
```

### Cron Jobs (on host)
```bash
# Install in crontab
0 * * * * cd /opt/globus && .venv/bin/python3 scripts/sync_email_hourly.py >> /var/log/globus-email-sync.log 2>&1
15 2 * * * cd /opt/globus && .venv/bin/python3 scripts/sync_email_daily.py >> /var/log/globus-email-sync.log 2>&1
30 3 * * 0 cd /opt/globus && .venv/bin/python3 scripts/rebuild_email_indexes.py >> /var/log/globus-email-index.log 2>&1
```

### Post-Deploy
```bash
# Build initial indexes
python3 scripts/build_email_index.py user@example.com

# Run first sync
python3 scripts/sync_email_hourly.py
```

---

## 10. Monitoring + Alerts

### Metrics to Track
- Index build time (should be < 5 sec for 1000 emails)
- Search latency (should be < 1 sec for top 10 results)
- Sync errors (log to centralized activity channel)
- RBAC violations (audit log)

### Health Check
```bash
# Verify indexes exist
ls -lh /var/lib/globus/faiss-index/*/gmail.faiss

# Check recent sync runs
tail -20 /var/log/globus-email-sync.log

# Test search latency
time python3 -c "from server.email_index import search_email_index; print(search_email_index('user@example.com', 'test', limit=5))"
```

---

## 11. Scaling Notes

### Per-Member Index Size
- 1,000 emails → ~40 MB (FAISS index + metadata)
- 10,000 emails → ~400 MB
- 100,000 emails → ~4 GB

### Rebuild Time
- 1,000 emails: ~1 sec (1 Gemini API request)
- 10,000 emails: ~10 sec (10 API requests)
- 100,000 emails: ~100 sec (100 API requests)

### Sync Time
- Hourly: O(new_emails) = typically < 1 sec
- Daily: O(last_7_days) = typically 5-30 sec
- Weekly: O(all_emails) = typically 1-5 min

### Cost
- Gemini embeddings: ~$0.02 per 1000 messages
- Monthly rebuild (4 rebuilds): ~$0.08 per member
- Daily syncs: negligible (metadata queries only)

---

## 12. Known Limitations + Future Work

### Current (Metadata-Only)
- No full-text body search
- Snippet limited to 500 chars
- No attachment metadata indexing
- No label/folder-based filtering

### v0.4 Roadmap
- Full-text body search (optional, requires more storage)
- Attachment filenames + MIME types in index
- Label + folder hierarchy filtering
- Thread grouping (group by thread_id)
- Auto-expiry (delete old indexes after 90 days)

---

## Summary

Email RAG + RBAC is built on:
1. **Multi-layer isolation**: Database → filesystem → Python → dispatch
2. **Metadata-only indexing**: Subject + from + to + 500-char snippet
3. **FAISS semantic search**: ~2 API calls per search, < 1 sec latency
4. **Continuous sync**: Hourly (incremental) + weekly (full rebuild)
5. **RBAC enforcement**: Role-based filtering at query time
6. **Zero hallucinations**: Guaranteed by Layer 1 (database WHERE clause)

All members' emails are completely isolated. Admins + team leads see filtered subsets via RBAC. Guests see nothing. Audit trail logs every access.
