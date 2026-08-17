# Running Drive RAG Integration

## Prerequisites

The full Drive RAG system requires:
- Docker Desktop running
- MySQL database with Globus schema
- Drive data synced to `globus_vault_files` table
- Gemini API key configured

## Quick Start

### 1. Start Docker

**Windows/Mac with Docker Desktop:**
```powershell
# Start Docker Desktop application, or via CLI:
docker desktop  # or just click the application icon
```

**Verify Docker is running:**
```bash
docker ps  # should list running containers
```

### 2. Start Globus Services

```bash
cd ~/globus
docker compose up -d
```

**Wait for the database to be ready (~30 seconds):**
```bash
docker compose logs -f db | grep -i "ready for connections"
```

### 3. Verify Services are Up

```bash
docker compose ps

# Expected output:
# NAME      IMAGE            STATUS
# db        mysql:8.0        Up (healthy)
# globus    globus:0.15.0    Up
```

### 4. Run the Full RAG Test

Once services are running:

```bash
python run_drive_rag.py
```

**Expected output:**
```
======================================================================
DRIVE RAG INTEGRATION - FULL SYSTEM TEST
======================================================================

[STEP 1] Database Connection
--
Connecting to: globus@db:3306/globus
[OK] Database connected

[STEP 2] Inventory Drive Files
--
Total Drive files in vault: 1,234

Member accounts with Drive files:
  - user@example.com / user@gmail.com: 856 files
  - ...
```

## What Happens Next

### If Drive Files Exist (Automatic)

1. **STEP 3:** Builds FAISS index for each member+account
   - One Gemini embedding API call per ~100 files
   - Takes ~5-10 seconds for 1,000 files
   - Saves `.faiss` + `.meta.json` to `./local_data/faiss-index/`

2. **STEP 4:** Tests semantic searches
   - Queries: "budget spreadsheet", "quarterly report", etc.
   - Returns top 3 results with similarity scores
   - Should show semantically relevant files even if keywords don't match

3. **STEP 5:** Verifies chat tool integration
   - Checks `search_drive_semantic` is registered
   - Tests tool function directly
   - Confirms end-to-end chat flow works

### If No Drive Files (Expected on First Boot)

The test gracefully stops with:
```
[WARN] No Drive files to index. Add some Drive files first.

To test with sample data, you can:
  1. Sync a Google Drive account via the UI
  2. Or manually insert test data into globus_vault_files
```

## Populate Test Data

### Option A: Via the Web UI

1. Go to http://localhost:8090
2. Log in with dev OTP (check `docker compose logs globus`)
3. Connect a Google Drive account
4. Let the sync complete (~1-5 minutes depending on folder size)

### Option B: Manual SQL Insert (for testing)

```bash
# Insert sample Drive files for testing
docker compose exec db mysql -uglobus -p$DB_PASSWORD globus << 'EOF'
INSERT INTO globus_vault_files 
  (email, provider_account, source_type, external_id, filename, mime_type, modified_at, metadata, extracted, extracted_chars)
VALUES
  ('test@example.com', 'test@gmail.com', 'google-drive', 'id1', 'Q3 2026 Budget.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', NOW(), '{"owners":[{"emailAddress":"owner@gmail.com"}],"webViewLink":"https://drive.google.com/file/d/id1/"}', 1, 2048),
  ('test@example.com', 'test@gmail.com', 'google-drive', 'id2', 'Sales Report July.pdf', 'application/pdf', NOW(), '{"owners":[{"emailAddress":"owner@gmail.com"}],"webViewLink":"https://drive.google.com/file/d/id2/"}', 1, 5120),
  ('test@example.com', 'test@gmail.com', 'google-drive', 'id3', 'Customer contracts folder', 'application/vnd.google-apps.folder', NOW(), '{"owners":[{"emailAddress":"owner@gmail.com"}],"webViewLink":"https://drive.google.com/drive/folders/id3/"}', 0, 0);
EOF

echo "Test data inserted"
```

