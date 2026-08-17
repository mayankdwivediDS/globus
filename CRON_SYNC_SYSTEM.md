# Continuous Sync System - Cron Jobs for Drive + Gmail

**Keep all user data fresh across Drive and Gmail.**

---

## Overview

Multi-level sync strategy:
1. **Hourly Quick Sync** (15 min window) - New/modified files only
2. **Daily Deep Sync** (2 am) - Full audit + rebuilds
3. **Weekly Full Rebuild** (Sunday 3 am) - FAISS index rebuild for all users
4. **Real-time Webhooks** (Optional) - Instant Drive sync on change

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Sync Scheduler (Cron)                        │
└─────────────────────────────────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        v                      v                      v
   ┌────────────┐      ┌──────────────┐      ┌───────────────┐
   │  Hourly    │      │    Daily     │      │    Weekly     │
   │ Quick Sync │      │ Deep Sync    │      │ Full Rebuild  │
   │  (15 min)  │      │   (2 AM)     │      │  (Sun 3 AM)   │
   └────────────┘      └──────────────┘      └───────────────┘
        │                      │                      │
        v                      v                      v
   Drive Sync          Drive + Gmail Sync      All FAISS Indexes
   (new files)         (full validation)       (all users)
   
   + Gmail Sync        + DB Integrity          + Email Indexes
   (new emails)        + Log cleanup           + Drive Indexes
```

---

## Cron Jobs Configuration

### Job 1: Hourly Quick Sync (Every Hour)

```bash
# /etc/cron.d/globus-hourly
# Sync new/modified files from Drive and Gmail (last 1 hour)

0 * * * *  cd /opt/globus && .venv/bin/python3 scripts/sync_drive_hourly.py >> /var/log/globus-sync-hourly.log 2>&1
0 * * * *  cd /opt/globus && .venv/bin/python3 scripts/sync_gmail_hourly.py >> /var/log/globus-sync-gmail.log 2>&1
```

### Job 2: Daily Deep Sync (2 AM)

```bash
# /etc/cron.d/globus-daily
# Full audit: verify data integrity, rebuild metadata

0 2 * * *  cd /opt/globus && .venv/bin/python3 scripts/sync_drive_daily.py >> /var/log/globus-sync-daily.log 2>&1
15 2 * * *  cd /opt/globus && .venv/bin/python3 scripts/sync_gmail_daily.py >> /var/log/globus-sync-gmail-daily.log 2>&1
30 2 * * *  cd /opt/globus && .venv/bin/python3 scripts/rebuild_email_indexes.py >> /var/log/globus-email-index.log 2>&1
```

### Job 3: Weekly Full Rebuild (Sunday 3 AM)

```bash
# /etc/cron.d/globus-weekly
# Rebuild all FAISS indexes for all users

0 3 * * 0  cd /opt/globus && .venv/bin/python3 scripts/rebuild_all_indexes.py >> /var/log/globus-rebuild-weekly.log 2>&1
```

### Job 4: Maintenance (Daily 4 AM)

```bash
# /etc/cron.d/globus-maintenance
# Clean logs, verify database, check index health

30 4 * * *  cd /opt/globus && .venv/bin/python3 scripts/maintenance.py >> /var/log/globus-maintenance.log 2>&1
```

---

## Sync Scripts

### 1. Hourly Drive Sync

```python
#!/usr/bin/env python3
# scripts/sync_drive_hourly.py

"""Sync new/modified Drive files from last hour."""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "server"))

# Load env
from db_helpers import configure, db_read, db_write

configure(db_cfg={
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "globus"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "globus"),
})

from sync_drive import sync_drive_incremental

def main():
    print(f"\n[sync-hourly] Starting Drive sync at {datetime.now()}")
    
    # Get all active members with Drive connections
    members = db_read(
        "SELECT DISTINCT u.email FROM globus_users u "
        "JOIN globus_oauth_connections c ON u.email=c.email "
        "WHERE u.status='active' AND c.source_types LIKE '%%drive%%'") or []
    
    if not members:
        print("[sync-hourly] No members with Drive connections")
        return 0
    
    sync_count = 0
    error_count = 0
    
    for member in members:
        email = member['email']
        print(f"\n[sync-hourly] Syncing {email}...")
        
        try:
            # Sync only files modified in the last hour
            result = sync_drive_incremental(
                email,
                modified_after=datetime.now() - timedelta(hours=1),
                batch_size=100)
            
            if result and result.get('success'):
                files_synced = result.get('files_synced', 0)
                print(f"[sync-hourly] {email}: {files_synced} files synced")
                sync_count += files_synced
            else:
                error_count += 1
                print(f"[sync-hourly] {email}: Sync failed - {result.get('error')}")
                
        except Exception as e:
            error_count += 1
            print(f"[sync-hourly] {email}: Exception - {type(e).__name__}: {e}")
    
    print(f"\n[sync-hourly] Completed at {datetime.now()}")
    print(f"[sync-hourly] Total synced: {sync_count} files, Errors: {error_count}")
    
    return 0 if error_count == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
