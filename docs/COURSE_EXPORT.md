# Export a course

## Download from the author dashboard

Open a course from **Мои курсы** and find **Экспорт курса**. **Скачать MHTML** saves an offline reading copy. **Скачать STEP (ZIP)** saves the native folder with `course.json` at the archive root. Both formats include preview and paid lessons, in course order. To include official solutions, hidden tests and answer keys, select the author-materials checkbox before downloading STEP. Both formats exclude submissions, enrollments and progress.

The page shows queue, generation and transfer status. A second request for the same course and options resumes an outstanding job. Downloads are single-use. An unopened file expires after 15 minutes. A failed or interrupted download can be generated again.

### Worker setup

For local development, run `python manage.py migrate` and start `python manage.py course_export_worker` alongside the web server. Docker Compose defines the same worker in the `export-worker` service. It uses the web image, shared SQLite database, read-only media, and a private shared volume. No message broker or new Python package is required. Both processes must use the same private `COURSE_EXPORT_ROOT` (local default `.course-downloads/`). Restrict the directory to their service account. The worker sweeps interrupted builds, expired files and deleted-course artifacts.

The JWT-authenticated API accepts `POST /api/courses/<course-uuid>/exports/` with `{"format":"zip","author_materials":false}` or `{"format":"mhtml"}`. Poll `GET .../exports/<job-uuid>/` and, once ready, send `POST .../exports/<job-uuid>/download/`. Every operation checks current authorization. An active course owner with the AUTHOR or ADMIN role can export their course. For cross-course exports, grant a Django staff account the explicit permission `api.export_any_course`. Django superusers also have this permission. Jobs are private to their requester. Staff status or the platform ADMIN label alone grants no cross-course export access.

The worker processes one course at a time. Admission allows one pending build per user, four new jobs per user per ten minutes and twelve queued, running or ready jobs across the installation. An individual build has three minutes, 1,000 lessons, 5,000 steps, 8 MiB of stored step content and description, 32 MiB of assets and a 96 MiB output limit. The Linux build subprocess also has a 512 MiB address-space limit. A course over budget produces an error. Operators can use the existing CLI for larger courses with sufficient resources. The dashboard streams the response from disk and the browser saves a bounded Blob.

## VPS release checklist

- [ ] Record the running commit, web image ID, Compose project name and version (2.24+), and applied migrations in `/root/learning-platform`. Inspect `free -h`, `docker stats --no-stream`, `lsblk -f`, available inodes, and available space on the database, backup and Docker filesystems. Budget 768 MiB and one CPU for the worker alongside web, runner, OS and backup activity. Worker swap is capped at its RAM limit, its temporary filesystem at 32 MiB and its process count at 64. Web and worker logs rotate.
- [ ] Have the VPS administrator provision an independently backed, fixed-capacity filesystem mounted persistently at `/srv/uchebus-exports`. A 2 GiB filesystem accommodates the twelve-job queue, staging and reserve at the current limits. Confirm the backing disk or reserved LV has capacity independent of SQLite, including any underlying thin pool. Arrange mount ordering before Docker starts after reboot. A directory or sparse file on the DB filesystem does not provide this guarantee. A same-device project quota would require a separate quota-aware implementation.
- [ ] After confirming the mount, create a root-owned mode-0700 `spool` subdirectory **on the mounted device**. Compose binds this exact existing directory into both containers with host path creation disabled. Remove any legacy Compose override that replaces this mount. The default production configuration enables separate-device enforcement. No new secrets are required.

```bash
cd /root/learning-platform
set -eu
db_mount=$(docker volume inspect -f '{{.Mountpoint}}' learning-platform_db-data)
mountpoint -q /srv/uchebus-exports
findmnt --mountpoint /srv/uchebus-exports
test -d /srv/uchebus-exports/spool
test "$(stat -c %d /srv/uchebus-exports/spool)" != "$(stat -c %d "$db_mount")"
stat -c '%U:%G %a %n' /srv/uchebus-exports/spool
test "$(stat -c '%u:%g:%a' /srv/uchebus-exports/spool)" = 0:0:700
df -h "$db_mount" /srv/uchebus-exports/spool /root/backups
df -i "$db_mount" /srv/uchebus-exports/spool
```

- [ ] Verify the Git release contains migration 0025 and the restore-aware entrypoint. Record the prior SHA outside the checkout. Run the existing online backup and verify its name before changing the live DB. Check that the backup has a separate recoverable copy. Keep the existing `.env`, certificates, project name and DB/media volumes.

