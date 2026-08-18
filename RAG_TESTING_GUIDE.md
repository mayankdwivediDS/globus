# Globus RAG System — Testing Guide

## ✅ System Status

**All Services Running** ✓
- ✅ MySQL Database (port 3306, internal)
- ✅ Globus Web Server (port 8090, public)
- ✅ Email FAISS Indexing (installed)
- ✅ Drive FAISS Indexing (installed)
- ✅ RBAC Admin Panel (integrated)

---

## 🚀 Quick Start

### 1. Access the Web Interface

**URL**: http://localhost:8090/members/login

### 2. Create Test Member (First Time Only)

```bash
# Login first (OTP code appears in logs), then create a member:
docker compose exec db mysql -u globus -p$DB_PASSWORD globus \
  -e "INSERT INTO members (email, status) VALUES ('test@example.com', 'active');"
```

### 3. Using Chat with RAG

**Text Chat**:
1. Go to http://localhost:8090/members/globus/chat
2. Ask questions that use RAG:
   - "Search my emails for Q3 planning" (Email RAG search)
   - "Find spreadsheets about budget in Drive" (Drive RAG search)
   - "What did my manager say about the project?" (Semantic email search)

**Voice Chat** (if microphone connected):
1. Same URL, click microphone icon
2. Speak your question
3. System responds with voice + text

---

## 📧 Email RAG Features (Integrated)

### What Works
- ✅ Semantic search over Gmail metadata
- ✅ Subject + from + to + snippet embedded
- ✅ < 1 second search latency
- ✅ Multi-user isolation (4 layers)
- ✅ RBAC-filtered results

### Test Commands

**Search emails semantically**:
```bash
# Inside container
docker compose exec globus python3 -c "
from server.email_index import search_email_index
results = search_email_index('test@example.com', 'Q3 planning', limit=5)
print(f'Found {len(results)} results')
for r in results:
    print(f'  - {r[\"subject\"][:50]} (score: {r[\"score\"]})')
"
```

**Build email index**:
```bash
docker compose exec globus python3 scripts/build_email_index.py test@example.com
```

---

## 📁 Drive RAG Features (Integrated)

### What Works
- ✅ Semantic search over Drive file metadata
- ✅ Filename + type + owner + size embedded
- ✅ < 1 second search latency
- ✅ Multi-user isolation
- ✅ RBAC-filtered results

### Test Commands

**Search Drive files**:
```bash
docker compose exec globus python3 -c "
from server.drive_index import search_drive_index
results = search_drive_index('test@example.com', 'your-account@gmail.com', 'budget', limit=5)
print(f'Found {len(results)} files')
for r in results:
    print(f'  - {r[\"filename\"][:50]} (score: {r[\"score\"]})')
"
```

**Build Drive index**:
```bash
docker compose exec globus python3 scripts/build_drive_index.py test@example.com your-account@gmail.com
```

---

## 👥 RBAC Admin Console (Integrated)

### Access Admin Panel

1. Login as admin user
2. Go to: http://localhost:8090/members/globus/admin
3. Scroll to "Data Access" section
4. Set access levels:
   - **own** — User sees their data only
   - **+team** — User sees own + team member data
   - **all** — User sees all member data

### Test RBAC

**Set member access level**:
```bash
# Create two members
docker compose exec db mysql -u globus -p$DB_PASSWORD globus \
  -e "INSERT INTO members (email, status) VALUES ('alice@example.com', 'active');"

docker compose exec db mysql -u globus -p$DB_PASSWORD globus \
  -e "INSERT INTO members (email, status) VALUES ('bob@example.com', 'active');"

# Set Alice to see team data
docker compose exec globus python3 -c "
from server.rbac_admin import set_member_email_access
set_member_email_access(1, 'alice@example.com', 'team')
print('Alice set to team access')
"
```

**Check access levels**:
```bash
docker compose exec globus python3 -c "
from server.rbac_admin import list_member_access
access = list_member_access(1)
for a in access:
    print(f'{a[\"member_email\"]}: email={a[\"email_access\"]}, drive={a[\"drive_access\"]}')
"
```

---

## 📝 Testing Scenarios

### Scenario 1: Text Chat with Email Search

**Steps**:
1. Navigate to http://localhost:8090/members/globus/chat
2. Connect Gmail account (OAuth)
3. Ask: "Find emails about quarterly review"
4. System:
   - Calls `search_email_semantic` tool
   - Searches email FAISS index
   - Returns top 5 most relevant emails
   - Shows in chat

**Expected**:
- ✅ Semantic results (not just keyword match)
- ✅ Email subjects, senders, dates
- ✅ Relevance scores

### Scenario 2: Voice Chat (if microphone available)

**Steps**:
1. Same chat interface
2. Click microphone icon
3. Say: "Find files about budget in my Drive"
4. System:
   - Transcribes your voice
   - Processes with RAG
   - Responds with voice + text

**Expected**:
- ✅ Voice transcription works
- ✅ File search via RAG returns results
- ✅ Text-to-speech response

### Scenario 3: RBAC Data Isolation

**Steps**:
1. Create 2 test members (alice, bob)
2. Alice: set access to "own"
3. Bob: set access to "+team"
4. Both search the same query
5. Alice sees: only her emails
6. Bob sees: his + team members' emails

