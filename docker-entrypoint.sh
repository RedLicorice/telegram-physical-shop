#!/bin/bash
set -e

# This entrypoint script fixes permission issues with mounted volumes
# It runs as root initially to fix permissions, then switches to botuser

echo "Fixing permissions for mounted volumes..."

# Ensure directories exist
mkdir -p /app/logs /app/data

# Fix ownership of logs and data directories
# This is necessary because mounted volumes inherit host permissions
chown -R botuser:botuser /app/logs /app/data

echo "Permissions fixed. Starting application as botuser..."

# Switch to botuser and execute the main command
# We don't use 'exec' so we can catch the exit code and delay the restart on crash
set +e
gosu botuser "$@"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "=================================================================="
    echo "❌ ERROR: Bot application crashed with exit code $EXIT_CODE."
    echo "⏳ Waiting 120 seconds before allowing Docker to restart..."
    echo "=================================================================="
    sleep 120
fi

exit $EXIT_CODE
