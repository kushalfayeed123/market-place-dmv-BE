# Database Migration Runbook (Alembic, any provider)

For the marketplace backend (FastAPI + SQLAlchemy + Alembic, asyncmy driver). Written after the `share_links` migration so the next one is a single command.

## 1. The one-command way

The script `backend\scripts\migrate.ps1` does the whole safe sequence: read target, back up, check revision, preview SQL, confirm, apply, verify.

```powershell
cd C:\sandbox\market-place\backend
.\scripts\migrate.ps1 prod -DryRun     # preview only, nothing applied
.\scripts\migrate.ps1 prod             # full run
.\scripts\migrate.ps1 local -SkipBackup
```

If PowerShell blocks the script: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`.

**Where the script gets the database URL (first match wins):**

1. Environment variable `MIGRATE_URL_<TARGET>`, for example `MIGRATE_URL_PROD`.
2. File `backend\.migrate\<target>.url`, one line containing the URL. Add `.migrate/` and `backups/` to `.gitignore`.
3. A hidden prompt. Nothing is stored.

URL shape: `mysql://user:password@host:port/dbname` (or `postgres://...`). The script converts it to the async driver form (`mysql+asyncmy`, `postgresql+asyncpg`) and masks nothing on screen except the password. Passwords with special characters can be pasted raw or percent-encoded.

**What the script refuses to do:**

- Continue if it cannot connect (wrong password, TLS, IP allow-list). Nothing is changed.
- Continue if the database has no Alembic revision (built without Alembic), or if there are several Alembic heads.
- Apply if the backup file is missing, tiny or incomplete.
- Apply destructive SQL (`DROP`, `TRUNCATE`, `DELETE`, `MODIFY`...) without you typing `YES`. The `-Yes` flag never bypasses this.
- Apply to a non-local database unless you type the database name.

Backups land in `backend\backups\<target>_<db>_<timestamp>.sql`.

## 2. One-time setup per project

1. Copy `migrate.ps1` to `backend\scripts\`.
2. Add to `.gitignore`: `.migrate/` and `backups/`.
3. Make `alembic/env.py` accept TLS (needed for most managed databases). Add this and pass `connect_args=_connect_args()` to the `async_engine_from_config(...)` call:

```python
import os, ssl

def _connect_args():
    if os.getenv("DB_SSL") != "1":
        return {}
    ca = os.getenv("DB_SSL_CA")
    ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
    if not ca:  # encrypted but not certificate-verified; pass -SslCa for full verification
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return {"ssl": ctx}
```

4. Make sure `env.py` reads the same environment variable the script sets (`DATABASE_URL` by default; change with `-UrlVar`).
5. Install the DB client tools (`mysqldump` or `pg_dump`) so the backup step works. The script also searches the usual Windows install folders.

## 3. Changing database provider

Only the URL changes. Checklist:

1. Get the new connection URL from the provider.
2. Update `.migrate\prod.url` (or `MIGRATE_URL_PROD`) and the host's environment variable (Render etc.).
3. If the provider gives a CA certificate, download it and add `-SslCa path\to\ca.pem`.
4. Allow your IP in the provider's allow-list if it has one.
5. Moving data between providers: dump from the old, restore into the new, then run `alembic current`. It must print the revision you expect. If it prints nothing, stamp the correct revision before any upgrade.
6. Run `.\scripts\migrate.ps1 prod -DryRun` to confirm the connection works before a real migration.

If you switch between MySQL and PostgreSQL, also check the migrations themselves. Types such as `CHAR(32)` UUIDs and `server_default` expressions differ between the engines.

## 4. Creating a migration (every time)

```powershell
alembic revision --autogenerate -m "short description"
```

Then **edit the generated file before applying it**. Keep only what you intended.

- Delete unrelated drift: dropped foreign keys, `CHAR(36)` to `Uuid()` type changes, expression-index changes (`created_at DESC`), comment-only changes.
- Check each new table's columns and foreign key types match the referenced columns.
- MySQL rejects literal defaults on TEXT/JSON columns. Use the expression form: `server_default=sa.text("('[]')")`.
- Remove duplicate unique constraints (`unique=True` plus a named `UniqueConstraint` produces two).
- Fix the model too, so the same noise doesn't reappear next time.
- Run locally first: `.\scripts\migrate.ps1 local -SkipBackup`.
- Commit the migration file before deploying.

Autogenerate needs the model imported in `alembic/env.py`. If the generated `upgrade()` is empty, that import is missing.

## 5. Manual fallback (if the script cannot be used)

```powershell
# 1. Backup (add --ssl-mode=REQUIRED for managed servers)
mysqldump -h <host> -P <port> -u <user> -p --single-transaction --triggers --set-gtid-purged=OFF <db> --result-file=backup.sql
Get-Content backup.sql -Tail 3     # must show: Dump completed

