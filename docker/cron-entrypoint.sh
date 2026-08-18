#!/bin/bash
# Globus cron service entrypoint — runs sync + index rebuild jobs inside Docker.
#
# This container runs in the background and executes scheduled jobs:
# - Hourly: Incremental Gmail/Drive sync
# - Daily: Deep Gmail/Drive sync (7-day lookback)
# - Weekly: Full FAISS index rebuild for all members
#
# Jobs are defined in docker/crontab and run via `cron -f` in foreground
# (required for Docker to receive signals + graceful shutdown).

set -e

# Wait for MySQL to be ready before starting cron
wait_for_db() {
    echo "[cron] Waiting for MySQL at $DB_HOST:$DB_PORT..."
    max_attempts=30
    attempt=1
    while [ $attempt -le $max_attempts ]; do
        if mysqladmin ping -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -p"$DB_PASSWORD" --ssl-mode=DISABLE --silent 2>/dev/null; then
            echo "[cron] MySQL is ready!"
            return 0
        fi
        echo "[cron] Attempt $attempt/$max_attempts failed, retrying in 2s..."
        sleep 2
        attempt=$((attempt + 1))
    done
    echo "[cron] MySQL did not become ready after $max_attempts attempts"
    return 1
}

# Load .env file if it exists (for local development)
if [ -f /app/.env ]; then
    set -a
    source /app/.env
    set +a
fi

# Export env vars so cron jobs can access them
export DB_HOST="${DB_HOST:-db}"
export DB_PORT="${DB_PORT:-3306}"
export DB_USER="${DB_USER:-globus}"
export DB_PASSWORD="${DB_PASSWORD:-}"
export DB_NAME="${DB_NAME:-globus}"
export GLOBUS_FAISS_INDEX_DIR="${GLOBUS_FAISS_INDEX_DIR:-/app/local_data/faiss-index}"
export GLOBUS_METADATA_DIR="${GLOBUS_METADATA_DIR:-/app/local_data/drive-metadata}"
export PYTHONPATH="${PYTHONPATH:-/app}"

# Create log directory
mkdir -p /var/log/globus
touch /var/log/globus/sync.log
touch /var/log/globus/index.log

echo "[cron] Globus cron service starting"
echo "[cron] DB_HOST: $DB_HOST"
echo "[cron] DB_PORT: $DB_PORT"
echo "[cron] GLOBUS_FAISS_INDEX_DIR: $GLOBUS_FAISS_INDEX_DIR"

# Start cron in foreground (cron jobs will handle database connection retries)
echo "[cron] Starting cron daemon (jobs will retry on database errors)..."
exec cron -f -l 2
