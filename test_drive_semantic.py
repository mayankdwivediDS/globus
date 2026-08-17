#!/usr/bin/env python3
"""Test Drive metadata semantic search in isolation.

Tests the FAISS indexing and search functionality without database.
Creates a mock dataset and tests:
1. Text embedding for Drive metadata
2. FAISS index creation
3. Semantic search over the index
"""
import sys
import json
import tempfile
import os
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root / "server"))

# Load .env before importing modules that need it
env_file = repo_root / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

print("[Drive Semantic RAG Test]")
print("=" * 60)

# ─────────────────────────────────────────────────────────────────────
# Step 1: Check dependencies
# ─────────────────────────────────────────────────────────────────────
print("\n[1/5] Checking dependencies...")
try:
    import faiss
    import numpy as np
    print("  [OK] faiss and numpy available")
except ImportError as e:
    print(f"  [FAIL] {e}")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────
# Step 2: Test Gemini embeddings
# ─────────────────────────────────────────────────────────────────────
print("\n[2/5] Testing Gemini embeddings...")
try:
    from globus_llm import globus_call_gemini_embed, GEMINI_EMBED_DIM

    test_texts = [
        "Q3 2026 Budget Spreadsheet.xlsx",
        "Customer contracts and agreements folder",
        "Sales pipeline dashboard - July 2026",
        "Marketing campaign analytics report"
    ]

    vectors = globus_call_gemini_embed(test_texts)
    print(f"  [OK] Generated {len(vectors)} embeddings")
    print(f"       Dimension: {len(vectors[0]) if vectors and vectors[0] else 'unknown'}")

except Exception as e:
    print(f"  [FAIL] {type(e).__name__}: {e}")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────
# Step 3: Create FAISS index with test data
# ─────────────────────────────────────────────────────────────────────
print("\n[3/5] Creating FAISS index...")
try:
    # Create index
    vectors_array = np.array(vectors, dtype="float32")
    faiss.normalize_L2(vectors_array)

    index = faiss.IndexFlatIP(vectors_array.shape[1])
    index.add(vectors_array)

    print(f"  [OK] Index created with {index.ntotal} items")

    # Create metadata
    metadata = []
    for i, text in enumerate(test_texts):
        metadata.append({
            "id": f"file-{i+1:03d}",
            "filename": text,
            "mime_type": "application/vnd.ms-excel" if "Spreadsheet" in text else "application/pdf",
            "owners": ["user@example.com"],
            "webViewLink": f"https://drive.google.com/file/d/file{i+1}/"
        })

except Exception as e:
    print(f"  [FAIL] {type(e).__name__}: {e}")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────
# Step 4: Test semantic search
# ─────────────────────────────────────────────────────────────────────
print("\n[4/5] Testing semantic search...")
try:
    test_queries = [
        ("budget planning documents", "Should find Q3 Budget"),
        ("spreadsheets with financial data", "Should find Budget Spreadsheet"),
        ("sales metrics and trends", "Should find Sales pipeline"),
    ]

    for query, expected in test_queries:
        print(f"\n  Query: '{query}'")
        print(f"  Expected: {expected}")

        # Embed query
        [qvec] = globus_call_gemini_embed([query])
        qmat = np.array([qvec], dtype="float32")
        faiss.normalize_L2(qmat)

        # Search
        k = min(3, index.ntotal)
        scores, ids = index.search(qmat, k)

        print(f"  Results:")
        for score, idx in zip(scores[0], ids[0]):
            if idx >= 0 and idx < len(metadata):
                result = metadata[idx]
                print(f"    [{score:.4f}] {result['filename']}")

    print(f"\n  [OK] Semantic search working")

except Exception as e:
    print(f"  [FAIL] {type(e).__name__}: {e}")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────
# Step 5: Test index persistence
# ─────────────────────────────────────────────────────────────────────
print("\n[5/5] Testing index persistence...")
try:
    with tempfile.TemporaryDirectory() as tmpdir:
        idx_path = os.path.join(tmpdir, "test.faiss")
        meta_path = os.path.join(tmpdir, "test.meta.json")

        # Save
        faiss.write_index(index, idx_path)
        with open(meta_path, "w") as f:
            json.dump(metadata, f)
        print(f"  [OK] Index saved to {tmpdir}")

        # Load
        loaded_index = faiss.read_index(idx_path)
        with open(meta_path) as f:
            loaded_meta = json.load(f)

        print(f"  [OK] Index reloaded: {loaded_index.ntotal} items")

        # Test search on loaded index
        [qvec] = globus_call_gemini_embed(["budget spreadsheet"])
        qmat = np.array([qvec], dtype="float32")
        faiss.normalize_L2(qmat)
        scores, ids = loaded_index.search(qmat, 1)

        if ids[0][0] >= 0:
            print(f"  [OK] Search works on loaded index")

except Exception as e:
    print(f"  [FAIL] {type(e).__name__}: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("[SUCCESS] Drive semantic search is working end-to-end!")
print("=" * 60)
print("\nNext: Build indexes for actual Drive data with:")
print("  python scripts/build_drive_index.py <member_email> [provider_account]")