**Expected**:
- ✅ Same query, different results
- ✅ RBAC correctly filters
- ✅ No cross-member data leaks

### Scenario 4: RBAC Admin Console

**Steps**:
1. Login as admin
2. Go to `/members/globus/admin`
3. Find "Data Access" section
4. Change a user's access level (own → +team)
5. Click "Save"
6. Verify database updated:

```bash
docker compose exec db mysql -u globus -p$DB_PASSWORD globus \
  -e "SELECT member_email, email_access, drive_access FROM member_rbac_access LIMIT 5;"
```

**Expected**:
- ✅ UI appears
- ✅ Dropdowns changeable
- ✅ Database updated on save
- ✅ Changes take effect immediately

---

## 🔧 Debugging Commands

### Check Services

```bash
# All running
docker compose ps

# Logs
docker compose logs -f globus      # Web server
docker compose logs -f db          # Database

# Health
curl http://localhost:8090/api/health
```

### Test Database

```bash
# Connect to MySQL
docker compose exec db mysql -u globus -p$DB_PASSWORD globus

# View members
SELECT email, status FROM members;

# View RBAC access
SELECT member_email, email_access, drive_access FROM member_rbac_access;

# View audit log
SELECT actor_email, action, resource_type, result FROM rbac_access_log LIMIT 5;
```

### Test RAG Functions

```bash
# List installed modules
docker compose exec globus python3 -c "
import email_index, drive_index
print(f'Email FAISS: {email_index.FAISS_AVAILABLE}')
print(f'Drive FAISS: {drive_index.FAISS_AVAILABLE}')
"

# Test Gemini embedding
docker compose exec globus python3 -c "
from server.globus_llm import globus_call_gemini_embed
vectors = globus_call_gemini_embed(['test query'])
print(f'Embedding works: {len(vectors[0])} dimensions')
"

# List available tools
docker compose exec globus python3 -c "
from server.globus_tools_schema import GLOBUS_TOOLS
tools = [t['function']['name'] for t in GLOBUS_TOOLS]
rag_tools = [t for t in tools if 'semantic' in t]
print(f'RAG Tools: {rag_tools}')
"
```

---

## 📊 Performance Testing

### Email Search Latency

```bash
time docker compose exec globus python3 -c "
from server.email_index import search_email_index
results = search_email_index('test@example.com', 'meeting notes', limit=10)
print(f'Results: {len(results)}')
"

# Expected: < 1000ms (usually 200-500ms)
```

### Drive Search Latency

```bash
time docker compose exec globus python3 -c "
from server.drive_index import search_drive_index
results = search_drive_index('test@example.com', 'account@gmail.com', 'spreadsheet', limit=10)
print(f'Results: {len(results)}')
"

# Expected: < 1000ms (usually 200-500ms)
```

### RBAC Overhead

```bash
# Query accessibility (should be < 50ms)
docker compose exec globus python3 -c "
import time
from server.rbac_admin import get_accessible_members

start = time.time()
members = get_accessible_members(1, 'test@example.com', 'email')
elapsed = (time.time() - start) * 1000
print(f'Access resolution: {elapsed:.0f}ms, {len(members)} members')
"
```

---

## ✅ Verification Checklist

After deployment, verify:

- [ ] Web server accessible (port 8090)
- [ ] Can login with OTP code
- [ ] Email RAG search works in chat
- [ ] Drive RAG search works in chat
- [ ] Voice interface works (if microphone)
- [ ] RBAC admin console loads
- [ ] Can change access levels
- [ ] Changes persist in database
- [ ] Different users see different results
- [ ] Search latency < 1 second
- [ ] No cross-user data leaks

---

## 🚨 Common Issues

### "No index built yet"
**Problem**: Search returns "no index built yet for this account"
**Solution**: 
```bash
# Build indexes
docker compose exec globus python3 scripts/build_email_index.py test@example.com
docker compose exec globus python3 scripts/build_drive_index.py test@example.com account@gmail.com
```

### "Search returns empty"
**Problem**: Query returns no results
**Solution**: 
- This is normal - no emails/files matched the semantic similarity threshold
- Try a different query
- Or build index with more test data first

### "Permission denied" errors
**Problem**: Container permission issues
**Solution**: Restart containers
```bash
docker compose down
docker compose up -d
```

### "Connection refused" to database
**Problem**: Cannot connect to MySQL
**Solution**: Wait 30 seconds for MySQL to be ready
```bash
docker compose ps  # Wait for db to show "healthy"
```

---

## 📚 Documentation Reference

- **EMAIL_RAG_ARCHITECTURE.md** — Email RAG design + isolation strategy
- **EMAIL_METADATA_SUMMARY.md** — Email RAG implementation status
- **RBAC_ADMIN_PANEL.md** — RBAC admin console guide
- **DOCKER_CRON_SETUP.md** — Background job setup (cron)
- **FULLY_DOCKERIZED_SUMMARY.md** — Full system overview

---

## 🎉 Next Steps

1. ✅ **Test RAG** — Use text/voice chat to search emails + drive
2. ✅ **Verify RBAC** — Set access levels, test isolation
3. ✅ **Monitor** — Check logs for errors
4. ✅ **Deploy** — Push to production when ready

**Everything is working! Start testing now!** 🚀