```

### 2. Hourly Gmail Sync

```python
#!/usr/bin/env python3
# scripts/sync_gmail_hourly.py

"""Sync new/modified Gmail messages from last hour."""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "server"))

from db_helpers import configure, db_read

configure(db_cfg={
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "globus"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "globus"),
})

from sync_gmail import sync_gmail_delta

def main():
    print(f"\n[sync-gmail-hourly] Starting Gmail sync at {datetime.now()}")
    
    # Get all active members with Gmail connections
    members = db_read(
        "SELECT DISTINCT u.email FROM globus_users u "
        "JOIN globus_oauth_connections c ON u.email=c.email "
        "WHERE u.status='active' AND c.source_types LIKE '%%gmail%%'") or []
    
    if not members:
        print("[sync-gmail-hourly] No members with Gmail connections")
        return 0
    
    sync_count = 0
    error_count = 0
    
    for member in members:
        email = member['email']
        print(f"\n[sync-gmail-hourly] Syncing {email}...")
        
        try:
            # Delta sync: only new messages
            result = sync_gmail_delta(email, cooldown_minutes=1)
            
            if result and result.get('success'):
                messages_synced = result.get('messages_synced', 0)
                print(f"[sync-gmail-hourly] {email}: {messages_synced} messages synced")
                sync_count += messages_synced
            else:
                error_count += 1
                print(f"[sync-gmail-hourly] {email}: Sync failed - {result.get('error')}")
                
        except Exception as e:
            error_count += 1
            print(f"[sync-gmail-hourly] {email}: Exception - {type(e).__name__}: {e}")
    
    print(f"\n[sync-gmail-hourly] Completed at {datetime.now()}")
    print(f"[sync-gmail-hourly] Total synced: {sync_count} messages, Errors: {error_count}")
    
    return 0 if error_count == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
```

### 3. Weekly Full Index Rebuild

```python
#!/usr/bin/env python3
# scripts/rebuild_all_indexes.py

"""Rebuild FAISS indexes for all users (weekly)."""

import os
import sys
from datetime import datetime
from pathlib import Path

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "server"))

from db_helpers import configure, db_read

configure(db_cfg={
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "globus"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "globus"),
})

from drive_index import build_drive_index, FAISS_AVAILABLE

def main():
    if not FAISS_AVAILABLE:
        print("[rebuild-weekly] FAISS not available - skipping")
        return 1
    
    print(f"\n[rebuild-weekly] Starting full index rebuild at {datetime.now()}")
    
    # Get all unique (email, provider_account) combinations with Drive files
    accounts = db_read(
        "SELECT DISTINCT email, provider_account FROM globus_vault_files "
        "WHERE source_type='google-drive'") or []
    
    if not accounts:
        print("[rebuild-weekly] No accounts to index")
        return 0
    
    success_count = 0
    error_count = 0
    
    for account in accounts:
        email = account['email']
        provider = account['provider_account']
        
        print(f"\n[rebuild-weekly] Indexing {email} / {provider}...")
        
        try:
            n_indexed, idx_path = build_drive_index(email, provider)
            print(f"[rebuild-weekly] ✓ Indexed {n_indexed} files -> {idx_path}")
            success_count += 1
            
        except Exception as e:
            error_count += 1
            print(f"[rebuild-weekly] ✗ Failed: {type(e).__name__}: {e}")
    
    print(f"\n[rebuild-weekly] Completed at {datetime.now()}")
    print(f"[rebuild-weekly] Success: {success_count}, Errors: {error_count}")
    
    return 0 if error_count == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
```

### 4. Email Index Rebuild (New!)

```python
#!/usr/bin/env python3
# scripts/rebuild_email_indexes.py

"""Build FAISS indexes for Gmail metadata (parallel to Drive)."""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "server"))

from db_helpers import configure, db_read, db_write

configure(db_cfg={
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "globus"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "globus"),
})

try:
    from email_index import build_email_index, FAISS_AVAILABLE
except ImportError:
    FAISS_AVAILABLE = False
    build_email_index = None