```bash
: "${RELEASE_SHA:?Set to the full approved commit}"
git rev-parse HEAD
docker inspect --format '{{.Image}}' "$(docker compose ps -q web)"
scripts/backup.sh
# Use the exact auto_... directory reported by backup.sh.
scripts/restore.sh --check "${BACKUP_NAME:?Set to the verified backup name}"
git fetch origin main
git merge --ff-only "$RELEASE_SHA"
test "$(git rev-parse HEAD)" = "$RELEASE_SHA"
docker compose config --quiet
docker compose build web export-worker
bash scripts/test_restore.sh
docker compose run --rm --no-deps -T web python manage.py shell -c \
  'from api.course_export.jobs import check_capacity; check_capacity()'
docker compose run --rm --no-deps -T -e DB_DIR=/tmp web python manage.py test api.test_course_downloads api.test_course_export
docker compose run --rm --no-deps -T web python manage.py migrate --plan
```

- [ ] Confirm the only pending migration on an up-to-date installation is `api.0025_course_export_job`. Rehearse restore and interrupted-restore recovery with the built images on a disposable Linux Docker host. The restore script targets the fixed production volume names. Use a separate Docker daemon for this drill. Verify exported files and the database have different device IDs inside **both** containers. The service checks 448 MiB free on the spool (256 MiB reserve plus space for the folder and archive) and 1 GiB free on the DB filesystem before admission and before building. Downloads and cleanup remain available under low space. These checks supplement the hard filesystem boundary.
- [ ] During the approved deployment window, apply migrations before starting the worker. Recheck service health and effective limits.

```bash
docker compose run --rm --no-deps -T web python manage.py migrate --noinput
docker compose up -d --no-deps web export-worker
docker compose exec -T nginx nginx -s reload
curl -fsS --retry 10 --retry-delay 2 https://uchebus.ru/api/status/
docker compose exec -T web python manage.py migrate --check
docker compose exec -T export-worker stat -c '%d %n' /app/db /app/course-downloads
docker compose ps
docker inspect --format '{{.HostConfig.RestartPolicy.Name}} {{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}}' "$(docker compose ps -q export-worker)"
docker compose logs --tail=50 export-worker
```

- [ ] Download both formats as the owner of a paid test course. Check that a student is denied, the ZIP contains its locked lesson, and the artifact disappears after transfer. Grant `api.export_any_course` only to designated staff.
- [ ] **Rollback.** For an application rollback, stop the export worker first, check out the recorded previous SHA, rebuild/recreate the previous web image and reload nginx. Keep the DB/media volumes and the additive job table. If data recovery is necessary, keep the restore-aware release installed, verify the chosen snapshot with `scripts/restore.sh --check "$BACKUP_NAME"`, then run `scripts/restore.sh "$BACKUP_NAME"` interactively. Restore replaces DB and media, including any writes since the snapshot. Follow the printed safety-snapshot recovery instructions if validation fails. Never use `docker compose down -v` during rollback. [Backup and restore procedure](BACKUP.md)

## Administrative command

In the VPS containers, pass a directory under the verified spool, for example `--output-dir /app/course-downloads/manual/2026-11-23`. Copy these administrative archives to their intended destination and remove them when finished. The worker expires dashboard jobs only. The relative paths below apply to standalone development.

Run these commands from the repository root with the project's Python environment and Django settings. Replace `python-basics` with a course slug or UUID. Each command prints lesson progress and the final artifact path. Asset warnings go to stderr. Errors such as a missing course, inaccessible output directory, or existing destination produce a nonzero exit code.

```sh
python manage.py export_course python-basics --format mhtml --output-dir ./exports
python manage.py export_course python-basics --format folder --output-dir ./exports
python manage.py export_course python-basics --format folder --author-materials --output-dir ./private-exports
```

The operator needs read access to the configured database and course assets and write access to the output directory. Shell and filesystem permissions control access. The command can read drafts, paid courses, and all lessons of the selected course. Treat even a learner export as a copy of the entire course. Use a private destination for author exports and restrict access to the directory and any copies. The command rejects author destinations in the configured media and static directories. On Windows, use a directory with an appropriate ACL.

The command reads course content without saving models or recording activity. It stages files in the destination filesystem and publishes the completed artifact. Use a new output directory for each scheduled run, for example a directory named with the job timestamp. An existing artifact is an error. MHTML publication uses a hard link and requires a filesystem that supports it. The snapshot and referenced asset bytes are held in memory for the duration of the export. For a consistent backup when editors are replacing or removing media, run against a matching database and storage snapshot.

