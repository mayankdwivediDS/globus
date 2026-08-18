#!/usr/bin/env python3
"""Weekly rebuild of all email indexes for all members.

Rebuilds FAISS indexes from scratch for all active members. Run after
major email sync cycles or when email metadata has significantly changed.

Cron:
  30 3 * * 0 python3 scripts/rebuild_email_indexes.py >> /var/log/globus-email-index.log 2>&1

Exit codes:
  0  success
  1  database error
  2  faiss/numpy not installed
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
    _boot()
    from email_index import FAISS_AVAILABLE, build_email_index
    from db_helpers import db_read

    if not FAISS_AVAILABLE:
        print("[rebuild-email-indexes] faiss/numpy not installed — "
              "pip install -r requirements-optional.txt", flush=True)
        return 2

    print("[rebuild-email-indexes] Starting weekly index rebuild", flush=True)

    # Get all members with Gmail data
    members = db_read(
        "SELECT DISTINCT email FROM globus_vault_files "
        "WHERE source_type='gmail' "
        "ORDER BY email") or []

    rebuilt_count = 0
    skipped_count = 0
    error_count = 0

    for member_row in members:
        email = member_row["email"]

        try:
            n, path = build_email_index(email)
            if n == 0:
                print(f"[rebuild-email-indexes] {email}: no emails to index", flush=True)
                skipped_count += 1
            else:
                print(f"[rebuild-email-indexes] {email}: rebuilt {n} emails -> {path}",
                      flush=True)
                rebuilt_count += 1

        except Exception as e:
            error_count += 1
            print(f"[rebuild-email-indexes] ERROR {email}: {e}", flush=True)

    print(f"[rebuild-email-indexes] Completed: {rebuilt_count} rebuilt, "
          f"{skipped_count} skipped, {error_count} errors", flush=True)
    return 0 if error_count == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
