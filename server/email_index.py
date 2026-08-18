"""FAISS semantic index over Gmail METADATA (from, to, subject, snippet) —
matches GMAIL_METADATA_ONLY: no full email content is ever embedded or indexed
here, only message metadata that sync_drive.py already indexes.

One index per member (Gmail account is in metadata, all emails for a member go
in one index), built OFFLINE by scripts/build_email_index.py — never inline in
the interactive chat loop. Embedding thousands of messages synchronously would
blow the per-turn latency budget every other LLM call in this codebase
deliberately keeps under; the chat-side tool (search_email_semantic, wired in
globus_orchestrator.py) only ever does ONE embedding call (the query) plus a
read of a pre-built index off disk.

Degrades gracefully: if faiss/numpy aren't installed (they're optional — see
requirements-optional.txt), FAISS_AVAILABLE is False and callers should skip
offering the tool, same pattern as _DRIVE_AVAILABLE elsewhere.
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


def _paths(email):
    """Email index is per-member (all Gmail accounts for a member in one index)."""
    d = os.path.join(INDEX_DIR, _safe(email))
    os.makedirs(d, exist_ok=True)
    base = os.path.join(d, "gmail")
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
    """What actually gets embedded — subject + from + to + snippet. No
    content, because in metadata-only mode there IS no full body on disk."""
    meta = _parse_meta_json(row.get("metadata"))
    subject = (meta.get("subject") or row.get("filename") or "(no subject)").strip()
    from_addr = meta.get("from") or "(unknown sender)"
    to_list = meta.get("to") or []
    to_addrs = ", ".join(to_list[:3]) if isinstance(to_list, list) else str(to_list)
    snippet = meta.get("snippet") or ""
    # Truncate snippet to avoid embedding giant messages
    snippet = snippet[:500]

    bits = [subject]
    if from_addr:
        bits.append(f"from {from_addr}")
    if to_addrs:
        bits.append(f"to {to_addrs}")
    if snippet:
        bits.append(f"({snippet})")
    return " ".join(bits)


def build_email_index(email):
    """(Re)build the FAISS index for one member's emails from the current
    globus_vault_files rows where source_type='gmail'. Overwrites any existing
    index. Returns (n_indexed, index_path)."""
    if not FAISS_AVAILABLE:
        raise RuntimeError(
            "faiss/numpy not installed — pip install -r requirements-optional.txt")

    rows = db_read(
        "SELECT external_id, filename, mime_type, size_bytes, modified_at, "
        "metadata FROM globus_vault_files "
        "WHERE email=%s AND source_type='gmail'",
        (email,)) or []
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
        modified = r.get("modified_at")
        meta_rows.append({
            "id": r.get("external_id"),
            "subject": meta.get("subject") or r.get("filename") or "(no subject)",
            "from": meta.get("from") or "(unknown sender)",
            "to": meta.get("to") or [],
            "snippet": (meta.get("snippet") or "")[:500],
            "received_at": modified.isoformat() if hasattr(modified, "isoformat") else (modified or ""),
            "thread_id": meta.get("thread_id"),
            "message_id": meta.get("message_id"),
            "size_bytes": r.get("size_bytes"),
        })

    idx_path, meta_path = _paths(email)
    faiss.write_index(index, idx_path)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta_rows, fh)
    for p in (idx_path, meta_path):
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    return len(rows), idx_path


def search_email_index(email, query, limit=10, from_addr=None,
                       received_after=None, received_before=None):
    """Semantic search over a pre-built email index. Post-filters by from_addr
    and received_at range (FAISS's flat index has no native metadata filter, so
    we over-fetch by vector similarity then filter). Returns a list of metadata
    dicts + similarity score, or a dict with an 'error' key if the index
    doesn't exist yet or faiss isn't installed."""
    if not FAISS_AVAILABLE:
        return {"error": "faiss/numpy not installed on this install"}

    idx_path, meta_path = _paths(email)
    if not (os.path.exists(idx_path) and os.path.exists(meta_path)):
        return {"error": "no email index built yet — run "
                         "scripts/build_email_index.py " + email}

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

    from_needle = from_addr.lower() if from_addr else None
    results = []
    for score, i in zip(scores[0], ids[0]):
        if i < 0 or i >= len(meta_rows):
            continue
        row = meta_rows[i]
        if from_needle and from_needle not in (row.get("from") or "").lower():
            continue
        recv = row.get("received_at") or ""
        if received_after and recv < received_after:
            continue
        if received_before and recv > received_before:
            continue
        results.append({**row, "score": round(float(score), 4)})
        if len(results) >= limit:
            break
    return results
