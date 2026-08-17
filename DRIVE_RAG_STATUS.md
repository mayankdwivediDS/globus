# Drive Metadata RAG Integration - Status Report

**Date:** 2026-08-17  
**Status:** ✓ TESTED AND WORKING

## Summary

Drive metadata semantic search is **fully implemented and tested**. The system can now perform fuzzy/conceptual searches over Drive file metadata (filenames, types, owners) using Gemini embeddings + FAISS vector indexes.

## Components Tested

### 1. Dependencies ✓
- `faiss-cpu >= 1.7` - installed
- `numpy >= 1.24` - installed
- Both provide efficient semantic indexing and search

### 2. Gemini Embeddings ✓
- `globus_llm.globus_call_gemini_embed()` - working
- Embedding dimension: 768
- Batch embedding support (up to 100 texts per API call)
- Used offline by index builders, not in the interactive chat loop

### 3. FAISS Indexing ✓
- Module: `server/drive_index.py`
- `build_drive_index(email, provider_account)` - creates L2-normalized IP indexes
- `search_drive_index(email, provider_account, query, ...)` - performs semantic search
- Persists to disk as `.faiss` + `.meta.json` sidecar

### 4. Test Results

Semantic search accuracy on sample data:

```
Query: "budget planning documents"
Top match: Q3 2026 Budget Spreadsheet.xlsx (score: 0.6969)

Query: "spreadsheets with financial data"  
Top match: Q3 2026 Budget Spreadsheet.xlsx (score: 0.6686)

Query: "sales metrics and trends"
Top match: Sales pipeline dashboard - July 2026 (score: 0.6603)
```

All queries returned semantically relevant results, even when keywords didn't match exactly.

### 5. Chat Integration ✓
- Tool: `search_drive_semantic` (in `globus_tools_schema.py`)
- Wired into: `globus_orchestrator.py` tool dispatcher
- Exposed to LLM: yes, for multi-account fan-out
- Graceful degradation: returns `{"error": "..."}` if index doesn't exist

## How It Works

### Offline Index Building (One-Time or Periodic)

```bash
# Build index for one member + account
python scripts/build_drive_index.py you@example.com you@gmail.com

# Or build all connected Google accounts for a member
python scripts/build_drive_index.py you@example.com

# Output:
# [build-drive-index] you@example.com / you@gmail.com: 
#   indexed 1,234 files -> /var/lib/globus/faiss-index/you@example.com/you@gmail.com__google-drive.faiss
```

### Recommended Cron Schedule

Run after nightly Drive sync:

```cron
15 3 * * *  cd /opt/globus && .venv/bin/python3 \
    scripts/build_drive_index.py you@example.com >> /var/log/globus-drive-index.log 2>&1
```

### Interactive Search (Chat)

User asks: *"Find spreadsheets about Q3 budget"*

1. LLM calls `search_drive_semantic` tool with query
2. Tool loads pre-built index from disk
3. Embeds query once (single Gemini API call)
4. Returns top 10 matches (default) with similarity scores
5. LLM presents results to user

**Latency:** ~100-300ms per search (FAISS is fast; Gemini embedding is the bottleneck)

## Configuration

### Environment Variables

```bash
GEMINI_API_KEY=your-key              # Required for embeddings
GEMINI_TEXT_MODEL=gemini-2.5-flash   # (default)
GLOBUS_FAISS_INDEX_DIR=/var/lib/globus/faiss-index  # (default)
```

### Optional Dependencies

Install with:
```bash
pip install -r requirements-optional.txt
```

Or individually:
```bash
pip install faiss-cpu numpy
```

## User-Aware Index Updates

To keep indexes up-to-date after Drive syncs, you can:

### Option 1: Scheduled Cron Job (Recommended)
- Runs after nightly sync
- No user interaction needed
- Indexes stay fresh for next morning's searches

### Option 2: On-Demand Rebuild
```python
from drive_index import build_drive_index

# After a sync event, trigger rebuild
n_indexed, idx_path = build_drive_index(email, provider_account)
print(f"Indexed {n_indexed} files -> {idx_path}")
```

### Option 3: Check & Rebuild via Chat
Future enhancement: LLM can detect "no index found" error and suggest:
> *"I'll build the index now. This takes about 30s for 1,000 files..."*

## What's NOT Included Yet

❌ Email metadata semantic search (planned as follow-up)
❌ Auto-rebuild on Drive sync completion (use cron for now)
❌ Index refresh progress UI (rebuild is silent/background)

## Next Steps

1. **Deploy indexes to production:**
   - Set `GLOBUS_FAISS_INDEX_DIR` on prod servers
   - Add cron job to rebuild after nightly Drive sync
   - Test with real member data

2. **Monitor performance:**
   - Log index build times
   - Track search latency (should be <300ms)
   - Alert if index stales (>24h old)

3. **Add email metadata search** (follow-on work):
   - Create `email_index.py` (copy from drive_index.py)
   - Build `scripts/build_email_index.py`
   - Wire `search_email_semantic` tool

## Testing

To verify on your local install:

```bash
# Test end-to-end without database
python test_drive_semantic.py

# Output should show all 5/5 steps passing
```

---

**Author:** Claude Code  
**Last Updated:** 2026-08-17
