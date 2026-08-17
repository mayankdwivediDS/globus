#!/usr/bin/env python3
"""Test Drive metadata RAG integration end-to-end.

Tests:
1. FAISS availability
2. Database connectivity to globus_vault_files
3. Drive index building
4. Semantic search over built index
"""
import os
import sys
import json
from pathlib import Path

# Fix Windows encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Add server to path
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root / "server"))

# ─────────────────────────────────────────────────────────────────────
# Step 1: Check dependencies
# ─────────────────────────────────────────────────────────────────────
print("[1/5] Checking FAISS/numpy...")
try:
    import faiss
    import numpy as np
    print("  [OK] faiss and numpy available")
    FAISS_OK = True
except ImportError as e:
    print(f"  [FAIL] MISSING: {e}")
    print("  → Install with: pip install -r requirements-optional.txt")
    FAISS_OK = False

# ─────────────────────────────────────────────────────────────────────
# Step 2: Check environment
# ─────────────────────────────────────────────────────────────────────
print("\n[2/5] Checking environment...")
env_file = repo_root / ".env"
if env_file.exists():
    print(f"  [OK] .env file found")
    # Load .env
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
else:
    print(f"  [FAIL] .env not found at {env_file}")

# Check required env vars
required = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME", "GEMINI_API_KEY"]
missing = [k for k in required if not os.environ.get(k)]
if missing:
    print(f"  [FAIL] Missing environment: {', '.join(missing)}")
    for k in missing:
        print(f"    {k}={os.environ.get(k, 'UNSET')}")
else:
    print(f"  [OK] All required env vars set")

# ─────────────────────────────────────────────────────────────────────
# Step 3: Database connectivity
# ─────────────────────────────────────────────────────────────────────
print("\n[3/5] Testing database connectivity...")
try:
    from db_helpers import configure, db_read
    configure(db_cfg={
        "host": os.environ.get("DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "globus"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "globus"),
    })

    # Test connectivity
    result = db_read("SELECT 1")
    if result is not None:
        print("  [OK] Database connected")

        # Check globus_vault_files table
        drive_files = db_read(
            "SELECT COUNT(*) as cnt FROM globus_vault_files "
            "WHERE source_type='google-drive'") or []
        if drive_files:
            count = drive_files[0].get("cnt", 0)
            print(f"  [OK] Found {count} Drive files in vault")

            if count > 0:
                # Show a sample
                sample = db_read(
                    "SELECT email, provider_account, filename, mime_type "
                    "FROM globus_vault_files "
                    "WHERE source_type='google-drive' LIMIT 3") or []
                print("  Sample files:")
                for row in sample:
                    print(f"    - {row.get('email')} / {row.get('filename')} ({row.get('mime_type')})")
        else:
            print("  [WARN] No Drive files found in vault (table may be empty)")
    else:
        print("  [FAIL] Database query failed")
except Exception as e:
    print(f"  [FAIL] Database error: {type(e).__name__}: {e}")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────
# Step 4: Test Gemini embeddings
# ─────────────────────────────────────────────────────────────────────
print("\n[4/5] Testing Gemini embeddings...")
try:
    from globus_llm import globus_call_gemini_embed
    test_text = ["test file about Q3 budget", "spreadsheet with sales data"]
    vectors = globus_call_gemini_embed(test_text)
    if vectors and len(vectors) == 2:
        print(f"  [OK] Gemini embeddings working")
        print(f"    Embedding dimension: {len(vectors[0]) if vectors[0] else 'unknown'}")
    else:
        print(f"  [FAIL] Embedding failed: got {len(vectors) if vectors else 0} results, expected 2")
except Exception as e:
    print(f"  [FAIL] Embedding error: {type(e).__name__}: {e}")

# ─────────────────────────────────────────────────────────────────────
# Step 5: Try building or searching index
# ─────────────────────────────────────────────────────────────────────
print("\n[5/5] Testing Drive index workflow...")

if not FAISS_OK:
    print("  [WARN] Skipping — FAISS not installed")
elif drive_files and drive_files[0].get("cnt", 0) > 0:
    try:
        from drive_index import build_drive_index, search_drive_index

        # Get first member+account from the sample
        accounts = db_read(
            "SELECT DISTINCT email, provider_account FROM globus_vault_files "
            "WHERE source_type='google-drive' LIMIT 1") or []

        if accounts:
            email = accounts[0].get("email")
            account = accounts[0].get("provider_account")
            print(f"  Building index for {email} / {account}...")

            n_indexed, idx_path = build_drive_index(email, account)
            print(f"  [OK] Indexed {n_indexed} files -> {idx_path}")

            # Try a test search
            if n_indexed > 0:
                print(f"  Testing semantic search...")
                results = search_drive_index(email, account, "budget spreadsheet", limit=3)
                if isinstance(results, dict) and "error" in results:
                    print(f"    [FAIL] Search error: {results['error']}")
                elif isinstance(results, list):
                    print(f"    [OK] Found {len(results)} results")
                    for r in results:
                        print(f"      - {r.get('filename')} (score: {r.get('score')})")
        else:
            print("  [WARN] No accounts found in database")
    except Exception as e:
        print(f"  [FAIL] Index workflow error: {type(e).__name__}: {e}")
else:
    print("  [WARN] No Drive files to index yet")

print("\n" + "="*60)
print("Test complete!")
print("="*60)