## MHTML reading copy

Open the resulting `.mhtml` in Chrome or Edge. The archive opens a full-page reading frame containing the syllabus and lesson headings. Selecting a lesson scrolls to its heading inside the open archive, including after moving or renaming the file. The course HTML and its assets are MIME parts with matching `Content-Location` URLs. Export uses Python's standard `email` library and the project's existing rendering and slugification dependencies. [MHTML specification](https://www.rfc-editor.org/rfc/rfc2557)

Code exercises show starter code and visible examples. Quizzes show options, fills show empty gaps, sorting and matching show the learner's items, and tables show an unfilled grid. Code execution, submission, grading, and progress tracking require the platform. Math displays its stored TeX, and local audio and video are represented as media links whose playback depends on the reader. The offline layout uses its own stylesheet. External sites, embedded players, and resources referenced only by custom CSS require their original environment.

## Native folder schema v1

```text
python-basics-<uuid>-author/
  course.json
  assets/<sha256>.png
  lessons/
    001-strings/
      lesson.json
      01_text.step
      02_code.step
      03_choice.step
    002-practice/
      lesson.json
      01_fill-blanks.step
      02_sorting.step
      03_matching.step
      04_table.step
```

All manifests and `.step` files are UTF-8 JSON. A reader should check `format == "uchebus-course"`, `schema_version == 1`, and `audience` before processing the package. Follow the manifest arrays in order, including empty lessons. Paths inside the package use forward slashes. Filenames use dense ordinal positions, while each record preserves its original UUID, timestamps, and stored order index. The extension and numbered filenames follow the reference materials; the data contract is native to УЧЁБУС.

| Record | Fields used by a reader |
| --- | --- |
| `course.json` | Course UUID, slug, title, description, tagline, tag, level, price and old price as decimal strings or null, catalog order, publication state, source author ID and username, linked Stepik ID, cover storage name, timestamps, ordered paths to lesson manifests, and asset map. |
| `lesson.json` | Lesson UUID, title, original `order_index`, preview setting, timestamps, and ordered step filenames relative to that lesson directory. |
| `*.step` | Block UUID, native `type`, original `order_index`, timestamps, and `content`. The containing manifest identifies the parent; the filename suffix is for convenience. |
| `assets` | The course manifest maps original resource references to paths relative to the course root. A null value records an unavailable resource. `asset_types` gives the MIME type for each packaged path. `cover_asset`, when present, points to the packaged cover. Identical asset bytes of the same media type share a file. |

**Author mode** preserves the stored block JSON, including IDs inside sorting, matching, and table tasks, answer keys, comparison modes, hidden test cases, header/footer code, and configured official solutions. It retains unknown block types and their original JSON for a future reader. A future importer can use the original content and the asset map to upload resources, replace references with target storage URLs, map the source author to a local account, and restore lesson and block order. Treat imported rich text and code as untrusted content. The existing HTML lesson importer accepts a different format.

**Learner mode** stores the platform's learner-facing representation. Coding tests contain only visible input/output examples, using the platform's visibility rule for legacy tests. Sorting items and matching columns use their learner order, quiz and table answer keys are omitted, and fill answers are blanked. For an unsupported type the record retains its identity and position with `content: null`. Use an author export when a future importer needs to reconstruct grading. Both formats exclude enrollments, user attempts, saved submissions (including author practice), discussions, and messages.

The asset resolver reads covers from Django storage, and media and static references from recognized rich-text fields. It supports root-relative URLs, absolute URLs on explicitly configured hosts, and inline base64 PNG, JPEG, GIF and WebP images. Missing and external resources produce warnings; a missing inline image in MHTML gets a text placeholder. Original references remain in the structured content. Ordinary external hyperlinks remain available for online use.

## Verification

```sh
python manage.py test api.test_course_downloads api.test_course_export backend.tests.PublicCourseAccessTests
```

The suite checks all seven types, ordering, asset bytes and references, syllabus targets, public/private boundaries, unknown types, and incomplete writes.

For the browser regression, install the optional Python `playwright` package in the test environment and use locally installed Chrome and Edge. In PowerShell:

```powershell
$env:UCHEBUS_TEST_MHTML_BROWSERS = 'chrome,msedge'
python manage.py test api.test_course_export.CourseExportTests.test_syllabus_click_scrolls_in_the_same_offline_document
```

The test opens a renamed archive offline, clicks a syllabus entry, and checks that the heading scrolls into view without another document request.
