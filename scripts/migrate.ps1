<#
.SYNOPSIS
  One-command, provider-agnostic Alembic migration runner:
  read target -> backup -> check revision -> preview SQL -> confirm -> apply -> verify.

.DESCRIPTION
  Save as backend\scripts\migrate.ps1. Works with any MySQL/MariaDB or PostgreSQL
  host (Aiven, Render, RDS, DigitalOcean, local...). Only the connection URL changes.

  Where the URL comes from (first match wins):
    1. env var MIGRATE_URL_<TARGET>   e.g. MIGRATE_URL_PROD
    2. file   backend\.migrate\<target>.url   (gitignored, one line: the URL)
    3. a hidden prompt (nothing is stored)

.EXAMPLE
  .\scripts\migrate.ps1 prod -DryRun     # everything except the final upgrade
  .\scripts\migrate.ps1 prod             # full run
  .\scripts\migrate.ps1 local -SkipBackup
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Target,
    [string]$BackendDir = (Split-Path -Parent $PSScriptRoot),
    [string]$UrlVar = "DATABASE_URL",   # env var your alembic/env.py reads
    [string]$Driver = "",               # override, e.g. mysql+asyncmy
    [string]$SslCa = "",                # optional CA certificate path
    [string]$BackupDir = "",
    [switch]$NoSsl,
    [switch]$DryRun,
    [switch]$SkipBackup,
    [switch]$Yes                        # skips prompts, but never skips the destructive-SQL stop
)

$ErrorActionPreference = "Continue"
$exitCode = 0

function Step([string]$m) { Write-Host "`n==> $m" -ForegroundColor Cyan }

function Get-TargetUrl([string]$t) {
    $v = [Environment]::GetEnvironmentVariable("MIGRATE_URL_" + $t.ToUpper())
    if ($v) { return $v }
    $f = Join-Path $BackendDir ".migrate\$t.url"
    if (Test-Path $f) { return (Get-Content $f -Raw) }
    $sec = Read-Host "Database URL for '$t' (input hidden)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Parse-DbUrl([string]$u) {
    $u = $u -replace '^\s*[A-Za-z_][A-Za-z0-9_]*=', ''
    $u = $u.Trim().Trim('"').Trim("'")
    $rx = '^(?<scheme>[A-Za-z0-9+]+)://(?<user>[^:@/]+):(?<pw>.*)@(?<host>[^@:/?]+)(:(?<port>\d+))?/(?<db>[^?]+)(\?(?<q>.*))?$'
    if (-not ($u -match $rx)) { throw "Could not parse the URL. Expected scheme://user:password@host:port/dbname" }
    $m = $Matches
    $scheme = $m['scheme'].ToLower()
    if ($scheme -match '^(mysql|mariadb)') { $engine = 'mysql'; $defPort = '3306' }
    elseif ($scheme -match '^postgres') { $engine = 'postgres'; $defPort = '5432' }
    else { throw "Unsupported scheme '$scheme' (supported: mysql, mariadb, postgres)." }

    $port = $m['port']; if (-not $port) { $port = $defPort }
    $pw = [uri]::UnescapeDataString($m['pw'])
    $drv = $Driver
    if (-not $drv) {
        if ($scheme -like '*+*') { $drv = $scheme }
        elseif ($engine -eq 'mysql') { $drv = 'mysql+asyncmy' }
        else { $drv = 'postgresql+asyncpg' }
    }
    $isLocal = $m['host'] -match '^(localhost|127\.0\.0\.1|::1)$'
    $tls = (-not $NoSsl) -and ((-not $isLocal) -or ($m['q'] -match 'ssl'))

    [pscustomobject]@{
        Engine = $engine; Host = $m['host']; Port = $port; User = $m['user']
        Password = $pw; Name = $m['db']; Tls = $tls; IsLocal = $isLocal
        Url = ("{0}://{1}:{2}@{3}:{4}/{5}" -f $drv, $m['user'], [uri]::EscapeDataString($pw), $m['host'], $port, $m['db'])
    }
}

function Find-Tool([string]$name) {
    $c = Get-Command $name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $globs = @(
        "C:\Program Files\MySQL\*\bin\$name.exe",
        "C:\Program Files\PostgreSQL\*\bin\$name.exe",
        "C:\Program Files\MariaDB*\bin\$name.exe",
        "C:\xampp\mysql\bin\$name.exe"
    )
    foreach ($g in $globs) {
        $f = Get-ChildItem $g -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($f) { return $f.FullName }
    }
    return $null
}