# 2. Point Alembic at the target (single quotes protect special characters)
$env:DATABASE_URL = 'mysql+asyncmy://user:pass@host:port/db'
alembic current                    # must show the revision you expect

# 3. Preview only the new revisions
alembic upgrade <current_rev>:<head_rev> --sql

# 4. Apply and verify
alembic upgrade head
alembic current
```

Use `--result-file` for dumps. PowerShell's `>` redirect writes UTF-16 and corrupts the file.

## 6. Order of operations for a release

1. Back up.
2. Run the migration against production.
3. Deploy the new backend code.

A new table or nullable column is backward compatible, so old code keeps working between steps 2 and 3. Deploying code first causes errors such as 1146 (table doesn't exist). For destructive changes (dropping or renaming columns), ship in two releases instead.

## 7. Troubleshooting (errors met so far)

| Error | Meaning | Fix |
| --- | --- | --- |
| `1146 Table 'x' doesn't exist` | The model exists, the table doesn't | Check that a migration creates it and has been applied to the database the app actually uses |
| `alembic current` shows head but the table is missing | The database was stamped without running the migrations, or the migration was never generated | `grep` the versions folder for the table. If no file creates it, autogenerate one |
| `1044 Access denied ... to database` | The user has no privileges on that database | `CREATE USER IF NOT EXISTS` first (MySQL 8+ no longer creates users via `GRANT`), then `GRANT ALL ON db.*`. Do it for both `localhost` and `127.0.0.1` accounts |
| `1410 You are not allowed to create a user with GRANT` | The account doesn't exist yet | `CREATE USER` first, then `GRANT` |
| `1045 Access denied for user ... (using password: YES)` | Wrong password, or PowerShell/URL mangled it | Test with the `mysql` client. Use single quotes. Percent-encode special characters. Rotated password not updated |
| `No module named 'MySQLdb'` | URL scheme is plain `mysql://` | Use `mysql+asyncmy://` (the script does this for you) |
| `mysql` is not recognized | Client not on PATH | Use the full path, e.g. `C:\Program Files\MySQL\MySQL Server 9.3\bin\mysql.exe` |
| `NoInspectionAvailable ... MockConnection` on `--sql` | An old migration uses `sa.inspect()`, which can't run offline | Preview only the new range: `alembic upgrade <cur>:<head> --sql` |
| `mysqldump ... Unknown table 'LIBRARIES'` | MySQL 9.x client against an 8.0 server, with `--routines` | Drop `--routines` or use a matching client or the provider's backup |
| GTID warning from `mysqldump` | Server uses GTIDs | Add `--set-gtid-purged=OFF` |
| Windows: multiple modules differing in casing (Next.js) | Folder opened under two casings | Always `cd` into the folder with the exact on-disk casing |

## 8. Security

- Never paste database passwords into chats, commits or docs. If one leaks, rotate it in the provider console and update the host's environment variables.
- Keep `.migrate/` and `backups/` out of git. Backups contain real user data.
- Don't leave the production URL in a long-lived terminal. The script restores your environment variables when it finishes.
- Prefer a dedicated migration user with only the privileges it needs, instead of the provider's admin account, once the project grows.
