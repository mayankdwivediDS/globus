# Complete Startup Instructions - Drive RAG Voice Agent

## What You'll Get

A fully working Globus instance with:
- ✅ Voice chat interface
- ✅ Drive semantic search (5 sample files)
- ✅ FAISS indexes built and ready
- ✅ Gemini embeddings working
- ✅ End-to-end voice-to-answer flow

## Step-by-Step

### Step 1: Ensure Docker Desktop is Running

**Windows 11:**
1. Press `Windows Key` and search for "Docker"
2. Click "Docker Desktop"
3. Wait ~30 seconds for it to fully start (look for the whale icon in system tray)

**Check it's running:**
```powershell
docker ps
```
If this shows container info (or empty list), Docker is ready.

### Step 2: Open Terminal

**Windows:**
1. Press `Windows Key + X`
2. Select "Windows Terminal" (or PowerShell)
3. Navigate to Globus:
   ```powershell
   cd C:\Users\GLB-BLR-307\Documents\globus
   ```

### Step 3: Start Everything with One Command

Run the startup script:
```powershell
python start_system.py
```

### Step 4: What Happens

The script will:
1. ✅ Verify Docker is running
2. ✅ Start MySQL database container
3. ✅ Start Globus web app container
4. ✅ Insert 5 sample Drive files
5. ✅ Build FAISS semantic indexes
6. ✅ **Open browser to http://localhost:8090/chat**

**Total time:** ~2 minutes (mostly waiting for services)

### Step 5: Test the Voice Agent

**In your browser (should open automatically):**

1. **Look for the chat interface:**
   - Text input box at the bottom
   - Microphone icon next to it

2. **Click the microphone icon**

3. **Say one of these queries:**
   - "Find spreadsheets about Q3 budget"
   - "Show me sales reports and analytics"
   - "Files about marketing campaigns"

4. **Watch what happens:**
   - Your voice is transcribed to text
   - LLM analyzes your query
   - System searches 5 sample Drive files using semantic AI
   - Results with Drive links appear
   - Response is spoken back to you

## Architecture in Action

```
YOU SPEAK
    ↓
Speech Recognition (Browser)
    ↓
"Find spreadsheets about budget"
    ↓
LLM (Claude)
    ↓
Calls: search_drive_semantic("Find spreadsheets about budget")
    ↓
FAISS Index (Pre-built, on disk)
    ↓
Embeds your query with Gemini
    ↓
Semantic similarity search
    ↓
Returns: [
  {filename: "Q3 2026 Budget Proposal.xlsx", score: 0.687},
  {filename: "Marketing Analytics Dashboard", score: 0.596},
  ...
]
    ↓
LLM formats response with Drive links
    ↓
Text-to-Speech
    ↓
YOU HEAR THE ANSWER
```

## Sample Files You Can Search

5 example Drive files are pre-loaded:

| File | Type | Owner | Searchable Content |
|------|------|-------|-------------------|
| Q3 2026 Budget Proposal.xlsx | Spreadsheet | Finance | Budget, financial planning, quarterly |
| July 2026 Sales Report.pdf | PDF | Sales | Sales, metrics, revenue, quarterly |
| Marketing Analytics Dashboard | Sheet | Marketing | Marketing, campaigns, analytics, data |
| Customer Contracts | Document | Legal | Contracts, agreements, templates |
| Product Roadmap 2026 | Presentation | Product | Product, roadmap, planning, quarterly |

### Example Queries That Will Work

**Direct keywords:**
- "Find the budget spreadsheet"
- "Show the sales report"

**Semantic (meaning-based, no keyword match):**
- "Show me files about financial planning" 
  → Matches Budget file even though keyword "financial" isn't in name
- "Find documents about company direction"
  → Matches Product Roadmap even though keyword doesn't match
- "Analytics and performance data"
  → Matches Marketing Dashboard even though exact keywords don't match

## If Something Goes Wrong

### "Docker not running"
```powershell
# Start Docker Desktop manually
# Or restart it:
docker restart
```

### "Port 8090 in use"
```powershell
# Stop any previous instance
docker compose down

# Then run startup again
python start_system.py
```

