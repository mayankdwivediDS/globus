"""FAISS semantic index over Drive file METADATA (filenames, mime types,
owners) — matches GOOGLE_DRIVE_METADATA_ONLY: no file content is ever
embedded or indexed here, only what sync_drive.py already indexes into
`globus_vault_files`.

One index per (member, Google account), built OFFLINE by
scripts/build_drive_index.py — never inline in the interactive chat loop.
Embedding thousands of rows synchronously would blow the per-turn latency
budget every other LLM call in this codebase is deliberately kept under;
the chat-side tool (search_drive_semantic, wired in globus_orchestrator.py)
only ever does ONE embedding call (the query) plus a read of a pre-built
index off disk.

Degrades gracefully: if faiss/numpy aren't installed (they're optional —
see requirements-optional.txt), FAISS_AVAILABLE is False and callers should
skip offering the tool, same pattern as _GMAIL_AVAILABLE elsewhere.
"""
from __future__ import annotations
import json
import os
import re

from db_helpers import db_read
from globus_llm import globus_call_gemini_embed

try:
    import faiss
    import numpy as np
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False


# Separate from GLOBUS_METADATA_DIR (raw JSON dumps) and RAW_DATA_DIR
# (extracted content, unused in metadata-only mode) — this is the vector
# index + its metadata sidecar.
INDEX_DIR = os.environ.get("GLOBUS_FAISS_INDEX_DIR", "/var/lib/globus/faiss-index")


def _safe(s):
    return re.sub(r"[^A-Za-z0-9@_.-]", "_", str(s or "_"))[:200]


def _paths(email, provider_account):
    d = os.path.join(INDEX_DIR, _safe(email))
    os.makedirs(d, exist_ok=True)
    base = os.path.join(d, _safe(provider_account) + "__google-drive")
    return base + ".faiss", base + ".meta.json"


def _parse_meta_json(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def _row_text(row):
    """What actually gets embedded — filename + type + owner names. No
    content, because in metadata-only mode there IS no content on disk."""
    meta = _parse_meta_json(row.get("metadata"))
    owners = ", ".join(
        o.get("displayName") or o.get("emailAddress") or ""
        for o in (meta.get("owners") or []) if isinstance(o, dict)
    ).strip()
    bits = [row.get("filename") or "(untitled)", f"({row.get('mime_type') or 'unknown type'})"]
    if owners:
        bits.append(f"owned by {owners}")
    return " ".join(bits)


def build_drive_index(email, provider_account):
    """(Re)build the FAISS index for one member+Google account from the
    current globus_vault_files rows. Overwrites any existing index for
    this account. Returns (n_indexed, index_path)."""
    if not FAISS_AVAILABLE:
        raise RuntimeError(
            "faiss/numpy not installed — pip install -r requirements-optional.txt")
    rows = db_read(
        "SELECT external_id, filename, mime_type, size_bytes, modified_at, "
        "metadata FROM globus_vault_files "
        "WHERE email=%s AND provider_account=%s AND source_type='google-drive'",
        (email, provider_account)) or []
    if not rows:
        return 0, None

    texts = [_row_text(r) for r in rows]
    vectors = globus_call_gemini_embed(texts)
    mat = np.array(vectors, dtype="float32")
    faiss.normalize_L2(mat)  # so IndexFlatIP dot-product == cosine similarity
    index = faiss.IndexFlatIP(mat.shape[1])
    index.add(mat)

    meta_rows = []
    for r in rows:
        meta = _parse_meta_json(r.get("metadata"))
        owners = [o.get("emailAddress") for o in (meta.get("owners") or [])
                  if isinstance(o, dict) and o.get("emailAddress")]
        modified = r.get("modified_at")
        meta_rows.append({
            "id": r.get("external_id"),
            "filename": r.get("filename"),
            "mime_type": r.get("mime_type"),
            "size_bytes": r.get("size_bytes"),
            "modified_at": modified.isoformat() if hasattr(modified, "isoformat") else (modified or ""),
            "owners": owners,
            "webViewLink": meta.get("webViewLink"),
        })

    idx_path, meta_path = _paths(email, provider_account)
    faiss.write_index(index, idx_path)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta_rows, fh)
    for p in (idx_path, meta_path):
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    return len(rows), idx_path


def search_drive_index(email, provider_account, query, limit=10, mime_type=None,
                        owner_email=None, modified_after=None, modified_before=None):
    """Semantic search over a pre-built index. Post-filters by mime_type /
    owner_email / modified_at range (FAISS's flat index has no native
    metadata filter, so we over-fetch by vector similarity then filter).
    Returns a list of metadata dicts + similarity score, or a dict with
    an 'error' key if the index doesn't exist yet or faiss isn't installed."""
    if not FAISS_AVAILABLE:
        return {"error": "faiss/numpy not installed on this install"}
    idx_path, meta_path = _paths(email, provider_account)
    if not (os.path.exists(idx_path) and os.path.exists(meta_path)):
        return {"error": "no index built yet for this account — run "
                          "scripts/build_drive_index.py " + email + " " + provider_account}

    index = faiss.read_index(idx_path)
    with open(meta_path, encoding="utf-8") as fh:
        meta_rows = json.load(fh)
    if index.ntotal == 0 or not meta_rows:
        return []

    [qvec] = globus_call_gemini_embed([query])
    qmat = np.array([qvec], dtype="float32")
    faiss.normalize_L2(qmat)

    # Over-fetch (8x) so post-filtering still has enough candidates to
    # return `limit` results even when a filter is narrow.
    k = min(max(int(limit), 1) * 8, index.ntotal)
    scores, ids = index.search(qmat, k)

    owner_needle = owner_email.lower() if owner_email else None
    mime_needle = mime_type.lower() if mime_type else None
    results = []
    for score, i in zip(scores[0], ids[0]):
        if i < 0 or i >= len(meta_rows):
            continue
        row = meta_rows[i]
        if mime_needle and mime_needle not in (row.get("mime_type") or "").lower():
            continue
        if owner_needle and owner_needle not in [o.lower() for o in (row.get("owners") or [])]:
            continue
        mtime = row.get("modified_at") or ""
        if modified_after and mtime < modified_after:
            continue
        if modified_before and mtime > modified_before:
            continue
        results.append({**row, "score": round(float(score), 4)})
        if len(results) >= limit:
            break
    return results
