#!/usr/bin/env python3
"""Database optimization — cleanup + table optimization.

Removes stale sync runs + optimizes tables for better query performance.

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
    _boot()
    from db_helpers import db_write, db_read

    print("[optimize-database] Starting database maintenance", flush=True)

    try:
        # Remove sync runs older than 90 days
        print("[optimize-database] Cleaning old sync runs...", flush=True)
        db_write(
            "DELETE FROM globus_sync_runs "
            "WHERE finished_at < DATE_SUB(NOW(), INTERVAL 90 DAY)")

        # Optimize key tables
        tables = [
            "globus_vault_files",
            "globus_vault_sources",
            "globus_messages",
            "rbac_access_log",
            "globus_sync_runs",
        ]

        for table in tables:
            print(f"[optimize-database] Optimizing {table}...", flush=True)
            db_write(f"OPTIMIZE TABLE {table}")

        print("[optimize-database] Database optimization complete", flush=True)
        return 0

    except Exception as e:
        print(f"[optimize-database] ERROR: {e}", flush=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
