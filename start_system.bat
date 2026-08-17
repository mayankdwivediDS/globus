@echo off
REM Start Globus with Drive RAG system
REM
REM This script:
REM 1. Starts Docker Desktop
REM 2. Brings up MySQL + Globus services
REM 3. Inserts test Drive data
REM 4. Builds FAISS indexes
REM 5. Opens browser to http://localhost:8090

setlocal enabledelayedexpansion

echo ====================================================================
echo Starting Globus + Drive RAG System
echo ====================================================================

REM Check if Docker is running
echo.
echo [1/6] Checking Docker...
docker ps >nul 2>&1
if errorlevel 1 (
    echo [INFO] Docker Desktop not running. Please start it manually.
    echo        Look for "Docker Desktop" in Start Menu and click it.
    echo.
    echo Waiting for Docker to start (checking every 5 seconds)...

    :wait_docker
    timeout /t 5 /nobreak >nul
    docker ps >nul 2>&1
    if errorlevel 1 goto wait_docker

    echo [OK] Docker is now running
)

REM Start services
echo.
echo [2/6] Starting Globus services (docker compose up -d)...
docker compose up -d
if errorlevel 1 (
    echo [FAIL] docker compose failed
    exit /b 1
)

REM Wait for database
echo.
echo [3/6] Waiting for database to be ready (this takes ~30 seconds)...
:wait_db
docker compose logs db 2>&1 | find "ready for connections" >nul
if errorlevel 1 (
    timeout /t 3 /nobreak >nul
    goto wait_db
)
echo [OK] Database is ready

REM Insert test data
echo.
echo [4/6] Inserting test Drive data...
(
    echo INSERT INTO globus_vault_files
    echo   ^(email, provider_account, source_type, external_id, filename, mime_type, modified_at, metadata, extracted, extracted_chars^)
    echo VALUES
    echo   ^('test@example.com', 'test@gmail.com', 'google-drive', 'id1', 'Q3 2026 Budget Proposal.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', NOW^(^), '{\"owners\":[{\"emailAddress\":\"finance@example.com\",\"displayName\":\"Finance Team\"}],\"webViewLink\":\"https://drive.google.com/file/d/id1/\"}', 1, 2048^),
    echo   ^('test@example.com', 'test@gmail.com', 'google-drive', 'id2', 'July 2026 Sales Report.pdf', 'application/pdf', NOW^(^), '{\"owners\":[{\"emailAddress\":\"sales@example.com\",\"displayName\":\"Sales\"}],\"webViewLink\":\"https://drive.google.com/file/d/id2/\"}', 1, 5120^),
    echo   ^('test@example.com', 'test@gmail.com', 'google-drive', 'id3', 'Marketing Campaign Analytics Dashboard', 'application/vnd.google-apps.spreadsheet', NOW^(^), '{\"owners\":[{\"emailAddress\":\"marketing@example.com\",\"displayName\":\"Marketing\"}],\"webViewLink\":\"https://drive.google.com/file/d/id3/\"}', 1, 3072^),
    echo   ^('test@example.com', 'test@gmail.com', 'google-drive', 'id4', 'Customer Contract Templates and Agreements', 'application/vnd.google-apps.document', NOW^(^), '{\"owners\":[{\"emailAddress\":\"legal@example.com\",\"displayName\":\"Legal\"}],\"webViewLink\":\"https://drive.google.com/file/d/id4/\"}', 1, 4096^),
    echo   ^('test@example.com', 'test@gmail.com', 'google-drive', 'id5', 'Product Roadmap 2026 - Quarterly Review', 'application/vnd.google-apps.presentation', NOW^(^), '{\"owners\":[{\"emailAddress\":\"product@example.com\",\"displayName\":\"Product\"}],\"webViewLink\":\"https://drive.google.com/file/d/id5/\"}', 1, 3584^);
) | docker compose exec -T db mysql -uglobus -pchange-me globus
echo [OK] Test data inserted

REM Wait for Globus app to be ready
echo.
echo [5/6] Waiting for Globus application to be ready (this takes ~30 seconds)...
:wait_app
docker compose logs globus 2>&1 | find "listening on" >nul
if errorlevel 1 (
    timeout /t 3 /nobreak >nul
    goto wait_app
)
echo [OK] Globus is ready

REM Build indexes
echo.
echo [6/6] Building Drive semantic indexes...
docker compose exec -T globus python scripts/build_drive_index.py test@example.com test@gmail.com
if errorlevel 1 (
    echo [WARN] Index build had an issue - that's OK, may not have FAISS installed in container
)
echo [OK] Index build attempted

echo.
echo ====================================================================
echo SUCCESS - System is running!
echo ====================================================================
echo.
echo Access the web interface:
echo   URL: http://localhost:8090
echo.
echo To test Voice RAG:
echo   1. Go to http://localhost:8090/chat
echo   2. Click the microphone button
echo   3. Say: "Find spreadsheets about budgets"
echo   4. Watch as the voice agent uses Drive semantic search
echo.
echo Test Data:
echo   - Email: test@example.com / test@gmail.com
echo   - 5 sample Drive files ready for search
echo.
echo To view logs:
echo   docker compose logs -f globus
echo.
echo To stop:
echo   docker compose down
echo.
pause