def main():
    if not FAISS_AVAILABLE or not build_email_index:
        print("[rebuild-email-index] Email indexing not available - skipping")
        return 1
    
    print(f"\n[rebuild-email-index] Starting email index rebuild at {datetime.now()}")
    
    # Get all members with Gmail synced data
    members = db_read(
        "SELECT DISTINCT email FROM globus_vault_files "
        "WHERE source_type='gmail'") or []
    
    if not members:
        print("[rebuild-email-index] No members with Gmail data")
        return 0
    
    success_count = 0
    error_count = 0
    
    for member in members:
        email = member['email']
        
        print(f"\n[rebuild-email-index] Indexing {email}...")
        
        try:
            n_indexed, idx_path = build_email_index(email)
            print(f"[rebuild-email-index] ✓ Indexed {n_indexed} emails -> {idx_path}")
            success_count += 1
            
        except Exception as e:
            error_count += 1
            print(f"[rebuild-email-index] ✗ Failed: {type(e).__name__}: {e}")
    
    print(f"\n[rebuild-email-index] Completed at {datetime.now()}")
    print(f"[rebuild-email-index] Success: {success_count}, Errors: {error_count}")
    
    return 0 if error_count == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
```

### 5. Maintenance Script

```python
#!/usr/bin/env python3
# scripts/maintenance.py

"""Daily maintenance: cleanup, verify integrity."""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "server"))

from db_helpers import configure, db_read, db_write

configure(db_cfg={
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "globus"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "globus"),
})

def cleanup_old_logs():
    """Remove sync logs older than 30 days."""
    log_dir = Path("/var/log")
    cutoff = datetime.now() - timedelta(days=30)
    
    removed = 0
    for log_file in log_dir.glob("globus-*.log"):
        if datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff:
            try:
                log_file.unlink()
                removed += 1
            except OSError:
                pass
    
    print(f"[maintenance] Removed {removed} old log files")

def verify_index_health():
    """Check if all built indexes are still on disk."""
    index_dir = Path(os.environ.get("GLOBUS_FAISS_INDEX_DIR", "/var/lib/globus/faiss-index"))
    
    if not index_dir.exists():
        print("[maintenance] Index directory doesn't exist")
        return 0, 0
    
    total = 0
    missing = 0
    
    accounts = db_read(
        "SELECT DISTINCT email, provider_account FROM globus_vault_files "
        "WHERE source_type='google-drive'") or []
    
    for account in accounts:
        email = account['email']
        provider = account['provider_account']
        
        # Check if index files exist
        email_dir = index_dir / email
        faiss_file = email_dir / f"{provider}__google-drive.faiss"
        meta_file = email_dir / f"{provider}__google-drive.meta.json"
        
        total += 1
        if not faiss_file.exists() or not meta_file.exists():
            missing += 1
            print(f"[maintenance] Missing index for {email}/{provider}")
    
    print(f"[maintenance] Index health: {total-missing}/{total} indexes present")
    return total, missing

def check_sync_status():
    """Report last sync time for each user."""
    members = db_read(
        "SELECT email, MAX(last_synced_at) as last_sync FROM globus_vault_files "
        "GROUP BY email") or []
    
    now = datetime.now()
    stale_count = 0
    
    for member in members:
        email = member['email']
        last_sync = member.get('last_sync')
        
        if not last_sync:
            continue
        
        hours_ago = (now - last_sync).total_seconds() / 3600
        
        if hours_ago > 24:
            stale_count += 1
            print(f"[maintenance] WARNING: {email} last synced {hours_ago:.1f} hours ago")
    
    print(f"[maintenance] Stale accounts: {stale_count}")

