#!/usr/bin/env python3
"""Cleanup old audit logs — keep last N days.

Usage:
  python3 scripts/cleanup_audit_logs.py 90

  Deletes records older than 90 days from rbac_access_log table.

Exit codes:
  0  success
  1  database error
"""
from __future__ import annotations
import os
import sys

def _load_env(path):
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def _boot():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _load_env(os.path.join(repo_root, ".env"))
    sys.path.insert(0, os.path.join(repo_root, "server"))
    import db_helpers
    db_helpers.configure(db_cfg={
        "host":     os.environ.get("DB_HOST", "127.0.0.1"),
        "port":     int(os.environ.get("DB_PORT", "3306")),
        "user":     os.environ.get("DB_USER", "globus"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "globus"),
    })

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    days_to_keep = int(sys.argv[1].strip())
    _boot()
    from db_helpers import db_write, db_read

    print(f"[cleanup-audit-logs] Removing records older than {days_to_keep} days",
          flush=True)

    try:
        # Get count before deletion
        before = db_read(
            "SELECT COUNT(*) as cnt FROM rbac_access_log") or []
        before_count = before[0].get("cnt", 0) if before else 0

        # Delete old records
        db_write(
            "DELETE FROM rbac_access_log "
            "WHERE timestamp < DATE_SUB(NOW(), INTERVAL %s DAY)",
            (days_to_keep,))

        # Get count after deletion
        after = db_read(
            "SELECT COUNT(*) as cnt FROM rbac_access_log") or []
        after_count = after[0].get("cnt", 0) if after else 0

        deleted = before_count - after_count
        print(f"[cleanup-audit-logs] Deleted {deleted} records "
              f"({before_count} -> {after_count})", flush=True)
        return 0

    except Exception as e:
        print(f"[cleanup-audit-logs] ERROR: {e}", flush=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
