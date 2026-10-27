<#
download_backups.ps1 - copy new server backups to this laptop, encrypted.

What it does, in order:
  1. Lists the auto_* backup folders on the server (ssh) and prints a WARNING
     if the newest one is older than $MaxAgeDays days.
  2. For every server backup that has no .7z in $SyncedDir yet:
     a. downloads it with scp into $PlainDir\.incoming (skipped if the plain
        copy is already in $PlainDir),
     b. checks every file against the backup's SHA256SUMS,
     c. moves it to $PlainDir (plain copy: local disk only, never synced),
     d. packs it into a 7-Zip archive (AES-256, file names encrypted too),
        tests the archive and moves it to $SyncedDir.
  3. Prints a summary.

Only encrypted .7z files ever go into $SyncedDir. The archive password is
asked when there is something to encrypt and kept only in memory: it is
never saved anywhere.

Run it from a PowerShell window in the project folder:
  powershell -ExecutionPolicy Bypass -File scripts\download_backups.ps1
#>

# ---- Settings ---------------------------------------------------------------
$Server     = 'root@uchebus.ru'                         # ssh login for the VPS
$RemoteDir  = '/root/backups'                           # where backup.sh writes
$PlainDir   = "$env:USERPROFILE\uchebus-backups-plain"  # plain copies: local only, NOT synced
$SyncedDir  = 'G:\My Drive\uchebus-backups'             # encrypted .7z only: Google Drive folder
$SevenZip   = 'C:\Program Files\7-Zip\7z.exe'           # 7-Zip's default install path
$MaxAgeDays = 2                                         # warn if the newest backup is older

Set-StrictMode -Version Latest     # using a variable that was never set is an error
$ErrorActionPreference = 'Stop'    # any failing cmdlet stops the script (or the try block)

$NamePattern = '^auto_(\d{4}-\d{2}-\d{2}_\d{6})Z$'     # folder names made by backup.sh
$Incoming    = Join-Path $PlainDir '.incoming'          # unfinished downloads and archives

function Fail([string]$message) {
    Write-Host "ERROR: $message" -ForegroundColor Red
    exit 1
}

# SecureString (what Read-Host -AsSecureString returns) -> normal string.
function ConvertTo-PlainText([Security.SecureString]$secure) {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }   # wipe the unmanaged copy
}

# Asks for the archive password twice; returns it.
function Read-ArchivePassword {
    Write-Host ''
    Write-Host 'Archive password: use the same one every time and keep it in your password manager.'
    $first  = ConvertTo-PlainText (Read-Host 'Password' -AsSecureString)
    $second = ConvertTo-PlainText (Read-Host 'Repeat password' -AsSecureString)
    if ($first -cne $second) { Fail 'the two passwords differ.' }    # -cne: case-sensitive
    if ($first.Length -lt 12) { Fail 'the password must be at least 12 characters long.' }
    # Windows PowerShell 5.1 cannot pass these two safely on the 7z command line.
    if ($first.Contains('"') -or $first.EndsWith('\')) { Fail 'the password must not contain " or end with \.' }

    # Guard against a different password by mistake: it should open the newest
    # archive made by an earlier run.
    $newest = Get-ChildItem -LiteralPath $SyncedDir -Filter 'auto_*.7z' -File |
        Sort-Object Name | Select-Object -Last 1
    if ($newest) {
        # l = list the archive; with encrypted names this needs the right password.
        # Only the exit code matters: -bse0 drops error messages, > $null the listing.
        & $SevenZip l "-p$first" -bse0 -- $newest.FullName > $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "This password does not open $($newest.Name) (made by an earlier run)." -ForegroundColor Yellow
            $answer = Read-Host 'Type NEW to use it anyway for the new archives, or press Enter to stop'
            if ($answer -cne 'NEW') { Fail 'stopped; nothing was downloaded or encrypted.' }
        }
    }
    return $first
}

# Throws unless every file listed in $dir\SHA256SUMS exists and matches.
function Test-Checksums([string]$dir) {
    $sumsFile = Join-Path $dir 'SHA256SUMS'
    if (-not (Test-Path -LiteralPath $sumsFile -PathType Leaf)) { throw 'SHA256SUMS is missing' }
    $lines = @(Get-Content -LiteralPath $sumsFile | Where-Object { $_.Trim() -ne '' })
    if ($lines.Count -eq 0) { throw 'SHA256SUMS is empty' }
    foreach ($line in $lines) {
        # sha256sum writes: 64 hex digits, a space, a space or "*" (binary
        # mode marker), file name. Only plain file names are accepted (no
        # folders, no ..).
        if ($line -notmatch '^([0-9a-f]{64}) [ *]([A-Za-z0-9._-]+)$') { throw "unexpected line in SHA256SUMS: $line" }
        $expected = $Matches[1]
        $fileName = $Matches[2]
        $file = Join-Path $dir $fileName
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "$fileName is missing" }
        $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
        # -ne ignores case: Get-FileHash gives upper-case hex, sha256sum lower-case.
        if ($actual -ne $expected) { throw "checksum mismatch: $fileName" }
    }
    Write-Host "  checksums ok ($($lines.Count) files)"
}