def main():
    print(f"\n[maintenance] Starting maintenance at {datetime.now()}")
    
    cleanup_old_logs()
    verify_index_health()
    check_sync_status()
    
    print(f"\n[maintenance] Completed at {datetime.now()}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

---

## Installation

### 1. Deploy Scripts

```bash
# Copy scripts to /opt/globus/scripts/
cp scripts/sync_drive_hourly.py /opt/globus/scripts/
cp scripts/sync_gmail_hourly.py /opt/globus/scripts/
cp scripts/rebuild_all_indexes.py /opt/globus/scripts/
cp scripts/rebuild_email_indexes.py /opt/globus/scripts/
cp scripts/maintenance.py /opt/globus/scripts/

# Make executable
chmod +x /opt/globus/scripts/sync_*.py /opt/globus/scripts/rebuild_*.py /opt/globus/scripts/maintenance.py
```

### 2. Install Cron Jobs

```bash
# Copy cron files
sudo cp cron.d/globus-hourly /etc/cron.d/
sudo cp cron.d/globus-daily /etc/cron.d/
sudo cp cron.d/globus-weekly /etc/cron.d/
sudo cp cron.d/globus-maintenance /etc/cron.d/

# Verify
sudo crontab -l | grep globus

# Test one job
/opt/globus/scripts/sync_drive_hourly.py
```

### 3. Monitor Logs

```bash
# Watch sync logs
tail -f /var/log/globus-sync-hourly.log
tail -f /var/log/globus-sync-gmail.log
tail -f /var/log/globus-rebuild-weekly.log

# Check cron execution
grep CRON /var/log/syslog | grep globus
```

---

## Sync Strategy

### Hourly (15 minutes to complete)
```
Purpose: Keep data fresh (new/modified files only)
Run:     Every hour
Time:    ~15 minutes
API Cost: Minimal (delta queries only)

Drive: Get files modified in last hour
Gmail: Get emails received in last hour
```

### Daily (2 AM - 30 minutes to complete)
```
Purpose: Full audit, validate all files
Run:     Daily at 2 AM
Time:    ~30 minutes
API Cost: Moderate (full audit)

Drive: Verify all files, check permissions
Gmail: Check all recent emails (7 days)
Email: Build semantic indexes for latest data
```

### Weekly (Sunday 3 AM - 60 minutes to complete)
```
Purpose: Rebuild all FAISS indexes from scratch
Run:     Every Sunday at 3 AM
Time:    ~60 minutes (for 10K+ files)
API Cost: High (full re-embedding)

All FAISS indexes: Rebuilt fresh
All user indexes: Optimized and compacted
```

### Maintenance (Daily 4 AM)
```
Purpose: Cleanup, health checks
Run:     Daily at 4 AM
Time:    ~5 minutes

Delete old logs (>30 days)
Verify index files exist
Check if any accounts are stale (>24h)
Alert on problems
```

---

## Monitoring & Alerts

### Log Files

```bash
/var/log/globus-sync-hourly.log       # Hourly Drive sync
/var/log/globus-sync-gmail.log        # Hourly Gmail sync
/var/log/globus-sync-daily.log        # Daily Drive audit
/var/log/globus-sync-gmail-daily.log  # Daily Gmail audit
/var/log/globus-email-index.log       # Email indexing
/var/log/globus-rebuild-weekly.log    # Weekly FAISS rebuild
/var/log/globus-maintenance.log       # Maintenance tasks
```

### Key Metrics to Monitor

```
[sync-hourly] ✓ Indexed 156 files -> /app/local_data/faiss-index/...
[sync-gmail-hourly] ✓ 12 messages synced
[rebuild-weekly] ✓ Indexed 10,014 files
[maintenance] Index health: 8/8 indexes present
```

### Alerts

Set up alerts for:
- Sync job failures (returns non-zero exit code)
- Stale indexes (>48 hours old)
- Missing index files
- High error rates in logs

---

## Scalability

| Scale | Sync Time | Cost |
|-------|-----------|------|
| 1 user, 1000 files | <1 min | Minimal |
| 5 users, 50K files | 5-10 min | Low |
| 50 users, 500K files | 30-60 min | Moderate |
| 500 users, 5M files | 2-3 hours | High |

For large scale:
- Run hourly sync in parallel per user
- Distribute weekly rebuild across week
- Use incremental sync (delta queries) instead of full sync

---

## Next: Email Metadata RAG

Parallel to Drive indexes, implement email metadata RAG:

```python
# server/email_index.py (similar to drive_index.py)

def build_email_index(email):
    """Build FAISS index from Gmail metadata."""
    # Get emails from globus_vault_files (source_type='gmail')
    # Extract: subject, from, to, date, labels, snippet
    # Embed with Gemini
    # Build FAISS index
    # Save to /faiss-index/{email}/gmail.faiss

def search_email_index(email, query, limit=10):
    """Semantic search over Gmail metadata."""
    # Search FAISS
    # Return: subject, from, date, similarity score
    # Can filter by: date range, sender, labels

# Wire into orchestrator as search_email_semantic
# Same isolation as Drive (email-scoped, separate indexes)
```

---

## Summary

### Cron Schedule
- **Hourly**: Quick sync (new files)
- **Daily 2 AM**: Deep sync + validation
- **Daily 4 AM**: Maintenance + health checks
- **Weekly (Sun 3 AM)**: Full FAISS rebuild

### Covered
- ✅ Drive data sync (incremental + full)
- ✅ Gmail data sync (incremental + full)
- ✅ FAISS index building (all users)
- ✅ Email indexing (ready to implement)
- ✅ Maintenance & monitoring
- ✅ Multi-user support

### Ready for
- Multi-user email RAG (same pattern as Drive)
- Continuous data freshness
- 24/7 search availability

