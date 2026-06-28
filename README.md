# Learning Platform

**[Русская версия](README.ru.md)**

> An interactive learning platform in the spirit of Stepik and Google Colab. Django + React, built so a single lesson can be embedded on any website through an iframe.

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0.3-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.16.1-red.svg)](https://www.django-rest-framework.org/)
[![Channels](https://img.shields.io/badge/Channels-4.3-purple.svg)](https://channels.readthedocs.io/)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![CodeMirror](https://img.shields.io/badge/CodeMirror-6-d30707.svg)](https://codemirror.net/)
[![JWT](https://img.shields.io/badge/Auth-JWT-orange.svg)](https://django-rest-framework-simplejwt.readthedocs.io/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg)](https://www.docker.com/)

---

## What it does

Authors build courses out of blocks: theory text, quizzes, and coding exercises. Students work through the lessons one block at a time. A finished lesson can be dropped into any page with an `<iframe>`.

An author can:

* Create and edit courses, lessons, and blocks, building the blocks visually in the browser (no HTML file needed)
* Import lessons from HTML files when there's a lot to bring in at once
* Give students access by enrolling them
* See each student's progress and overall stats
* Look back at every submission a student has made, including the wrong ones, with timestamps down to the second and the exact code they ran
* Talk to each student in a live chat

A student can:

* Read theory with syntax-highlighted code samples
* Answer quizzes, get immediate feedback, and retry after a wrong answer
* Write and run Python in a PyCharm-style editor (CodeMirror 6 with the Darcula theme: keyword coloring, bracket matching, highlighted built-ins)
* Follow their own progress through a course
* Chat with the teacher in real time

---

## Project layout

```
learning-platform/
├── backend/                  # Django project settings
│   ├── settings.py           # ASGI + Channels configured
│   └── asgi.py               # ProtocolTypeRouter: HTTP → Django, WS → ChatConsumer
├── api/                      # Main app
│   ├── models.py             # User, Course, Lesson, Block, Enrollment, Progress, Attempt, Message
│   ├── serializers.py        # JSON serializers
│   ├── views.py              # REST views + code execution + progress + message history
│   ├── urls.py               # HTTP URL routing
│   ├── consumers.py          # ChatConsumer (WebSocket) — real-time messaging
│   ├── routing.py            # WebSocket URL patterns
│   ├── ws_auth.py            # JWT middleware for WebSocket query-string token
│   ├── permissions.py        # IsAuthor, IsOwnerOrReadOnly
│   └── management/
│       └── commands/
│           └── import_lesson.py   # HTML → database importer
├── frontend/                 # React app (Vite)
│   └── src/
│       ├── api.js            # Axios client with JWT auth + refresh interceptor
│       ├── App.jsx           # Routing for all pages
│       ├── pages/
│       │   ├── LoginPage.jsx
│       │   ├── RegisterPage.jsx
│       │   ├── DashboardPage.jsx        # Role-based dashboard
│       │   ├── CoursePage.jsx           # Author/student views + WebSocket chat
│       │   ├── StudentProgressPage.jsx  # Per-student progress + expandable attempt history
│       │   ├── LessonViewer.jsx         # Reads lesson ID from URL, WebSocket chat with teacher
│       │   └── LessonEditor.jsx         # Author: visual block editor (add/edit/delete/reorder)
│       ├── components/
│       │   ├── TextBlock.jsx
│       │   ├── QuizBlock.jsx
│       │   ├── CodeBlock.jsx          # CodeMirror 6 editor with PyCharm Darcula theme
│       │   ├── FillBlock.jsx          # Fill-in-the-blanks task (auto-growing inputs)
│       │   ├── pycharmDarcula.js      # Theme + Python built-ins highlighter
│       │   ├── RichTextEditor.jsx     # TipTap WYSIWYG editor (TEXT/QUIZ/CODE) + image upload
│       │   ├── RichTextEditor.css     # Toolbar + prose styling for the editor
│       │   └── UserBadge.jsx          # Fixed top-right "who am I" avatar + menu
│       └── lib/
│           ├── pythonHighlight.js   # Shared highlight.js code-block highlighter
│           └── fillTemplate.js      # Parses {{answer}} blanks for FILL blocks
├── Dockerfile                # Multi-stage build: Node → Python
├── docker-compose.yml        # One-command launch
├── .dockerignore
├── fixtures.json             # Test data (users, courses, lessons, blocks)
├── requirements.txt          # Includes channels + daphne
└── manage.py
```

---

## Block system

A lesson is a list of blocks. There are four kinds:

| Type | Description                | Content stored as                                                                      |
|------|----------------------------|----------------------------------------------------------------------------------------|
| TEXT | Theory with HTML formatting | `{"html": "<p>...</p>"}`                                                              |
| QUIZ | Multiple choice question   | `{"question": "...", "options": [...], "correct_answer": 0, "explanation": "..."}`    |
| CODE | Python coding exercise     | `{"prompt": "...", "starter_code": "...", "tests": [...]}`                            |
| FILL | Fill-in-the-blanks task    | `{"prompt": "...", "template": "print({{8}})", "case_sensitive": false}`              |

Code blocks run on CodeMirror 6 with a hand-built PyCharm Darcula theme ([frontend/src/components/pycharmDarcula.js](frontend/src/components/pycharmDarcula.js)):

* Orange keywords (`if`, `def`, `and`, `True`)
* Green strings, blue numbers, purple built-ins (`print`, `input`, `len`, `range`, and about 60 others, picked out by a ViewPlugin that walks the syntax tree)
* JetBrains Mono, dark `#2B2B2B` background
* Bracket matching, indent-on-input, tab-to-indent
* CodeMirror's own line numbers and active-line gutter highlight

---

## Visual block editor

Authors put a lesson together block by block right in the browser. No HTML file, no `import_lesson` call. The HTML importer is still there for bulk imports, but day-to-day authoring happens in the UI.

To open it, go to a course page: every lesson row has an Edit button (authors only) that opens the editor at `/lesson/<lesson-uuid>/edit/`. A Preview button next to it jumps to the normal student view.

In the editor you can:

* Add a block of any type — Theory (TEXT), Quiz (QUIZ), Code task (CODE), or Fill in the blanks (FILL)
* Edit any existing block in place
* Delete a block, with a confirmation
* Move blocks up and down

Each block type has its own form:

| Type | Editing UI |
|------|------------|
| TEXT | A WYSIWYG editor (TipTap): bold, italic, H2/H3, bullet and numbered lists, inline code, code block, quote. The teacher never touches raw HTML; the editor produces the `{"html": ...}` that gets stored. Code blocks become `<pre><code>` and are highlighted automatically in the lesson viewer. It also handles image upload (toolbar button, paste, or drag-and-drop) and undo/redo. |
| QUIZ | The question uses the same rich editor, with a dynamic list of options, a radio button to mark the correct one, and an explanation shown on a correct answer. Empty options are dropped on save and `correct_answer` is reindexed for you. |
| CODE | A rich-text task description, `starter_code`, and an optional hidden solution (both in the same CodeMirror + PyCharm Darcula editor the student sees), plus a tests table (stdin → expected stdout). Blank test rows are ignored. |
| FILL | A rich-text description plus a template where blanks are written inline as `{{answer}}` (alternatives separated by `\|`, e.g. `print({{math.factorial(8)\|factorial(8)}})`). A live preview shows the fixed text and the accepted answers. A case-sensitive toggle and an explanation are optional. |

A few implementation notes:

* Files: [frontend/src/pages/LessonEditor.jsx](frontend/src/pages/LessonEditor.jsx), [frontend/src/components/RichTextEditor.jsx](frontend/src/components/RichTextEditor.jsx) (+ `.css`), [frontend/src/components/FillBlock.jsx](frontend/src/components/FillBlock.jsx), [frontend/src/lib/fillTemplate.js](frontend/src/lib/fillTemplate.js), [frontend/src/lib/pythonHighlight.js](frontend/src/lib/pythonHighlight.js).
* The editor talks to the existing DRF `BlockViewSet` (`POST` / `PUT` / `PATCH` / `DELETE /api/blocks/`). `BlockSerializer` checks the required fields for each block type and returns `400` on bad content. Access is author-only through the existing `IsAuthor` / `IsOwnerOrReadOnly` permissions.
* Image upload: `POST /api/upload-image/` (author-only) saves to `MEDIA_ROOT/lesson_images/` and returns an absolute URL that the editor drops in as an `<img>`. Served from `/media/`, kept in a Docker volume.
* FILL grading happens on the server in `ProgressSubmitView` (`grade_fill()` trims, optionally folds case, and requires every blank to match). The viewer also grades on the client for instant feedback. The blank inputs grow as the student types.
* Ordering and the unique constraint: `Block` has `unique_together (lesson, order_index)`. New blocks use `max(order_index) + 1` rather than count + 1, so gaps left by deletions never collide. Reordering swaps two blocks through a temporary free index so the constraint isn't violated mid-swap. Lesson creation on the course page follows the same `max + 1` rule.

---

## Real-time chat (WebSockets)

Teacher and student chat over Django Channels WebSockets, so messages show up instantly with no polling and no refresh.

* Backend: ASGI server (Daphne) + Channels 4. The WebSocket endpoint is `ws/chat/<course_id>/<other_user_id>/?token=<jwt>`.
* Auth: browsers can't set an Authorization header on a WebSocket handshake, so the JWT access token rides along in the query string. A small middleware ([api/ws_auth.py](api/ws_auth.py)) validates it and attaches the User to the connection scope.
* Rooms: the group name comes from the sorted `(user_id_A, user_id_B)` pair within a course, so both sides land in the same room no matter who connected first. Strangers and student-to-student pairings are rejected with WebSocket close code 4003.
* Channel layer: `InMemoryChannelLayer` in development, so there's nothing extra to run. For production, switch to `channels_redis` + Redis.
* Persistence: message history is still served by the existing HTTP endpoint, loaded once when the chat opens. The WebSocket only carries new messages.

---

## Attempt history

Every QUIZ and CODE submission is logged in the `Attempt` table. That's separate from `Progress`, which still keeps only the latest answer and a counter.

* On a student's progress page, click the `попыток: N` pill next to a task to expand the full submission history.
* Each entry has a timestamp down to the second (`DD.MM.YYYY HH:MM:SS`) and a correct/incorrect marker.
* Click an individual attempt to see what was submitted: for CODE blocks, the code is shown with the same CodeMirror PyCharm Darcula theme as the editor; for QUIZ blocks, the option number that was chosen.

---

## Authentication and roles

JWT auth with two roles:

* AUTHOR — create, edit, and delete their own courses, lessons, and blocks
* STUDENT — view published courses, enroll, and submit answers

Access tokens last 7 days, refresh tokens 30. The axios interceptor in [frontend/src/api.js](frontend/src/api.js) refreshes the access token on a 401 and retries the original request. Only if the refresh itself fails does it clear the session.

---

## Embedding via iframe

Django serves each lesson at `/lesson/<uuid>/`. React reads the UUID from the URL and loads the lesson over the API. The route carries `@xframe_options_exempt`, so it can sit inside an iframe on another site.

```html
<iframe
  src="http://your-server/lesson/<lesson-uuid>/"
  width="100%"
  height="700px"
  frameborder="0">
</iframe>
```

There's an `iframe_test.html` in the repo root for trying this locally.

---

## Getting started

You'll need [Docker Desktop](https://www.docker.com/products/docker-desktop/).

1. Clone and start:

```bash
git clone https://github.com/EugeneMorrison/learning-platform.git
cd learning-platform
docker-compose up --build
```

Docker takes care of the rest:
- Installs the Python and Node dependencies (Channels and Daphne included)
- Builds the React frontend
- Runs database migrations
- Loads the test data (users, courses, lessons, blocks)
- Starts the ASGI server on port 8000

2. Open the lesson in the browser:

```
http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/
```

3. Try the iframe embed:

Open `iframe_test.html` from the project root (double-click it in File Explorer). It loads the same lesson inside an `<iframe>`, which is how the platform is meant to be used on other sites.

To stop: `Ctrl+C` in the terminal, then `docker-compose down`.

Later runs, with no code changes: `docker-compose up` — drop `--build` and it reuses the cached image.

---

## Manual setup (without Docker)

Docker is the easy path, but you can run everything by hand. You'll need:

* Python 3.12+ — [python.org](https://www.python.org/downloads/)
* Node.js 20+ — [nodejs.org](https://nodejs.org/), needed to build the React frontend

> Note: `frontend/dist/` is gitignored because it's a build artifact. On a fresh clone it doesn't exist yet, so Django can't serve the frontend until you build it. Running only the Django steps gives you a `staticfiles.W004` warning and a blank lesson page. Docker builds the frontend for you; the manual flow doesn't.

1. Backend — Python dependencies:

```bash
python -m venv venv
venv\Scripts\activate           # Windows (PowerShell/CMD)
# source venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
```

2. Frontend — build the React app (this is the step people forget):

```bash
cd frontend
npm install
npm run build
cd ..
```

That creates `frontend/dist/`, which Django uses both as a template directory (for `index.html`) and as a static files directory (for the JS/CSS bundles).

3. Django — migrations, fixtures, server:

```bash
python manage.py migrate
python manage.py loaddata fixtures.json
python manage.py runserver
```

> The startup log should read "Starting ASGI/Daphne version 4.x development server". That's how you know WebSockets are wired up. If it says "Starting development server" (WSGI) instead, check that `daphne` is listed first in `INSTALLED_APPS`.

4. Open it — Django serves on port 8000:

```
http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/
http://localhost:8000/login/
http://localhost:8000/admin/
```

> Don't open `http://127.0.0.1:5173/`. That's the Vite dev server port, and it only runs if you separately start `npm run dev` inside `frontend/`. For plain manual setup, everything comes from Django on port 8000.

Re-running after changes:

* Backend (Python) — just restart `python manage.py runserver`.
* Frontend (React) — re-run `npm run build` in `frontend/`, then refresh. Or run `npm run dev` on port 5173 for hot reload while you're actively working, though API and WebSocket calls still go to Django on 8000.

---

## Which port am I using? (8000 vs 5173)

This is the part people get stuck on. There are two servers, each with its own job:

| Port | Server | What it does | When it runs |
|------|--------|--------------|--------------|
| 8000 | Django | Backend: REST API, database, WebSocket chat, media. Also serves the built frontend. | Always (your `runserver` / PyCharm). |
| 5173 | Vite | Frontend dev server (React UI) with instant hot reload. Talks to Django on 8000 for all data. | Only while `npm run dev` is running. |

Two ways to run it:

A) Dev mode (handy while coding) — two terminals, open `:5173`

Terminal 1, backend:
```bash
python manage.py runserver        # → http://localhost:8000  (banner must say "Starting ASGI/Daphne")
```
Terminal 2, frontend:
```bash
cd frontend
npm run dev                       # → http://localhost:5173
```
Then open `http://localhost:5173/`. Editing a React file updates the page instantly. API and chat calls still go to Django on 8000 in the background.

B) Production-style — one server, open `:8000`

Build the frontend once and let Django serve everything:
```bash
cd frontend && npm run build && cd ..
python manage.py runserver        # → open http://localhost:8000/
```
No hot reload here — re-run `npm run build` after each frontend change.

When something looks broken:

* `localhost:5173` won't load but `8000` works → Vite isn't running. Start `npm run dev`.
* `5173` loads pages but login / data / chat fail → Django isn't running, or not on 8000.
* Chat in particular is dead → make sure exactly one `runserver` is up and its banner says "Starting ASGI/Daphne". Kill any stray `runserver` sitting on port 8000 (on Windows: `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*runserver*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`).

---

### Import a lesson from HTML

```bash
python manage.py import_lesson path/to/lesson.html --course-id <uuid> --order 1
```

---

## API endpoints

### Auth

```
POST   /api/auth/register/          Register new user
POST   /api/auth/login/             Login, get JWT tokens
POST   /api/auth/token/refresh/     Refresh access token
GET    /api/auth/me/                Current user info
```

### Courses and lessons

```
GET    /api/courses/                List published courses
POST   /api/courses/                Create course (author only)
GET    /api/courses/{id}/           Course detail
PUT    /api/courses/{id}/           Update course (author only)
DELETE /api/courses/{id}/           Delete course (author only)
GET    /api/lessons/?course={id}    List lessons in a course
POST   /api/lessons/                Create lesson (author only)
GET    /api/lessons/{id}/           Lesson detail
DELETE /api/lessons/{id}/           Delete lesson (author only)
```

### Blocks (used by the visual block editor)

```
GET    /api/blocks/?lesson={id}     List blocks in a lesson
POST   /api/blocks/                 Create block (author only)
PUT    /api/blocks/{id}/            Replace block content/type/order (author only)
PATCH  /api/blocks/{id}/            Partial update, e.g. order_index (author only)
DELETE /api/blocks/{id}/            Delete block (author only)
```

### Enrollment

```
GET    /api/enrollments/                    My enrollments
POST   /api/enrollments/                    Enroll in a course
DELETE /api/enrollments/{course_id}/        Unenroll
```

### Progress

```
POST   /api/progress/submit/                              Submit block answer (also writes an Attempt row)
GET    /api/progress/course/{id}/                         Progress for a course
GET    /api/progress/stats/                               Overall statistics
GET    /api/progress/student/{student_id}/course/{id}/    Per-student progress with full attempt history
```

### Code execution

```
POST   /api/run-code/               Run Python code, get stdout/stderr
POST   /api/run-tests/              Run code against test cases, get pass/fail
POST   /api/upload-image/           Upload a lesson image (author only) → returns URL
```

### Author tools

```
GET    /api/courses/my_courses/                            Author's own courses
POST   /api/courses/{id}/enroll_student/                   Enroll student by username
```

### Messaging (history)

```
GET    /api/messages/?course={id}              Message history for a course
POST   /api/messages/                          (Legacy HTTP send — kept for compatibility)
```

### WebSocket — real-time chat

```
ws://host/ws/chat/{course_id}/{other_user_id}/?token={jwt_access_token}
```

Send a message: client → server JSON `{"text": "..."}`.
Receive messages: server → client serialized `Message` JSON, broadcast to both participants the moment it's saved.

---

## Frontend routes

```
/login/                                    Login form
/register/                                 Registration with role selector (Student/Author)
/dashboard/                                Role-based dashboard
/courses/:courseId/                        Course detail (author/student views)
/courses/:courseId/students/:studentId/    Author: per-student progress with attempt history
/lesson/:lessonId/                         Lesson viewer
/lesson/:lessonId/edit/                     Author: visual block editor
```

* Author dashboard: lists your courses (from `/api/courses/my_courses/`) with an inline "Create Course" form.
* Student dashboard: lists enrolled courses with their enrollment dates.
* Author course page: the lessons list (each with Edit and Delete), an add-lesson form, and a students list with Progress and Chat buttons. Chat opens a WebSocket scoped to that student.
* Lesson editor (author): add, edit, delete, and reorder TEXT, QUIZ, and CODE blocks with per-type forms and a WYSIWYG editor for theory. Preview opens the student view.
* Student progress page: completion %, tasks done, quizzes correct, and a per-lesson breakdown. Each task shows a `попыток: N` pill; click it for the full submission history with timestamps, then click an attempt to see the submitted code or answer with syntax highlighting.
* Lesson viewer: the PyCharm-style CodeMirror editor for code tasks, plus a floating chat bubble wired to the teacher over WebSocket.

---

## Tech stack

### Backend

| Package                          | Purpose                                  |
|----------------------------------|------------------------------------------|
| Django 6.0.3                     | Web framework                            |
| Django REST Framework 3.16.1     | API toolkit                              |
| djangorestframework-simplejwt    | JWT authentication                       |
| Channels 4.3.2                   | WebSocket / ASGI support                 |
| Daphne 4.2.2                     | ASGI server (replaces runserver default) |
| django-cors-headers              | Cross-origin requests                    |
| django-filter                    | Search and filtering                     |
| BeautifulSoup4                   | HTML lesson importer                     |

### Frontend

| Package                  | Purpose                                  |
|--------------------------|------------------------------------------|
| React 19                 | UI framework                             |
| Vite 8                   | Build tool                               |
| Axios                    | HTTP client (with JWT refresh interceptor)|
| @uiw/react-codemirror    | CodeMirror 6 React wrapper               |
| @codemirror/lang-python  | Python syntax parser                     |
| @tiptap/react + starter-kit | WYSIWYG rich-text editor for TEXT blocks |
| highlight.js             | Syntax highlighting for read-only theory blocks |

### Infrastructure

| Tool           | Purpose                          |
|----------------|----------------------------------|
| Docker         | Containerization                 |
| docker-compose | Multi-container orchestration    |
| SQLite         | Database                         |
| InMemory layer | Channels message broker (dev — switch to Redis for production) |

---

## Test users

Loaded automatically from `fixtures.json` (both with Docker and with `loaddata`):

| Username     | Role    | Password    |
|--------------|---------|-------------|
| admin        | Admin   | (set yours) |
| john_author  | AUTHOR  | password123 |
| alice        | STUDENT | password123 |

Test lesson URL: `http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/`

> To try the chat as two people, open Alice's view in an incognito window or a different browser profile. The same browser shares `localStorage` across tabs, so otherwise both tabs end up logged in as the same user.

---

## Project progress

| Step | Feature                                          | Status |
|------|--------------------------------------------------|--------|
| 1    | Basic API setup                                  | Done   |
| 2    | Database models                                  | Done   |
| 3    | Serializers + CRUD                               | Done   |
| 4    | JWT authentication                               | Done   |
| 5    | Permissions + roles                              | Done   |
| 6    | Validation + filtering                           | Done   |
| 7    | Block system + HTML importer                     | Done   |
| 8    | Enrollment API                                   | Done   |
| 9    | Progress tracking API                            | Done   |
| 10   | React frontend — lesson viewer                   | Done   |
| 11   | iframe embedding                                 | Done   |
| 12   | Docker                                           | Done   |
| 13   | Management dashboard + messaging                 | Done   |
| 14   | PyCharm-style code editor (CodeMirror + Darcula) | Done   |
| 15   | Real-time chat via WebSockets (Channels + Daphne)| Done   |
| 16   | Full attempt history (per-submission timestamps + answer viewer) | Done   |
| 17   | In-app visual block editor (WYSIWYG TEXT, QUIZ & CODE forms, reorder) | Done   |
| 18   | Image upload in blocks + fill-in-the-blanks (FILL) task type | Done   |

---

Built with Django, React, and Channels. [View on GitHub](https://github.com/EugeneMorrison/learning-platform).
