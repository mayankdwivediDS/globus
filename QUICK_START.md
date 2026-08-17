# Quick Start - Test Drive RAG with Voice Agent

**What you'll see:** A working Globus instance with voice chat that can search Drive files semantically.

## Prerequisites

1. **Docker Desktop** installed on your machine
2. **5 minutes of setup time** (mostly waiting for services)

## Start the System

### Windows/Mac

**Option 1: Python Script (Recommended)**
```bash
python start_system.py
```

This will:
1. Start Docker (or wait for it if not running)
2. Bring up MySQL + Globus services
3. Insert 5 sample Drive files
4. Build FAISS semantic search indexes
5. Open browser to http://localhost:8090/chat

**Option 2: Batch Script**
```bash
start_system.bat
```

Same as above but using Windows batch file.

## What Happens Next

1. **Browser opens** to http://localhost:8090/chat
2. **Globus interface** shows with chat box + voice button
3. **Click microphone** and say a query, like:
   - "Find spreadsheets about budget"
   - "Show me sales reports"
   - "Files about marketing analytics"

4. **Watch the magic:**
   - Voice is transcribed to text
   - LLM processes the query
   - `search_drive_semantic` tool is called
   - FAISS index is searched
   - Top results with similarity scores returned
   - LLM formats response with clickable Drive links
   - Response is spoken back to you via TTS

## Sample Queries to Try

### Budget/Finance
- "Find spreadsheets about Q3 budget"
- "Show me financial planning documents"
- "Find files with budget in the name"

### Sales/Analytics
- "Search for sales reports and analytics"
- "Find files about marketing campaigns"
- "Show me quarterly review documents"

### Semantic Matching (No Keyword Match)
- "Find documents about planning and forecasts" 
  → Will match "Q3 Budget Proposal" even though keywords differ
- "Show me financial data and dashboard"
  → Will match both spreadsheets AND analytics presentations

## The System at a Glance

```
Your Voice
    ↓
Web Interface (Chat + Microphone)
    ↓
Speech-to-Text (Transcribed)
    ↓
LLM (Claude with Tools)
    ↓
search_drive_semantic Tool Calls
    ↓
FAISS Index (Pre-Built, On Disk)
    ↓
Gemini Embedding (Query)
    ↓
Semantic Search Results (Top 10)
    ↓
LLM Formats Response
    ↓
Text-to-Speech
    ↓
Your Speaker Hears Answer
```

## Files in This Demo

The system has 5 sample Drive files:

1. **Q3 2026 Budget Proposal.xlsx** (Spreadsheet)
   - Owned by: Finance Team
   - About: Quarterly budget planning

2. **July 2026 Sales Report.pdf** (PDF)
   - Owned by: Sales
   - About: Monthly sales metrics

3. **Marketing Campaign Analytics Dashboard** (Google Sheet)
   - Owned by: Marketing
   - About: Campaign performance data

4. **Customer Contract Templates** (Google Doc)
   - Owned by: Legal
   - About: Contract templates and agreements

5. **Product Roadmap 2026 - Quarterly Review** (Presentation)
   - Owned by: Product
   - About: Product planning and roadmap

All can be searched semantically (by meaning, not just keywords).

## Troubleshooting

### "Docker is not running"
- Open Docker Desktop from Start Menu
- Wait for whale icon to appear in system tray
- Run the script again

### "Port 8090 already in use"
```bash
# Stop any existing Globus instances
docker compose down

# Then run the script again
python start_system.py
```

### "Database connection failed"
- Wait a few more seconds (DB can be slow to start)
- Check: `docker compose ps` should show 2 healthy containers
- If not healthy, restart: `docker compose restart`

### "No results in search"
- Indexes may still be building (takes ~30 seconds)
- Refresh the page
- Try a different query with different keywords

### "Voice not working"
- Check browser microphone permissions
- Try text chat first (type your query) to verify search works
- Voice transcription is separate from search functionality

## Next Steps

### After Testing Works

1. **Build your own indexes** with real Drive data:
   ```bash
   docker compose exec globus python scripts/build_drive_index.py your@email.com
   ```

2. **Add email search** (same pattern as Drive):
   - Follow `DRIVE_RAG_STATUS.md` for implementation
   - Parallel to Drive metadata search

3. **Deploy to production:**
   - See `RUN_DRIVE_RAG.md` for full deployment guide
   - Add cron job for nightly index rebuilds

## To Stop

```bash
# Stop all services
docker compose down

# Stop and remove volumes (full cleanup)
docker compose down -v
```

## More Info

- `DRIVE_RAG_TESTED.md` - Complete test results
- `DRIVE_RAG_STATUS.md` - Technical details
- `RUN_DRIVE_RAG.md` - Production deployment
- `demo_drive_rag.py` - Standalone demo (no Docker needed)

## Support

If something goes wrong:

1. **Check logs:**
   ```bash
   docker compose logs -f globus
   ```

2. **Run the test suite:**
   ```bash
   python run_drive_rag.py
   ```

3. **Check individual components:**
   ```bash
   python test_drive_semantic.py  # FAISS + embeddings
   python demo_drive_rag.py       # Search simulation
   ```

---

**Ready to see it in action?** Run:
```bash
python start_system.py
```

Takes about 2 minutes. Then open http://localhost:8090/chat and start talking! 🎙️
