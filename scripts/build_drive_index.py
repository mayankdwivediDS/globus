#!/usr/bin/env python3
"""Build/rebuild the FAISS semantic index over one member's Drive metadata.

Offline by design — this is what does the embedding calls (one Gemini API
request per ~100 files), which is exactly the kind of batch cost the
interactive chat tool (search_drive_semantic) must NOT do inline. Run this
after a Drive sync, or on a cron, to keep the index current.

Usage:
  python3 scripts/build_drive_index.py <member_email> [provider_account]

  member_email       required — whose vault to index.
  provider_account   optional — the connected Google account (e.g.
                      you@gmail.com). Omit to index every Google account
                      connected to this member, one index file each.

Exit codes:
  0  built (including "0 files, nothing to index")
  1  bad usage / member has no matching connection
  2  faiss/numpy not installed (pip install -r requirements-optional.txt)

Example crontab — run after the nightly Drive sync:
  15 3 * * *  cd /opt/globus && .venv/bin/python3 \\
      scripts/build_drive_index.py you@example.com \\
      >> /var/log/globus-drive-index.log 2>&1
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
    email = sys.argv[1].strip().lower()
    provider_account = sys.argv[2].strip() if len(sys.argv) > 2 else None

    _boot()
    from drive_index import FAISS_AVAILABLE, build_drive_index
    if not FAISS_AVAILABLE:
        print("[build-drive-index] faiss/numpy not installed — "
              "pip install -r requirements-optional.txt", flush=True)
        return 2

    from db_helpers import db_read
    accounts = ([provider_account] if provider_account else
                [r["provider_account"] for r in (db_read(
                    "SELECT DISTINCT provider_account FROM globus_oauth_connections "
                    "WHERE email=%s AND source_types LIKE '%%drive%%'",
                    (email,)) or [])])
    if not accounts:
        print(f"[build-drive-index] no Drive connection found for {email}", flush=True)
        return 1

    for account in accounts:
        n, path = build_drive_index(email, account)
        print(f"[build-drive-index] {email} / {account}: indexed {n} files -> {path}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