# Downloads one backup folder, checks it and moves it to $PlainDir.
function Copy-ServerBackup([string]$name) {
    $staging = Join-Path $Incoming $name
    # Left over from an interrupted run: start again from scratch.
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    Write-Host '  downloading ...'
    # scp copies into the current folder ("."), so it never has to tell a
    # Windows drive letter ("C:...") from a server name ("host:...").
    Push-Location -LiteralPath $Incoming
    try {
        # ${Server}: the braces stop PowerShell from reading "$Server:" as a drive.
        & scp -r "${Server}:$RemoteDir/$name" .
        $exitCode = $LASTEXITCODE
    }
    finally { Pop-Location }
    if ($exitCode -ne 0) { throw "scp failed (exit code $exitCode)" }
    Test-Checksums $staging
    Move-Item -LiteralPath $staging -Destination (Join-Path $PlainDir $name)
}

# Packs $PlainDir\$name into $SyncedDir\$name.7z.
function New-EncryptedArchive([string]$name, [string]$password) {
    $plain = Join-Path $PlainDir $name
    $tmp   = Join-Path $Incoming "$name.7z"     # built and tested here, outside the synced folder
    $final = Join-Path $SyncedDir "$name.7z"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    Write-Host '  encrypting ...'
    # a            add files to a new archive (here: the whole backup folder)
    # -t7z         7z format: with a password the content is encrypted with AES-256
    # -mhe=on      encrypt the headers too, so even the file names need the password
    # -p...        the password (given to 7z only, never written to a file)
    # -bso0 -bsp0  no file list, no progress bar; errors are still shown
    # --           end of options: what follows are file names
    & $SevenZip a -t7z -mhe=on "-p$password" -bso0 -bsp0 -- $tmp $plain
    if ($LASTEXITCODE -ne 0) { throw "7-Zip could not create the archive (exit code $LASTEXITCODE)" }
    # t = test: decrypt the new archive with the password and check every file.
    & $SevenZip t "-p$password" -bso0 -bsp0 -- $tmp
    if ($LASTEXITCODE -ne 0) { throw "testing the new archive failed (exit code $LASTEXITCODE)" }
    Move-Item -LiteralPath $tmp -Destination $final
    Write-Host ('  encrypted: {0} ({1:N1} MB)' -f $final, ((Get-Item -LiteralPath $final).Length / 1MB))
}

