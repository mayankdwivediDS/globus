#!/usr/bin/env python3
"""Build/rebuild the FAISS semantic index over a member's Gmail metadata.

Offline by design — this is what does the embedding calls (one Gemini API
request per ~100 emails), which is exactly the kind of batch cost the
interactive chat tool (search_email_semantic) must NOT do inline. Run this
after a Gmail sync, or on a cron, to keep the index current.

Usage:
  python3 scripts/build_email_index.py <member_email>

  member_email   required — whose mailbox(es) to index.

Exit codes:
  0  built (including "0 emails, nothing to index")
  1  bad usage / member has no Gmail data
  2  faiss/numpy not installed (pip install -r requirements-optional.txt)

Example crontab — run after the nightly Gmail sync:
  30 3 * * *  cd /opt/globus && .venv/bin/python3 \\
      scripts/build_email_index.py you@example.com \\
      >> /var/log/globus-email-index.log 2>&1
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

    _boot()
    from email_index import FAISS_AVAILABLE, build_email_index
    if not FAISS_AVAILABLE:
        print("[build-email-index] faiss/numpy not installed — "
              "pip install -r requirements-optional.txt", flush=True)
        return 2

    n, path = build_email_index(email)
    print(f"[build-email-index] {email}: indexed {n} emails -> {path}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