### "Database not connecting"
```powershell
# Check status
docker compose ps

# Should show:
# NAME      STATUS
# db        Up (healthy)
# globus    Up

# If db shows unhealthy, restart it:
docker compose restart db
```

### "No search results"
1. Wait 30 seconds (indexes still building)
2. Refresh the browser page
3. Try a simpler query first (e.g., "budget")

## Monitoring the System

### Watch live logs:
```powershell
docker compose logs -f globus
```

### Check if search is working:
```powershell
# Run the standalone demo
python demo_drive_rag.py
```

### Full system test:
```powershell
python run_drive_rag.py
```

## Stop When Done

```powershell
# Press Ctrl+C in the terminal where start_system.py is running

# Or in a separate terminal:
docker compose down

# Full cleanup (removes data):
docker compose down -v
```

## What's Actually Happening

### When you speak "Find spreadsheets about budget":

1. **Transcription:** "Find spreadsheets about budget"

2. **LLM Reasoning:**
   ```
   User wants to find spreadsheets related to budgets.
   This is a Drive search task. I should call search_drive_semantic.
   Query: "spreadsheets about budget"
   ```

3. **Tool Call:**
   ```
   search_drive_semantic(
     email="test@example.com",
     query="spreadsheets about budget",
     limit=10
   )
   ```

4. **Inside Drive RAG:**
   ```
   - Embed query: "spreadsheets about budget" → 768-dim vector
   - Search FAISS index against all files
   - Find top 10 matches by semantic similarity
   - Return with metadata (filename, owner, type, Drive link)
   ```

5. **Results Ranked by Relevance:**
   ```
   1. Q3 2026 Budget Proposal.xlsx (68.7% match)
   2. Marketing Analytics Dashboard (59.6% match)
   3. Customer Contracts (55.9% match)
   ...
   ```

6. **LLM Response:**
   ```
   "I found 5 spreadsheets related to your query about budgets. 
    The most relevant is 'Q3 2026 Budget Proposal.xlsx' owned by 
    the Finance Team. Would you like me to read it?"
   ```

7. **Text-to-Speech:** Reads response aloud

## Key Features Being Demonstrated

### ✅ Voice Integration
- Speech recognition (Browser Web Audio API)
- Text-to-speech (Browser TTS or Globus voice)

### ✅ Semantic Search (Not Keyword-Based)
- Uses Gemini embeddings for semantic understanding
- FAISS for fast vector similarity search
- Returns results by meaning, not keywords

### ✅ Tool Integration
- LLM knows when to call `search_drive_semantic`
- Orchestrator properly dispatches the tool
- Results properly formatted for LLM consumption

### ✅ User-Aware
- Searches only this user's files
- Respects file ownership
- Each user gets their own indexes

### ✅ Metadata Integration
- File names, types, owners
- Modified dates
- Direct Drive links in results
- Similarity scores

## Next: Production Deployment

Once you've tested and it works:

1. **Build real indexes** with your actual Drive:
   ```bash
   python scripts/build_drive_index.py your@email.com
   ```

2. **Set up nightly rebuilds** (cron):
   ```bash
   # Runs after Drive sync completes
   15 3 * * *  cd /opt/globus && python scripts/build_drive_index.py "*"
   ```

3. **Add email search** (same architecture):
   - Create `email_index.py` (copy from `drive_index.py`)
   - Implement `search_email_semantic` tool
   - Wire into orchestrator

4. **Deploy to production:**
   - See `RUN_DRIVE_RAG.md` for full guide

## Summary

**To see it working right now:**

```powershell
# 1. Make sure Docker Desktop is running (Start Menu → Docker)

# 2. Navigate to Globus folder
cd C:\Users\GLB-BLR-307\Documents\globus

# 3. Run the startup script
python start_system.py

# 4. Browser opens to http://localhost:8090/chat

# 5. Click microphone and say:
#    "Find spreadsheets about Q3 budget"

# 6. Watch the magic happen!
```

**Estimated time:** 2 minutes total
**Result:** Full end-to-end Drive RAG with voice working live

Enjoy! 🎙️ 📁 🤖
