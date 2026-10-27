# Backups

The live site keeps everything that matters in two Docker volumes:

| Volume                         | Mounted in `web` at   | Holds                          |
|--------------------------------|-----------------------|--------------------------------|
| `learning-platform_db-data`    | `/app/db`             | `db.sqlite3` (all site data)   |
| `learning-platform_media-data` | `/app/media`          | images uploaded by authors     |

Three scripts protect them:

| Script                          | Runs on        | Does                                                      |
|---------------------------------|----------------|-----------------------------------------------------------|
| `scripts/backup.sh`             | server, cron   | daily backup without stopping the site, keeps the last 14 |
| `scripts/restore.sh`            | server, by hand| checks a backup, or restores it (with a safety copy first)|
| `scripts/download_backups.ps1`  | Windows laptop | pulls new backups, keeps a plain copy locally, puts an encrypted `.7z` into Google Drive |

**Not in any backup, on purpose:** `.env` (secrets) and `/root/certs` (TLS keys).
Keep a copy of `.env` in your password manager; you need it to rebuild a server.

## What a backup looks like

`/root/backups/auto_2026-10-27_000003Z/` (the name is the UTC time it was made):

| File           | Content                                                        |
|----------------|----------------------------------------------------------------|
| `db.sqlite3`   | consistent snapshot of the database; passed `PRAGMA integrity_check` |
| `media.tar.gz` | everything in the media volume                                 |
| `info.txt`     | time, server, git commit of the code, DB size, number of images |
| `SHA256SUMS`   | checksums of the three files above                             |

How it is made: a small Python program runs inside the running `web`
container (`docker compose exec`) and copies the database with SQLite's online
backup API, so the site never stops. Media is read by a throwaway
`alpine:3.20` container that mounts the volume read-only. A backup is built in
`auto_<time>.partial/` and renamed only when every step has passed, so a
half-finished backup is never mistaken for a good one.

**Retention:** after each successful run, only the 14 newest `auto_*` folders
are kept. It counts backups, not days: extra manual runs also count. Anything
else in `/root/backups` (the manual snapshots from 18-19 October,
`pre-restore_*` folders, other files) is never deleted by the scripts.

The database contains personal data (names, emails, password hashes). Server
backups are readable by root only; laptop copies outside the server are
encrypted (see below).

## 1. Install on the server (once)

All commands run on the server as root.

```bash
cd /root/learning-platform
git pull
```

The scripts are stored in Git as executable. If `ls -l scripts/*.sh` does not
show `x` permissions, add them (harmless if they are already there):

```bash
chmod +x scripts/backup.sh scripts/restore.sh
```

Download the helper image once, so the first night's run does not depend on
Docker Hub:

```bash
docker pull alpine:3.20
```

Check the server clock. The `Time zone` line should say `Etc/UTC` (or `UTC`):

```bash
timedatectl
```

Run the first backup by hand and look at the result:

```bash
scripts/backup.sh
ls -l /root/backups
scripts/restore.sh --check auto_2026-10-27_000003Z     # use the name just printed
```

Install the cron job. It runs every day at 00:00 server time; the server clock
is UTC, so that is **00:00 UTC = 03:00 Moscow time**. The script logs to
`/var/log/uchebus-backup.log` (a few lines per day).

```bash
(crontab -l 2>/dev/null; echo '0 0 * * * /root/learning-platform/scripts/backup.sh >> /var/log/uchebus-backup.log 2>&1') | crontab -
crontab -l
```

`crontab -l 2>/dev/null` prints the current crontab (nothing yet), `echo` adds
the new line, and `crontab -` installs the result. The cron line itself:

```
0 0 * * *   /root/learning-platform/scripts/backup.sh   >> /var/log/uchebus-backup.log 2>&1
| | | | |   the script                                    append output and errors to the log
| | | | +-- any day of the week
| | | +---- any month
| | +------ any day of the month
| +-------- hour 0
+---------- minute 0
```

`backup.sh` sets its own full `PATH` and changes to the project folder itself,
so cron's minimal environment is not a problem.

The next morning, check that it ran:

```bash
tail -n 20 /var/log/uchebus-backup.log
```

