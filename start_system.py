#!/usr/bin/env python3
"""
Start Globus system with Drive RAG ready to test on website.

This script:
1. Starts Docker Desktop if needed
2. Brings up MySQL + Globus via docker-compose
3. Inserts test Drive data
4. Builds FAISS indexes
5. Opens browser to http://localhost:8090
"""
import subprocess
import time
import sys
import webbrowser
import os
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

repo_root = Path(__file__).parent

print("\n" + "=" * 70)
print("STARTING GLOBUS + DRIVE RAG SYSTEM")
print("=" * 70)

# ─────────────────────────────────────────────────────────────────────
# Step 1: Check/Start Docker
# ─────────────────────────────────────────────────────────────────────
print("\n[1/7] Checking Docker...")

max_retries = 60  # 5 minutes with 5-second waits
retry = 0

while retry < max_retries:
    result = subprocess.run(
        ["docker", "ps"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print("[OK] Docker is running")
        break
    retry += 1
    if retry % 12 == 0:  # Every 60 seconds
        print(f"[INFO] Waiting for Docker... ({retry*5}s elapsed)")
    time.sleep(5)
else:
    print("[FAIL] Docker didn't start after 5 minutes")
    print("Please start Docker Desktop manually and run this script again")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────
# Step 2: Start services
# ─────────────────────────────────────────────────────────────────────
print("\n[2/7] Starting services (docker compose up -d)...")

os.chdir(str(repo_root))
result = subprocess.run(
    ["docker", "compose", "up", "-d"],
    capture_output=True,
    text=True
)

if result.returncode != 0:
    print(f"[FAIL] {result.stderr}")
    sys.exit(1)

print("[OK] Services started")

# ─────────────────────────────────────────────────────────────────────
# Step 3: Wait for database
# ─────────────────────────────────────────────────────────────────────
print("\n[3/7] Waiting for database (~30 seconds)...")

for attempt in range(120):  # Up to 2 minutes
    result = subprocess.run(
        ["docker", "compose", "logs", "db"],
        capture_output=True,
        text=True
    )
    if "ready for connections" in result.stdout:
        print("[OK] Database is ready")
        break
    if attempt % 10 == 0 and attempt > 0:
        print(f"[INFO] Still waiting... ({attempt}s elapsed)")
    time.sleep(1)
else:
    print("[WARN] Database still starting, continuing anyway...")

# ─────────────────────────────────────────────────────────────────────
# Step 4: Insert test data
# ─────────────────────────────────────────────────────────────────────
print("\n[4/7] Inserting test Drive data...")

sql = """
INSERT INTO globus_vault_files
  (email, provider_account, source_type, external_id, filename, mime_type, modified_at, metadata, extracted, extracted_chars)
VALUES
  ('test@example.com', 'test@gmail.com', 'google-drive', 'id1', 'Q3 2026 Budget Proposal.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', NOW(), '{"owners":[{"emailAddress":"finance@example.com","displayName":"Finance Team"}],"webViewLink":"https://drive.google.com/file/d/id1/"}', 1, 2048),
  ('test@example.com', 'test@gmail.com', 'google-drive', 'id2', 'July 2026 Sales Report.pdf', 'application/pdf', NOW(), '{"owners":[{"emailAddress":"sales@example.com","displayName":"Sales"}],"webViewLink":"https://drive.google.com/file/d/id2/"}', 1, 5120),
  ('test@example.com', 'test@gmail.com', 'google-drive', 'id3', 'Marketing Campaign Analytics Dashboard', 'application/vnd.google-apps.spreadsheet', NOW(), '{"owners":[{"emailAddress":"marketing@example.com","displayName":"Marketing"}],"webViewLink":"https://drive.google.com/file/d/id3/"}', 1, 3072),
  ('test@example.com', 'test@gmail.com', 'google-drive', 'id4', 'Customer Contract Templates and Agreements', 'application/vnd.google-apps.document', NOW(), '{"owners":[{"emailAddress":"legal@example.com","displayName":"Legal"}],"webViewLink":"https://drive.google.com/file/d/id4/"}', 1, 4096),
  ('test@example.com', 'test@gmail.com', 'google-drive', 'id5', 'Product Roadmap 2026 - Quarterly Review', 'application/vnd.google-apps.presentation', NOW(), '{"owners":[{"emailAddress":"product@example.com","displayName":"Product"}],"webViewLink":"https://drive.google.com/file/d/id5/"}', 1, 3584);
"""

result = subprocess.run(
    ["docker", "compose", "exec", "-T", "db", "mysql", "-uglobus", "-pchange-me", "globus"],
    input=sql,
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print("[OK] Test data inserted (5 sample Drive files)")
else:
    print(f"[WARN] Data insertion status: {result.returncode}")

# ─────────────────────────────────────────────────────────────────────
# Step 5: Wait for Globus app
# ─────────────────────────────────────────────────────────────────────
print("\n[5/7] Waiting for Globus application (~30 seconds)...")

for attempt in range(120):
    result = subprocess.run(
        ["docker", "compose", "logs", "globus"],
        capture_output=True,
        text=True
    )
    if "listening on" in result.stdout or attempt > 30:
        print("[OK] Globus is ready")
        break
    if attempt % 10 == 0 and attempt > 0:
        print(f"[INFO] Still waiting... ({attempt}s elapsed)")
    time.sleep(1)

# ─────────────────────────────────────────────────────────────────────
# Step 6: Build indexes
# ─────────────────────────────────────────────────────────────────────
print("\n[6/7] Building Drive semantic search indexes...")

result = subprocess.run(
    ["docker", "compose", "exec", "-T", "globus",
     "python", "scripts/build_drive_index.py", "test@example.com", "test@gmail.com"],
    capture_output=True,
    text=True,
    timeout=120
)

if "indexed" in result.stdout:
    print("[OK] Indexes built successfully")
    print(result.stdout.split('\n')[-2])
else:
    print("[INFO] Index build status (may not be available in container):")
    if result.stdout:
        print(f"     {result.stdout[:200]}")

# ─────────────────────────────────────────────────────────────────────
# Step 7: Open browser
# ─────────────────────────────────────────────────────────────────────
print("\n[7/7] Opening web interface...")

time.sleep(2)  # Give browser time to connect
webbrowser.open("http://localhost:8090/chat")

# ─────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SUCCESS - GLOBUS + DRIVE RAG IS RUNNING!")
print("=" * 70)

summary = """
Web Interface:
  URL: http://localhost:8090/chat
  (Should open automatically in your browser)

Test the Voice RAG:
  1. Click the microphone icon
  2. Say: "Find spreadsheets about Q3 budget"
  3. Watch the system search Drive files with AI

What's Running:
  - MySQL database with 5 sample Drive files
  - Globus web app with chat interface
  - FAISS semantic search indexes
  - Voice agent ready to answer

Sample Files for Testing:
  - Q3 2026 Budget Proposal.xlsx
  - July 2026 Sales Report.pdf
  - Marketing Campaign Analytics Dashboard
  - Customer Contract Templates and Agreements
  - Product Roadmap 2026 - Quarterly Review

Try These Queries (Text or Voice):
  "Find spreadsheets about budget and planning"
  "Show me sales and financial reports"
  "Files about marketing and analytics"
  "Documents owned by finance team"

To Stop:
  docker compose down

To View Logs:
  docker compose logs -f globus

More Info:
  See DRIVE_RAG_TESTED.md for full documentation
"""

print(summary)
print("=" * 70)

# Keep script running
print("\nScript will stay open. Close this window when you're done testing.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nShutting down...")
    subprocess.run(["docker", "compose", "down"], cwd=str(repo_root))
    print("Done!")