function Invoke-Alembic([string[]]$a) {
    $out = & $script:alembic @a 2>&1 | ForEach-Object { "$_" }
    [pscustomobject]@{ Code = $LASTEXITCODE; Lines = @($out) }
}

function Get-Revs($lines) {
    @($lines | Where-Object { $_ -match '^[A-Za-z0-9_]+\s*(\(.*\))?\s*$' } | ForEach-Object { ($_ -split '\s+')[0] })
}

function New-Backup($db, [string]$file) {
    if ($db.Engine -eq 'mysql') {
        $bin = Find-Tool 'mysqldump'
        if (-not $bin) { throw "mysqldump not found. Install the MySQL client tools or add them to PATH (or use -SkipBackup after taking a provider snapshot)." }
        $env:MYSQL_PWD = $db.Password
        $base = @('-h', $db.Host, '-P', $db.Port, '-u', $db.User, '--single-transaction', '--triggers', "--result-file=$file")
        if ($db.Tls) { $base += '--ssl-mode=REQUIRED' }
        $ok = $false
        # First try with GTID purge off (managed servers), then without (older/MariaDB clients).
        foreach ($extra in @(@('--set-gtid-purged=OFF'), @())) {
            & $bin @base @extra $db.Name 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match 'error' } | ForEach-Object { Write-Host $_ -ForegroundColor DarkYellow }
            if ($LASTEXITCODE -eq 0 -and (Test-Path $file)) { $ok = $true; break }
        }
        if (-not $ok) { throw "mysqldump failed. A client/server version mismatch is a common cause; try a matching client or take a provider snapshot and use -SkipBackup." }
        $okTail = (Get-Content $file -Tail 5 -ErrorAction SilentlyContinue) -match 'Dump completed'
        if (-not $okTail) { throw "Backup file looks incomplete (no 'Dump completed' footer): $file" }
    }
    else {
        $bin = Find-Tool 'pg_dump'
        if (-not $bin) { throw "pg_dump not found. Install PostgreSQL client tools or use -SkipBackup after a provider snapshot." }
        $env:PGPASSWORD = $db.Password
        if ($db.Tls) { $env:PGSSLMODE = 'require' }
        & $bin -h $db.Host -p $db.Port -U $db.User -d $db.Name -f $file 2>&1 | ForEach-Object { Write-Host $_ -ForegroundColor DarkYellow }
        if ($LASTEXITCODE -ne 0) { throw "pg_dump failed." }
    }
    if (-not (Test-Path $file) -or (Get-Item $file).Length -lt 1024) { throw "Backup file is missing or suspiciously small: $file" }
    Write-Host ("Backup OK: {0} ({1:N0} bytes)" -f $file, (Get-Item $file).Length) -ForegroundColor Green
}

# ---- remember env so nothing leaks into later commands -----------------------------------
$savedEnv = @{}
foreach ($n in @($UrlVar, 'MYSQL_PWD', 'PGPASSWORD', 'PGSSLMODE', 'DB_SSL', 'DB_SSL_CA')) {
    $savedEnv[$n] = [Environment]::GetEnvironmentVariable($n)
}
Push-Location $BackendDir

