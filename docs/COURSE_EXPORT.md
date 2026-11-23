# Export a course

Authors open **Экспорт курса** on their course page and choose **Скачать MHTML** or **Скачать STEP (ZIP)**. The page shows generation status followed by download progress. The checkbox includes official solutions and hidden tests in STEP only. Both downloads contain the full course, including paid lessons. Student submissions, enrollment, progress and messages are excluded.

The authenticated endpoint is `POST /api/courses/<uuid>/exports/` with `{"format":"zip","author_materials":false}` or `{"format":"mhtml"}`. It returns the completed file. Active owners with AUTHOR/ADMIN roles, explicitly permitted staff (`api.export_any_course`), and superusers may export. Authorization is checked before admission, inside the child, and before delivery.

An OS file lock on `DB_DIR/.course-export.lock` admits one export across processes and containers sharing the VPS database volume, including the active download. Four requests per user per ten minutes are recorded in this small private lock file. It must remain on a local filesystem supporting locks. A busy server returns 429 with Retry-After.

Each request starts a short-lived child and creates one private `TemporaryFile`. Linux unlinks the file at creation. Closing the final descriptor releases its disk space, including after crashes. The child inherits the slot lock so a web crash cannot admit a second build before the child exits. ZIP entries use the same serialization as the structured folder command, with no intermediate folder.

Limits are 90 seconds wall time, 75 seconds CPU time, 512 MiB address space on Linux, 96 MiB final output, 32 MiB unique assets, 8 MiB source content, 1,000 lessons and 5,000 steps. The largest measured production course had an individual 21.84-second ZIP run. The generation deadline includes startup overhead. Downloads have a five-minute absolute deadline. Nginx allows 120 seconds between upstream reads and 60 seconds of client write inactivity. Browser requests allow 400 seconds overall. A timeout or disconnect closes the response and releases its file and slot. An interrupted transfer must be requested again.

The service checks at least 1 GiB plus 96 MiB free on both the temporary-file and database filesystems. This bounds export disk consumption to one archive while preserving a reserve at admission. Other applications can consume that reserve independently. Linux enforces the file-size, memory, CPU and wall-clock limits in the child. Windows development has the parent deadline and size checks, without Linux resource limits.

`COURSE_EXPORT_ROOT` defaults to a private `uchebus-exports` directory under the OS temporary directory. Docker sets it to `/tmp/uchebus-exports` inside the web container. Keep it outside public media/static paths. Use the ASGI server included in the project so generation cancellation and asynchronous downloads operate correctly. There is no worker service or persistent artifact spool.

## Linux release-candidate verification

Use a disposable Linux Docker host with comparable RAM and CPU capacity. Keep the downloaded backup and all rehearsal output private. This procedure applies migrations only to a disposable backup copy.

1. Check out the release commit and build it. Run the focused suite with isolated container storage.

```bash
docker build -t uchebus-export-review .
docker run --rm --network none -e DB_DIR=/tmp \
  -e SECRET_KEY=isolated-export-review-key-only-2026 -e DEBUG=False \
  uchebus-export-review python manage.py test api.test_course_downloads api.test_course_export
```

2. Set `BACKUP_DIR` to the absolute path of the verified local backup. Create a private disposable database/media copy. The original backup remains available for comparison.

```bash
(cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS)
umask 077
REVIEW_DIR=$(mktemp -d /tmp/uchebus-review.XXXXXX)
mkdir "$REVIEW_DIR/db" "$REVIEW_DIR/media"
cp "$BACKUP_DIR/db.sqlite3" "$REVIEW_DIR/db/db.sqlite3"
tar --no-same-owner --no-same-permissions -xzf "$BACKUP_DIR/media.tar.gz" -C "$REVIEW_DIR/media"
docker run -d --name uchebus-export-review -p 127.0.0.1:18080:8000 \
  --mount "type=bind,src=$REVIEW_DIR/db,dst=/app/db" \
  --mount "type=bind,src=$REVIEW_DIR/media,dst=/app/media,readonly" \
  -e SECRET_KEY=isolated-export-review-key-only-2026 -e DEBUG=False \
  -e ALLOWED_HOSTS=localhost,127.0.0.1,uchebus.ru,www.uchebus.ru \
  -e COURSE_EXPORT_ROOT=/tmp/uchebus-exports \
  uchebus-export-review
docker exec uchebus-export-review python manage.py migrate --check
docker exec -it uchebus-export-review python manage.py createsuperuser
```

3. Use the temporary superuser in the isolated site at `http://127.0.0.1:18080`. For a remote rehearsal host, forward port 18080 over SSH. Select the 55-lesson, 873-step course from the November 22 backup. Generate MHTML, STEP ZIP, and author STEP ZIP three times, spacing attempts to respect the four-per-ten-minute limit. Record generation and total download time, archive sizes, peak memory, free disk, and any errors. Retain only aggregate measurements in the release report.
4. While generation is active, inspect the child's `/proc/<pid>/limits` and `/proc/<pid>/status` inside the container. Confirm 536870912-byte address space, 100663296-byte file size, 75 CPU seconds and zero core size. `VmPeak` measures virtual memory and `VmHWM` peak resident memory. Monitor `docker stats uchebus-export-review`, host `free -h`, and `df -h`. Repeat with representative runner load on this disposable host. A container-wide memory reading includes Django and the export child.
5. Start a second export during generation and during a deliberately slow download. Expect 429. Cancel the first request in each phase and verify another export can start, subject to the per-user rate limit. Verify the child exits, temporary disk usage returns, and no OOM kill occurs. The automated suite covers deadline and disconnect handling; successful representative builds must finish within 90 seconds with RAM headroom for the live VPS workload.
6. Open MHTML offline in Chrome and Edge and click syllabus entries. Check ZIP CRCs, 55 lesson manifests and 873 numbered steps. Confirm author materials appear only in the explicitly selected ZIP. Account for the documented external-image omissions separately from export failures.
7. Stop and remove only the rehearsal container with `docker rm -f uchebus-export-review`. Securely remove the disposable files after verifying the exact `REVIEW_DIR` path. Preserve the original backup. Record the image/commit, Linux results and capacity measurements before approving deployment.

