-- =============================================================================
-- scripts/db/init_mysql.sql
-- One-time setup for local MySQL development.
--
-- Run as the MySQL root user (or any privileged user) ONCE:
--   "C:\Program Files\MySQL\MySQL Server 9.3\bin\mysql.exe" -u root -p < scripts/db/init_mysql.sql
--
-- This creates the application database and a dedicated least-privilege user.
-- Adjust POSTGRES_* names below if you used different values in your .env.
-- =============================================================================

-- Application database (utf8mb4 for full Unicode / emoji support)
CREATE DATABASE IF NOT EXISTS marketplace_dev
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- Dedicated application user (NOT root) so the app never uses the admin account
CREATE USER IF NOT EXISTS 'marketplace'@'localhost' IDENTIFIED BY 'marketplace';
CREATE USER IF NOT EXISTS 'marketplace'@'127.0.0.1' IDENTIFIED BY 'marketplace';

-- Grant access only to the application schema
GRANT ALL PRIVILEGES ON marketplace_dev.* TO 'marketplace'@'localhost';
GRANT ALL PRIVILEGES ON marketplace_dev.* TO 'marketplace'@'127.0.0.1';

-- Apply privilege changes
FLUSH PRIVILEGES;

-- Sanity check output
SELECT 'Database and user created successfully' AS status;