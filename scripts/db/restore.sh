#!/bin/bash
# scripts/db/restore.sh
# Database restore script for PostgreSQL

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Check for backup file argument
if [ -z "$1" ]; then
    echo "Usage: $0 <backup_file>"
    echo "Available backups:"
    ls -1 "$PROJECT_ROOT"/backups/*.sql* 2>/dev/null || echo "No backups found"
    exit 1
fi

BACKUP_FILE=$1
if [ ! -f "$BACKUP_FILE" ]; then
    BACKUP_FILE="$PROJECT_ROOT/backups/$BACKUP_FILE"
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "=== Restoring from: $BACKUP_FILE ==="

# Load environment variables
if [ -f "$PROJECT_ROOT/.env.local" ]; then
    source "$PROJECT_ROOT/.env.local"
elif [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
fi

# Decompress if needed
if [[ "$BACKUP_FILE" == *.gz ]]; then
    TEMP_FILE="/tmp/restore_$(basename $BACKUP_FILE .gz).sql"
    gunzip -c "$BACKUP_FILE" > "$TEMP_FILE"
    BACKUP_FILE=$TEMP_FILE
fi

# Confirm with user
echo "WARNING: This will overwrite the current database!"
echo "Database: $DATABASE_URL"
read -p "Are you sure? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Restore cancelled."
    rm -f "$TEMP_FILE" 2>/dev/null || true
    exit 0
fi

# Check if running in Docker (local dev) or external database
if echo "$DATABASE_URL" | grep -q "localhost"; then
    # Local Docker container
    CONTAINER_NAME="marketplace_postgres"
    
    if docker ps --format '{{.Names}}' | grep -q "$CONTAINER_NAME"; then
        echo "Restoring to Docker container: $CONTAINER_NAME"
        
        POSTGRES_USER=$(grep POSTGRES_USER "$PROJECT_ROOT/.env" | cut -d= -f2 || echo "marketplace")
        POSTGRES_DB=$(grep POSTGRES_DB "$PROJECT_ROOT/.env" | cut -d= -f2 || echo "marketplace_dev")
        
        # Copy backup file to container
        docker cp "$BACKUP_FILE" "$CONTAINER_NAME:/tmp/restore_backup.sql"
        
        # Drop and recreate database
        docker exec "$CONTAINER_NAME" psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS $POSTGRES_DB;"
        docker exec "$CONTAINER_NAME" psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $POSTGRES_DB;"
        
        # Restore
        docker exec "$CONTAINER_NAME" psql \
            -U "$POSTGRES_USER" \
            -d "$POSTGRES_DB" \
            -f /tmp/restore_backup.sql
        
        # Cleanup
        docker exec "$CONTAINER_NAME" rm -f /tmp/restore_backup.sql
    else
        echo "Docker container not running. Using local psql..."
        DB_URL="${DATABASE_URL/\/asyncpg/}"
        
        DB_HOST=$(echo $DB_URL | sed -n 's/.*@\([^:]*\).*/\1/p')
        DB_PORT=$(echo $DB_URL | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
        DB_NAME=$(echo $DB_URL | sed -n 's/.*\/\(.*\)/\1/p')
        DB_USER=$(echo $DB_URL | sed -n 's/.*:\/\/\([^:]*\):.*/\1/p')
        DB_PASS=$(echo $DB_URL | sed -n 's/.*:\/\/[^:]*:\([^@]*\)@.*/\1/p')
        
        PGPASSWORD=$DB_PASS psql \
            -h "$DB_HOST" \
            -p "$DB_PORT" \
            -U "$DB_USER" \
            -d postgres \
            -c "DROP DATABASE IF EXISTS $DB_NAME;"
        
        PGPASSWORD=$DB_PASS psql \
            -h "$DB_HOST" \
            -p "$DB_PORT" \
            -U "$DB_USER" \
            -d postgres \
            -c "CREATE DATABASE $DB_NAME;"
        
        PGPASSWORD=$DB_PASS psql \
            -h "$DB_HOST" \
            -p "$DB_PORT" \
            -U "$DB_USER" \
            -d "$DB_NAME" \
            -f "$BACKUP_FILE"
    fi
else
    # External database (staging/production)
    DB_URL="${DATABASE_URL/\/asyncpg/}"
    
    DB_HOST=$(echo $DB_URL | sed -n 's/.*@\([^:]*\).*/\1/p')
    DB_PORT=$(echo $DB_URL | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
    DB_NAME=$(echo $DB_URL | sed -n 's/.*\/\(.*\)/\1/p')
    DB_USER=$(echo $DB_URL | sed -n 's/.*:\/\/\([^:]*\):.*/\1/p')
    DB_PASS=$(echo $DB_URL | sed -n 's/.*:\/\/[^:]*:\([^@]*\)@.*/\1/p')
    
    # Drop and recreate database
    PGPASSWORD=$DB_PASS psql \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d postgres \
        -c "DROP DATABASE IF EXISTS \"$DB_NAME\";"
    
    PGPASSWORD=$DB_PASS psql \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d postgres \
        -c "CREATE DATABASE \"$DB_NAME\";"
    
    # Restore
    PGPASSWORD=$DB_PASS psql \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        -f "$BACKUP_FILE"
fi

# Cleanup temp file
rm -f "$TEMP_FILE" 2>/dev/null || true

echo "=== Restore complete ==="