## VPS deployment checklist

Deployment remains a separately approved operation. Use the existing project directory `/root/learning-platform` and Compose project `learning-platform`. Verify these names before following the commands.

1. Inspect `free -h`, `docker stats --no-stream`, `df -h`, and `df -i`. Check available RAM with the runner busy and disk space on the Docker writable-layer and DB-volume filesystems. Allow headroom for one 512 MiB child alongside Django, the 1 GiB runner, Nginx and the OS.
2. Record the current commit and web image ID. Run `scripts/backup.sh`, then `scripts/restore.sh --check "$BACKUP_NAME"` with the exact resulting folder name. Keep a verified off-server copy.
3. Fetch and fast-forward to the approved release commit. Keep the existing secrets, certificates and DB/media volumes. Remove any obsolete spool override and `COURSE_EXPORT_REQUIRE_SEPARATE_DEVICE` setting. No storage provisioning or new production dependency is required.
4. Build and validate the release before stopping the site.

```bash
cd /root/learning-platform
docker compose config --quiet
docker compose build web
bash scripts/test_restore.sh
docker compose run --rm --no-deps -T -e DB_DIR=/tmp web python manage.py test api.test_course_downloads api.test_course_export
docker compose run --rm --no-deps -T web python manage.py migrate --plan
```

5. During the approved maintenance window, stop web and remove a legacy worker container if one was previously installed. This prevents old code accessing the retired queue table.

```bash
docker compose stop web
legacy_worker=$(docker ps -aq --filter label=com.docker.compose.project=learning-platform --filter label=com.docker.compose.service=export-worker)
if [ -n "$legacy_worker" ]; then
    docker stop "$legacy_worker"
    docker rm "$legacy_worker"
fi
docker compose run --rm --no-deps -T web python manage.py migrate --noinput
docker compose run --rm --no-deps -T web python manage.py shell -c 'from api.course_export.downloads import check_capacity; check_capacity()'
docker compose up -d --no-deps web
docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload
curl -fsS --retry 10 --retry-delay 2 https://uchebus.ru/api/status/
docker compose exec -T web python manage.py migrate --check
docker compose logs --tail=50 web
```

6. Verify a paid-course download as its owner, deny a student, check busy-export behavior and cancellation, and open MHTML offline in Chrome and Edge. Observe peak RAM while the runner is active. Linux Docker resource enforcement and restore locking should also be rehearsed on a disposable Docker host before release.

Migration 0025 stays in history. Migration 0026 moves the existing export permission to Course while retaining its primary key and grants, then removes only the obsolete export-job table. Course, lesson, student and media records are unaffected. A database still at 0024 applies 0025 and 0026 in sequence. Existing queue rows are disposable and disappear.

For application rollback, stop web first. If the prior application expects the queue table, use the new image to run `python manage.py migrate api 0025` while web is stopped, then restore the recorded previous code/image and its compatible configuration. Reverse migration recreates an empty queue and moves the permission back, preserving grants. A pre-export application can run against the current course schema. Retain DB/media volumes. Data recovery uses the existing verified backup and interactive restore procedure, which replaces subsequent writes. Never use `docker compose down -v` as rollback.

The restore script retains its persistent maintenance marker, exclusive SQLite service lock, safety snapshot and integrity checks. It stops and resumes web. Unexpected containers mounting the DB volume cause restore to refuse replacement.

## External-resource findings

The November 22 production backup contains 161 distinct Stepik CDN image references (178 occurrences) and six distinct localhost image references. The inspected rich-text fields contain external images, with no external video/audio/player sources detected. Missing instructional images can prevent complete offline reading. Existing MHTML exports replace unavailable images with placeholders; structured exports retain original references and record null asset mappings.

For Stepik images, implement an explicit author-reviewed import that copies permitted images into uploaded media and rewrites references. Such an importer needs an allowlist, redirect/DNS checks, type and size limits, and a record of provenance. Export-time fetching would add network variability and SSRF exposure. None of the six localhost image paths matches a file in the downloaded media archive. Ask the author to supply these originals, then upload them and replace the references with relative media URLs. These content repairs are proposed separately and have not been applied to production.

## Administrative command

```sh
python manage.py export_course python-basics --format mhtml --output-dir ./exports
python manage.py export_course python-basics --format folder --output-dir ./exports
python manage.py export_course python-basics --format folder --author-materials --output-dir ./private-exports
```

The operator needs filesystem and database access. The command stages files beside the destination and refuses to overwrite an existing export. Author exports require a private destination outside media/static. CLI exports retain explicit operator-controlled output and do not use the dashboard download limits. Use a consistent database/media snapshot when concurrent editing matters.

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
