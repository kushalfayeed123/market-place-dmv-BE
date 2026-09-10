-- =============================================================================
-- Database Initialization Script
-- Runs automatically when PostgreSQL container starts for the first time
-- =============================================================================

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Set timezone
SET timezone = 'UTC';

-- Log initialization
DO $$
BEGIN
    RAISE NOTICE 'Database initialized successfully';
END
$$;