try {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    if (-not $BackupDir) { $BackupDir = Join-Path $BackendDir "backups" }
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

    $script:alembic = Join-Path $BackendDir ".venv\Scripts\alembic.exe"
    if (-not (Test-Path $script:alembic)) { $script:alembic = "alembic" }

    Step "Reading target '$Target'"
    $db = Parse-DbUrl (Get-TargetUrl $Target)
    Write-Host ("Engine: {0} | Host: {1}:{2} | Database: {3} | User: {4} | TLS: {5}" -f $db.Engine, $db.Host, $db.Port, $db.Name, $db.User, $db.Tls)

    [Environment]::SetEnvironmentVariable($UrlVar, $db.Url, "Process")
    if ($db.Tls) { $env:DB_SSL = "1" }
    if ($SslCa) { $env:DB_SSL_CA = $SslCa }

    Step "Checking connection and current revision"
    $cur = Invoke-Alembic @('current')
    if ($cur.Code -ne 0) {
        $cur.Lines | Select-Object -Last 8 | ForEach-Object { Write-Host $_ -ForegroundColor DarkYellow }
        throw "Could not read the current revision (wrong URL/password, TLS, or firewall/IP allow-list). Nothing was changed."
    }
    $curRevs = Get-Revs $cur.Lines
    $headRevs = Get-Revs (Invoke-Alembic @('heads')).Lines
    if ($headRevs.Count -ne 1) { throw "Expected exactly one Alembic head, found $($headRevs.Count). Merge heads first." }
    $head = $headRevs[0]
    if ($curRevs.Count -eq 0) {
        throw "The database has no Alembic revision. It was built without Alembic, so 'upgrade head' would try to recreate tables. Work out the right revision and run 'alembic stamp <rev>' first."
    }
    if ($curRevs.Count -gt 1) { throw "Database reports several revisions ($($curRevs -join ', ')). Resolve manually." }
    $curRev = $curRevs[0]
    Write-Host "Database revision: $curRev | Code head: $head"
    if ($curRev -eq $head) { Write-Host "`nAlready up to date. Nothing to do." -ForegroundColor Green; return }

    Step "Backup"
    $backupFile = "(skipped)"
    if ($SkipBackup) {
        Write-Host "Backup skipped. Make sure the provider has a fresh snapshot." -ForegroundColor Yellow
    }
    else {
        $backupFile = Join-Path $BackupDir ("{0}_{1}_{2}.sql" -f $Target, $db.Name, $ts)
        New-Backup $db $backupFile
    }

    Step "Previewing SQL ($curRev -> $head)"
    $pv = Invoke-Alembic @('upgrade', "${curRev}:${head}", '--sql')
    $sql = @($pv.Lines | Where-Object { $_ -notmatch '^(INFO|WARNI)' -and $_.Trim() -ne '' })
    $sql | ForEach-Object { Write-Host $_ }

    if ($pv.Code -ne 0) {
        Write-Host "`nThe preview failed (some migrations use sa.inspect(), which cannot run offline)." -ForegroundColor Yellow
        if ($Yes) { throw "Preview failed and -Yes was given; refusing to continue." }
        if ((Read-Host "Type CONTINUE to apply without a full preview") -ne "CONTINUE") { throw "Cancelled. Nothing was changed." }
    }

    $bad = @($sql | Select-String -Pattern 'DROP\s+(TABLE|COLUMN|INDEX|CONSTRAINT|FOREIGN|SCHEMA)|TRUNCATE|DELETE\s+FROM|\sMODIFY\s|CHANGE\s+COLUMN|RENAME\s+(TABLE|COLUMN)')
    if ($bad.Count -gt 0) {
        Write-Host "`nPotentially destructive statements found:" -ForegroundColor Red
        $bad | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) -ForegroundColor Red }
        if ($Yes) { throw "Destructive SQL found; -Yes does not bypass this." }
        if ((Read-Host "Type YES to accept these statements") -ne "YES") { throw "Cancelled. Nothing was changed." }
    }

    if ($DryRun) { Write-Host "`nDry run complete. Nothing was applied." -ForegroundColor Green; return }

    if (-not $Yes) {
        if ($db.IsLocal) {
            if ((Read-Host "Apply to local database '$($db.Name)'? (y/N)") -notmatch '^[Yy]') { throw "Cancelled. Nothing was changed." }
        }
        elseif ((Read-Host "Type the database name '$($db.Name)' on $($db.Host) to apply") -ne $db.Name) { throw "Name did not match. Nothing was changed." }
    }

    Step "Applying"
    $up = Invoke-Alembic @('upgrade', 'head')
    $up.Lines | Where-Object { $_.Trim() -ne '' } | ForEach-Object { Write-Host $_ }
    if ($up.Code -ne 0) {
        throw "Upgrade FAILED. MySQL DDL is not transactional: check which objects were created before re-running. Backup: $backupFile"
    }

    Step "Verifying"
    $afterRevs = Get-Revs (Invoke-Alembic @('current')).Lines
    if ($afterRevs -contains $head) {
        Write-Host "SUCCESS: database is at $head" -ForegroundColor Green
        Write-Host "Next: deploy the backend code, spot-check row counts, rotate credentials if they were ever shared."
    }
    else { throw "Upgrade finished but the database is not at head ($($afterRevs -join ', ')). Investigate before deploying." }
}
catch {
    Write-Host "`nSTOP: $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
}
finally {
    foreach ($n in $savedEnv.Keys) { [Environment]::SetEnvironmentVariable($n, $savedEnv[$n], "Process") }
    Pop-Location
}
exit $exitCode