# ---- Checks before doing anything -------------------------------------------
if (-not (Test-Path -LiteralPath $SevenZip -PathType Leaf)) {
    Fail "7-Zip not found at '$SevenZip'. Install it from https://www.7-zip.org/ or set `$SevenZip at the top of this script."
}
foreach ($tool in 'ssh', 'scp') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Fail "$tool not found. Install 'OpenSSH Client' (Settings > Apps > Optional features)."
    }
}
# Plain copies must never end up in the synced folder, and the other way round.
$plainFull  = [IO.Path]::GetFullPath($PlainDir).TrimEnd('\') + '\'
$syncedFull = [IO.Path]::GetFullPath($SyncedDir).TrimEnd('\') + '\'
if ($plainFull.StartsWith($syncedFull, 'OrdinalIgnoreCase') -or $syncedFull.StartsWith($plainFull, 'OrdinalIgnoreCase')) {
    Fail '$PlainDir and $SyncedDir must be separate folders, neither inside the other.'
}
foreach ($dir in $PlainDir, $SyncedDir, $Incoming) {
    if (-not (Test-Path -LiteralPath $dir)) {
        try { New-Item -ItemType Directory -Path $dir | Out-Null }
        catch { Fail "cannot create folder '$dir' (is Google Drive for desktop running?): $($_.Exception.Message)" }
    }
}

# ---- 1. What is on the server -----------------------------------------------
Write-Host "Listing backups on $Server ..."
$listing = & ssh $Server "ls -1 $RemoteDir"
if ($LASTEXITCODE -ne 0) { Fail "ssh failed (exit code $LASTEXITCODE). Check `$Server and your SSH key or password." }
# Only finished backups made by backup.sh; the names sort by time, oldest first.
$remote = @($listing | Where-Object { $_ -match $NamePattern } | Sort-Object)

$warnings = @()
if ($remote.Count -eq 0) {
    $warnings += 'there are no auto_* backups on the server. Is the cron job installed?'
}
else {
    $newest = $remote[-1]
    $stamp = ([regex]::Match($newest, $NamePattern)).Groups[1].Value
    # The name holds the UTC time the backup was made.
    $created = [DateTime]::ParseExact($stamp, 'yyyy-MM-dd_HHmmss',
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]'AssumeUniversal, AdjustToUniversal')
    $ageHours = ([DateTime]::UtcNow - $created).TotalHours
    Write-Host ('{0} backups on the server; newest: {1} ({2:N1} hours ago)' -f $remote.Count, $newest, $ageHours)
    if ($ageHours -gt $MaxAgeDays * 24) {
        $warnings += ('the newest backup on the server is {0:N1} days old (limit {1}). Check /var/log/uchebus-backup.log on the server.' -f ($ageHours / 24), $MaxAgeDays)
    }
}
foreach ($warning in $warnings) { Write-Host "WARNING: $warning" -ForegroundColor Yellow }

# ---- 2. Download, check, encrypt --------------------------------------------
# A backup is done once its .7z is in the synced folder.
$todo = @($remote | Where-Object { -not (Test-Path -LiteralPath (Join-Path $SyncedDir "$_.7z")) })
$downloaded = @()
$encrypted  = @()
$failed     = @()
if ($todo.Count -gt 0) {
    Write-Host "$($todo.Count) new backup(s) to process."
    $password = Read-ArchivePassword
    foreach ($name in $todo) {
        Write-Host ''
        Write-Host "== $name"
        $plain = Join-Path $PlainDir $name
        try {
            if (Test-Path -LiteralPath $plain) {
                Write-Host '  plain copy already here, only the .7z is missing'
                Test-Checksums $plain
            }
            else {
                Copy-ServerBackup $name
                $downloaded += $name
            }
            New-EncryptedArchive $name $password
            $encrypted += $name
        }
        catch {
            # Report and go on with the next backup; the next run retries this one.
            Write-Host "  FAILED: $($_.Exception.Message)" -ForegroundColor Red
            $failed += $name
        }
    }
    $password = $null
}

# ---- 3. Summary -------------------------------------------------------------
$archives   = @(Get-ChildItem -LiteralPath $SyncedDir -Filter 'auto_*.7z' -File)
$archiveMB  = 0
foreach ($archive in $archives) { $archiveMB += $archive.Length / 1MB }
$plainCount = @(Get-ChildItem -LiteralPath $PlainDir -Directory | Where-Object { $_.Name -match $NamePattern }).Count
Write-Host ''
Write-Host '==== Summary ===='
Write-Host ('On the server:  {0} backups' -f $remote.Count)
Write-Host ('Downloaded now: {0}' -f $downloaded.Count)
Write-Host ('Encrypted now:  {0}' -f $encrypted.Count)
if ($failed.Count -gt 0) {
    Write-Host ('Failed:         {0} ({1})' -f $failed.Count, ($failed -join ', ')) -ForegroundColor Red
}
Write-Host ('Synced folder:  {0} encrypted archives, {1:N1} MB in {2}' -f $archives.Count, $archiveMB, $SyncedDir)
Write-Host ('Plain copies:   {0} folders in {1} (not synced)' -f $plainCount, $PlainDir)
foreach ($warning in $warnings) { Write-Host "WARNING: $warning" -ForegroundColor Yellow }
if ($failed.Count -gt 0) { exit 1 }