A good run ends with `Backup auto_... finished (...); N auto backups kept`.
A failed run ends with `BACKUP FAILED (exit code ...)`, with the reason in the
`ERROR:` line just above it. A failure never deletes older backups.

## 2. Run a backup by hand

Any time, for example before a risky deploy:

```bash
/root/learning-platform/scripts/backup.sh
```

It refuses to run while another backup or a restore is running.

## 3. Download to the laptop

`download_backups.ps1` runs in Windows PowerShell on the laptop. For each new
backup it:

1. downloads it with `scp` and checks every file against `SHA256SUMS`;
2. keeps that plain copy in `$PlainDir` on the local disk, which is **not** synced;
3. packs it into `<name>.7z`: 7-Zip format, AES-256, with file names
   encrypted too (`-mhe=on`). It tests the archive and moves it to `$SyncedDir`,
   your Google Drive folder. Only `.7z` files ever go there.

It prints a **WARNING** if the newest backup on the server is more than 2 days
old. That usually means the cron job stopped or keeps failing: check
`/var/log/uchebus-backup.log` on the server.

### One-time setup

1. **7-Zip** at `C:\Program Files\7-Zip\7z.exe` (https://www.7-zip.org/). If
   it is somewhere else, change `$SevenZip` at the top of the script.
2. **OpenSSH client**: `ssh` and `scp` come with Windows 10 (Settings > Apps >
   Optional features > OpenSSH Client).
3. **Settings** at the top of `scripts\download_backups.ps1`:
   - `$SyncedDir`: your Google Drive for desktop folder, e.g. `G:\My Drive\uchebus-backups`;
   - `$PlainDir`: a local folder that is NOT synced (default:
     `C:\Users\<you>\uchebus-backups-plain`). The script refuses if one
     folder is inside the other.
4. **SSH key** (recommended). Without one, `scp` asks for the root password once
   per backup. Create a key and copy it to the server, in PowerShell:

   ```powershell
   ssh-keygen -t ed25519
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@uchebus.ru "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
   ssh root@uchebus.ru "ls /root/backups"
   ```

   The last command must work without asking for the server password. If you
   gave the key a passphrase, `ssh` asks for that instead.
5. **Archive password**: choose one (at least 12 characters, no `"` and not
   ending with `\`) and store it in your password manager. **Without it the
   `.7z` archives cannot be opened by anyone, including you.**

### Run

From the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\download_backups.ps1
```

If there is something new to encrypt, it asks for the archive password twice.
The password is kept only in memory and never saved. If the password does not
open the newest existing archive (a typo, or the wrong password), it stops. To
really switch to a new password, type `NEW` when asked.

The script ends with a summary: backups on the server, downloaded and
encrypted now, failures, and what is in each local folder. A failed download
(e.g. checksum mismatch) is reported, the others continue, and the next run
tries it again. The exit code is 1 if anything failed.

Run it as often as you like: it only processes backups whose `.7z` is not in
`$SyncedDir` yet. Nothing is ever deleted on the laptop; remove old archives or
plain copies by hand when you no longer want them.

## 4. Decrypt a downloaded backup

With the 7-Zip window: right-click `auto_<time>.7z` > 7-Zip > Extract here,
then enter the archive password.

Or in PowerShell (7-Zip asks for the password):

```powershell
& "C:\Program Files\7-Zip\7z.exe" x "G:\My Drive\uchebus-backups\auto_2026-10-27_000003Z.7z" -oC:\Temp\restore
```

On Linux or macOS: `7z x auto_2026-10-27_000003Z.7z` (package `7zip` or `p7zip-full`).

The result is the original backup folder, `auto_<time>\` with `db.sqlite3`,
`media.tar.gz`, `info.txt` and `SHA256SUMS`. To check it in PowerShell,
compare each line of `SHA256SUMS` with:

```powershell
Get-FileHash C:\Temp\restore\auto_2026-10-27_000003Z\db.sqlite3     # also media.tar.gz, info.txt
Get-Content  C:\Temp\restore\auto_2026-10-27_000003Z\SHA256SUMS
```

The hashes must be equal (`Get-FileHash` prints them in upper case). On Linux:
`cd auto_<time> && sha256sum -c SHA256SUMS`.

## 5. Restore on the server

Restoring replaces **all** live data: anything written to the site after the
backup was made is lost (except in the safety copy, see below).

First check the backup (changes nothing, the site keeps running):

```bash
cd /root/learning-platform
ls /root/backups
scripts/restore.sh --check auto_2026-10-27_000003Z
```

It verifies the checksums and the archive, runs an integrity check on a copy
of the database inside the `web` container, and prints the newest migration
and the number of rows per table.

Then restore:

```bash
scripts/restore.sh auto_2026-10-27_000003Z
```

It shows the backup's `info.txt` and asks you to type the folder name. Then it:

1. stops only `web`. nginx and the runner keep running; visitors see a 502
   error page for the duration, usually under a minute;
2. saves the current DB and media to `/root/backups/pre-restore_<time>/`;
3. replaces the database (and removes any leftover `-journal`/`-wal` file),
   empties the media volume and unpacks the backup's media;
4. starts `web` (it applies any newer migrations on startup), waits until it
   answers, and runs the integrity check on the restored database.

**Undo a restore:** restore the safety copy the same way:

```bash
scripts/restore.sh pre-restore_2026-10-27_101500Z
```

If something fails before any data was changed, the script starts `web` again
by itself. If it fails after that, it leaves `web` stopped and prints the exact
command to put the previous data back. `pre-restore_*` folders are never
deleted automatically; remove them by hand once you are happy:

```bash
rm -rf /root/backups/pre-restore_2026-10-27_101500Z
```

**Code version.** `info.txt` records the git commit the server ran when the
backup was made. Restoring an older backup onto newer code is fine: `web`
applies the missing migrations on start. Restoring onto *older* code than the
backup (after rolling the code back) can fail: deploy that commit or a newer one
first.

### Restore from a laptop copy

When the server copy is gone, decrypt the `.7z` (section 4) and upload the
folder. Use a folder **outside** `/root/backups`: an old `auto_*` folder inside
it would be deleted by the next nightly retention.

```powershell
ssh root@uchebus.ru "mkdir -p /root/restore-from-laptop"
scp -r C:\Temp\restore\auto_2026-10-27_000003Z root@uchebus.ru:/root/restore-from-laptop/
```

Then on the server:

```bash
cd /root/learning-platform
scripts/restore.sh --check /root/restore-from-laptop/auto_2026-10-27_000003Z
scripts/restore.sh /root/restore-from-laptop/auto_2026-10-27_000003Z
```

### On a new server

Set the server up as usual (clone the repository to `/root/learning-platform`,
put `.env` back from your password manager, put the certificates into
`/root/certs/uchebus`, `docker compose up -d --build`), check that the site
starts, then restore as above. `restore.sh` needs the containers to exist
because it uses `docker compose start web`.

## 6. Test a restore safely

Do this now and then, e.g. once a month: a backup you have never restored is
only a hope.

**On the server, without touching the live site:**

```bash
cd /root/learning-platform
scripts/restore.sh --check auto_2026-10-27_000003Z
```

Compare the row counts with what you expect: number of users, courses,
lessons, and so on.

**Full rehearsal on the laptop (no Docker needed).** `settings.py` reads the
database folder from the `DB_DIR` environment variable, so the local Django
can run on a copy of a backup without touching your development database.
In PowerShell, in the project folder, with your usual Python environment:

```powershell
New-Item -ItemType Directory -Force C:\Temp\restore-test | Out-Null
Copy-Item "$env:USERPROFILE\uchebus-backups-plain\auto_2026-10-27_000003Z\db.sqlite3" C:\Temp\restore-test\
$env:DB_DIR = 'C:\Temp\restore-test'   # use the copy instead of the local db.sqlite3
$env:EMAIL_HOST = ''                   # emails only printed, never sent to real users
python manage.py migrate               # only does something if your code has newer migrations
python manage.py runserver
```

Open http://127.0.0.1:8000, log in with your own account and check that the
courses, lessons and progress are there. Lesson images show as broken because
media is not unpacked locally. To look at them, open `media.tar.gz` from the
same backup with 7-Zip.

Afterwards, stop the server (Ctrl+C) and clean up:

```powershell
Remove-Item Env:DB_DIR, Env:EMAIL_HOST
Remove-Item -Recurse C:\Temp\restore-test
```

The copy contains real personal data, so do not leave it lying around.
