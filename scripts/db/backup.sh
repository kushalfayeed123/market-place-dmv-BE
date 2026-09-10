#!/bin/bash
# scripts/db/backup.sh
# Database backup script for PostgreSQL

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Load environment variables
if [ -f "$PROJECT_ROOT/.env.local" ]; then
    source "$PROJECT_ROOT/.env.local"
elif [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
fi

# Create backups directory
mkdir -p "$PROJECT_ROOT/backups"

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Determine environment
if [ "$ENVIRONMENT" = "production" ]; then
    BACKUP_FILE="$PROJECT_ROOT/backups/prod_backup_${TIMESTAMP}.sql"
elif [ "$ENVIRONMENT" = "staging" ]; then
    BACKUP_FILE="$PROJECT_ROOT/backups/staging_backup_${TIMESTAMP}.sql"
else
    BACKUP_FILE="$PROJECT_ROOT/backups/dev_backup_${TIMESTAMP}.sql"
fi

echo "=== Creating backup: $BACKUP_FILE ==="

# Check if running in Docker (local dev) or external database
if echo "$DATABASE_URL" | grep -q "localhost"; then
    # Local Docker container
    CONTAINER_NAME="marketplace_postgres"
    
    if docker ps --format '{{.Names}}' | grep -q "$CONTAINER_NAME"; then
        echo "Backing up from Docker container: $CONTAINER_NAME"
        
        POSTGRES_USER=$(grep POSTGRES_USER "$PROJECT_ROOT/.env" | cut -d= -f2 || echo "marketplace")
        POSTGRES_DB=$(grep POSTGRES_DB "$PROJECT_ROOT/.env" | cut -d= -f2 || echo "marketplace_dev")
        
        docker exec "$CONTAINER_NAME" pg_dump \
            -U "$POSTGRES_USER" \
            -d "$POSTGRES_DB" \
            --format=plain \
            --no-owner \
            --no-acl \
            > "$BACKUP_FILE"
    else
        echo "Docker container not running. Using local psql..."
        PGPASSWORD=$(echo "$DATABASE_URL" | sed -n 's/.*:\/\/[^:]*:\([^@]*\)@.*/\1/p') \
        pg_dump \
            -h $(echo "$DATABASE_URL" | sed -n 's/.*@\([^:]*\).*/\1/p') \
            -p $(echo "$DATABASE_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p') \
            -U $(echo "$DATABASE_URL" | sed -n 's/.*:\/\/\([^:]*\):.*/\1/p') \
            -d $(echo "$DATABASE_URL" | sed -n 's/.*\/\(.*\)/\1/p') \
            --format=plain \
            --no-owner \
            --no-acl \
            > "$BACKUP_FILE"
    fi
else
    # External database (staging/production)
    DB_URL="${DATABASE_URL/\/asyncpg/}"
    
    # Extract connection details
    DB_HOST=$(echo $DB_URL | sed -n 's/.*@\([^:]*\).*/\1/p')
    DB_PORT=$(echo $DB_URL | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
    DB_NAME=$(echo $DB_URL | sed -n 's/.*\/\(.*\)/\1/p')
    DB_USER=$(echo $DB_URL | sed -n 's/.*:\/\/\([^:]*\):.*/\1/p')
    DB_PASS=$(echo $DB_URL | sed -n 's/.*:\/\/[^:]*:\([^@]*\)@.*/\1/p')
    
    PGPASSWORD=$DB_PASS pg_dump \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --format=plain \
        --no-owner \
        --no-acl \
        > "$BACKUP_FILE"
fi

# Compress the backup
gzip "$BACKUP_FILE"
echo "Backup created and compressed: ${BACKUP_FILE}.gz"

# Show backup size
ls -lh "${BACKUP_FILE}.gz"

# Clean up old backups (keep last 7)
echo "Cleaning up old backups..."
ls -t "$PROJECT_ROOT"/backups/*.gz 2>/dev/null | tail -n +8 | xargs -r rm --
echo "=== Backup complete ==="