Then run:
```bash
python run_drive_rag.py
```

## Troubleshooting

### "Database query returned None"
**Cause:** Docker not running or database not ready  
**Fix:** 
```bash
docker compose ps  # Check if db is healthy
docker compose logs db  # View database logs
docker compose restart db  # Restart if needed
```

### "FAISS not available"
**Cause:** Optional dependencies not installed  
**Fix:**
```bash
pip install -r requirements-optional.txt
```

### "GEMINI_API_KEY not configured"
**Cause:** Missing API key  
**Fix:**
1. Get a Gemini API key from https://aistudio.google.com/app/apikey
2. Add to `.env`:
   ```
   GEMINI_API_KEY=your-key-here
   ```
3. Restart: `docker compose restart globus`

### "No Drive files to index"
**Cause:** Empty database  
**Fix:**
1. Use the web UI to sync a Drive account, OR
2. Use the manual SQL insert above (Option B)
3. Re-run the test

## Monitoring

### Watch Index Building in Progress

```bash
# Terminal 1: Watch Docker logs
docker compose logs -f globus

# Terminal 2: Run the test
python run_drive_rag.py
```

### Check Generated Indexes

```bash
# List all built indexes
ls -lah ./local_data/faiss-index/

# Example structure:
# local_data/faiss-index/
#   user@example.com/
#     user@gmail.com__google-drive.faiss       (the vector index)
#     user@gmail.com__google-drive.meta.json   (metadata sidecar)
```

### Inspect Index Contents

```bash
# View metadata for a built index
python -c "
import json
with open('./local_data/faiss-index/user@example.com/user@gmail.com__google-drive.meta.json') as f:
    meta = json.load(f)
    print(f'Index contains {len(meta)} files')
    for item in meta[:3]:
        print(f\"  - {item['filename']} ({item['mime_type']})\")
"
```

## Next Steps

### After Testing Works

1. **Set Production Index Directory:**
   ```bash
   # On prod servers, change in docker-compose.yml or .env:
   GLOBUS_FAISS_INDEX_DIR=/var/lib/globus/faiss-index  # Change to prod path
   ```

2. **Add Cron for Automatic Index Rebuilds:**
   ```bash
   # After nightly Drive sync, rebuild all member indexes
   15 3 * * *  cd /opt/globus && python scripts/build_drive_index.py "*" 2>&1 >> /var/log/globus-build-indexes.log
   ```

3. **Monitor Index Age:**
   ```bash
   # Alert if indexes are older than 24 hours
   # (indicating sync or index build failure)
   ```

4. **User-Facing Features:**
   - Chat will automatically show `search_drive_semantic` tool
   - Users can search: *"Find spreadsheets about Q3 planning"*
   - Tool returns top 10 matches with similarity scores
   - Users can click results to open in Drive

## Performance Expectations

| Operation | Time | Cost |
|-----------|------|------|
| Embed 100 Drive files | ~1-2s | 1 Gemini embed call |
| Build 1,000-file index | ~10-15s | 10 Gemini embed calls |
| Search query | ~100-300ms | 1 Gemini embed call |
| Annual embeddings (nightly) | ~365 API calls | ~$0.10 |

**Cost is negligible** — Gemini batch embedding is extremely cheap.

## Architecture Diagram

```
User Chat
    |
    v
Orchestrator (globus_orchestrator.py)
    |
    +-- search_drive_semantic tool
         |
         v
    Drive Index (server/drive_index.py)
         |
         +-- Load .faiss index (disk)
         +-- Embed query (Gemini API)
         +-- FAISS semantic search
         +-- Load .meta.json sidecar
         |
         v
    Top 10 results (filename, mime_type, owner, score, link)
         |
         v
    LLM formats results for user

(Index built offline by scripts/build_drive_index.py after Drive sync)
```

## Cleanup

To stop and remove all containers/volumes:

```bash
docker compose down -v
```

To keep data but stop services:

```bash
docker compose down
```

---

**For questions:** See DRIVE_RAG_STATUS.md for integration details.
