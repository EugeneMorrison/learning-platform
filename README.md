# 🎓 Learning Platform

**[Русская версия](README.ru.md)**

> An interactive learning platform inspired by Stepik and Google Colab. Built with Django + React, designed to be embedded on external websites via iframe.

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0.3-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.16.1-red.svg)](https://www.django-rest-framework.org/)
[![Channels](https://img.shields.io/badge/Channels-4.3-purple.svg)](https://channels.readthedocs.io/)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![CodeMirror](https://img.shields.io/badge/CodeMirror-6-d30707.svg)](https://codemirror.net/)
[![JWT](https://img.shields.io/badge/Auth-JWT-orange.svg)](https://django-rest-framework-simplejwt.readthedocs.io/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg)](https://www.docker.com/)

---

## 📋 What It Does

Authors create courses made of **blocks** — theory text, quizzes, and coding exercises. Students work through lessons interactively. The platform can be embedded on any website using a simple `<iframe>` tag.

**Author can:**

* Create and edit courses, lessons, and blocks — **building blocks visually in the browser, no HTML file required**
* Import lessons from HTML files automatically (for bulk imports)
* Give students access via enrollment
* View student progress and statistics
* Inspect **every submission a student ever made** — including wrong attempts, with timestamps to the second and the actual code they wrote
* Chat with each student in real time

**Student can:**

* Read theory blocks with syntax-highlighted code examples
* Answer quiz questions with instant feedback and retry on wrong answers
* Write and run Python code in a **PyCharm-style editor** (CodeMirror 6 with Darcula theme — keyword coloring, bracket matching, Python built-in highlighting)
* Track their progress through lessons
* Chat with the teacher in real time

---

## 🏗️ Architecture

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

## 🧱 Block System

Each lesson is made of blocks. Four types are supported:

| Type | Description                | Content stored as                                                                      |
|------|----------------------------|----------------------------------------------------------------------------------------|
| TEXT | Theory with HTML formatting | `{"html": "<p>...</p>"}`                                                              |
| QUIZ | Multiple choice question   | `{"question": "...", "options": [...], "correct_answer": 0, "explanation": "..."}`    |
| CODE | Python coding exercise     | `{"prompt": "...", "starter_code": "...", "tests": [...]}`                            |
| FILL | Fill-in-the-blanks task    | `{"prompt": "...", "template": "print({{8}})", "case_sensitive": false}`              |

**Code blocks** use **CodeMirror 6** with a custom **PyCharm Darcula** theme (`frontend/src/components/pycharmDarcula.js`):

* Orange keywords (`if`, `def`, `and`, `True`)
* Green strings, blue numbers, purple Python built-ins (`print`, `input`, `len`, `range`, ~60 others detected via a syntax-tree-aware ViewPlugin)
* JetBrains Mono font, dark `#2B2B2B` background
* Bracket matching, indent-on-input, tab-to-indent
* Native CodeMirror line numbers and active-line gutter highlight

---

## ✏️ Visual Block Editor

Authors build a lesson **block by block directly in the browser** — no HTML file and no `import_lesson` command needed. The HTML importer stays available for bulk imports, but everyday authoring happens in the UI.

**How to open it:** on a course page, every lesson row has an **✎ Редактировать (Edit)** button (authors only). It opens the editor at `/lesson/<lesson-uuid>/edit/`. A **👁 Предпросмотр (Preview)** button jumps to the normal student view.

**In the editor you can:**

* **Add** a block of any type — 📝 Theory (TEXT), ❓ Quiz (QUIZ), 💻 Code task (CODE), ✍️ Fill in the blanks (FILL)
* **Edit** any existing block in place
* **Delete** a block (with confirmation)
* **Reorder** blocks with ↑ / ↓ buttons

**Per-type editing forms:**

| Type | Editing UI |
|------|------------|
| TEXT | **WYSIWYG rich-text editor** (TipTap) — bold, italic, H2/H3, bullet & numbered lists, inline code, code block, quote. The teacher never writes raw HTML; the editor produces the `{"html": ...}` stored in the block. Code blocks become `<pre><code>` and are auto-highlighted in the lesson viewer. Supports **image upload** (toolbar button, paste, or drag-and-drop) and **undo/redo**. |
| QUIZ | WYSIWYG question (same rich editor), a dynamic list of options with a radio button to mark the correct one, and an explanation shown on a correct answer. Empty options are dropped on save and `correct_answer` is reindexed automatically. |
| CODE | Rich-text task description, `starter_code` and an optional **hidden solution** (both in the same CodeMirror + PyCharm Darcula editor as the student side), and a tests table (stdin → expected stdout). Blank test rows are ignored. |
| FILL | Rich-text description plus a **template** where blanks are written inline as `{{answer}}` (alternatives via `\|`, e.g. `print({{math.factorial(8)\|factorial(8)}})`). A **live preview** shows the fixed text and the accepted answers; a *case-sensitive* toggle and explanation are optional. |

**Implementation notes:**

* Files: `frontend/src/pages/LessonEditor.jsx`, `frontend/src/components/RichTextEditor.jsx` (+ `.css`), `frontend/src/components/FillBlock.jsx`, `frontend/src/lib/fillTemplate.js`, `frontend/src/lib/pythonHighlight.js`.
* The editor drives the existing DRF `BlockViewSet` (`POST` / `PUT` / `PATCH` / `DELETE /api/blocks/`). `BlockSerializer` validates the required fields per block type and returns `400` on invalid content. Access is author-only via the existing `IsAuthor` / `IsOwnerOrReadOnly` permissions.
* **Image upload:** `POST /api/upload-image/` (author-only) saves to `MEDIA_ROOT/lesson_images/` and returns an absolute URL that the editor inserts as `<img>`. Served from `/media/` (persisted via a Docker volume).
* **FILL grading:** fill-in-the-blanks answers are checked **server-side** in `ProgressSubmitView` (`grade_fill()` — trims, optional case-fold, all blanks must match); the viewer also grades client-side for instant feedback. Blanks auto-grow as the student types.
* **Ordering & the unique constraint:** `Block` has `unique_together (lesson, order_index)`. New blocks use `max(order_index) + 1` (not count + 1), so gaps left by deletions never collide. Reordering swaps two blocks through a temporary free index to avoid violating the constraint mid-swap. Lesson creation on the course page uses the same `max + 1` rule.

---

## 💬 Real-Time Chat (WebSockets)

Teacher↔student chat is delivered over **Django Channels** WebSockets — messages appear instantly with no polling and no refresh.

* **Backend:** ASGI server (Daphne) + Channels 4. WebSocket endpoint at `ws/chat/<course_id>/<other_user_id>/?token=<jwt>`.
* **Auth:** browsers can't add Authorization headers to WebSocket handshakes, so the JWT access token is passed in the query string. A custom middleware (`api/ws_auth.py`) validates it and attaches the User to the connection scope.
* **Rooms:** group name is derived from the sorted `(user_id_A, user_id_B)` pair within a course — both sides end up in the same room regardless of who connected first. Strangers and student↔student combinations are rejected with WebSocket close code 4003.
* **Channel layer:** `InMemoryChannelLayer` in development (no extra infrastructure). For production, swap to `channels_redis` + Redis.
* **Persistence:** message history is still served by the existing HTTP endpoint (loaded once when the chat opens). The WebSocket only streams new messages.

---

## 📊 Attempt History

Every QUIZ and CODE submission is logged in the new `Attempt` table — separate from `Progress`, which still only stores the latest answer and a counter.

* The author opens a student's progress page and clicks the **`▶ попыток: N`** pill next to any task to expand the full submission history.
* Each entry shows a timestamp to the second (`DD.MM.YYYY HH:MM:SS`) and a ✓/✗ correctness indicator.
* Click any individual attempt to reveal the actual content: for CODE blocks, the submitted code is rendered with the **same CodeMirror PyCharm Darcula theme** as the editor; for QUIZ blocks, the selected option number.

---

## 🔐 Authentication & Roles

JWT-based authentication with two roles:

* **AUTHOR** — can create/edit/delete their own courses, lessons, blocks
* **STUDENT** — can view published courses, enroll, submit answers

Access tokens last 7 days, refresh tokens 30 days. The axios interceptor in `frontend/src/api.js` automatically refreshes the access token on 401 and retries the original request — only if the refresh itself fails does it clear the session.

---

## 🔗 Embedding via iframe

Each lesson is served at `/lesson/<uuid>/` by Django. React reads the UUID from the URL and loads the lesson via API. The route is decorated with `@xframe_options_exempt` so it can be embedded on external websites.

```html
<iframe
  src="http://your-server/lesson/<lesson-uuid>/"
  width="100%"
  height="700px"
  frameborder="0">
</iframe>
```

A test file `iframe_test.html` is included in the repo root for local testing.

---

## 🚀 Getting Started

To install/run [Docker Desktop](https://www.docker.com/products/docker-desktop/).

**1. Clone and start:**

```bash
git clone https://github.com/EugeneMorrison/learning-platform.git
cd learning-platform
docker-compose up --build
```

Docker automatically handles everything:
- Installs all Python and Node dependencies (including Channels + Daphne)
- Builds the React frontend
- Runs database migrations
- Loads test data (users, courses, lessons, blocks)
- Starts the ASGI server on port 8000

**2. Open the lesson directly in the browser:**

```
http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/
```

**3. Test iframe embedding:**

Open `iframe_test.html` from the project root in your browser (double-click it in File Explorer). It loads the same lesson inside an `<iframe>` — this is how the platform is meant to be used on external websites.

**To stop:** `Ctrl+C` in the terminal, then `docker-compose down`

**Next runs** (no code changes): `docker-compose up` — no `--build` needed, uses cached image.

---

## 🛠️ Manual Setup (without Docker)

Docker is recommended, but the project can also be run manually. You'll need:

* **Python 3.12+** — [python.org](https://www.python.org/downloads/)
* **Node.js 20+** — [nodejs.org](https://nodejs.org/) (required to build the React frontend)

> ⚠️ **Important:** `frontend/dist/` is gitignored (it's a build artifact). On a fresh clone it doesn't exist, so Django can't serve the frontend until you build it. Running only the Django steps will give a `staticfiles.W004` warning and a blank lesson page. The Docker flow builds the frontend automatically — the manual flow does not.

**1. Backend — Python dependencies:**

```bash
python -m venv venv
venv\Scripts\activate           # Windows (PowerShell/CMD)
# source venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
```

**2. Frontend — build the React app** (this is the step that's easy to miss):

```bash
cd frontend
npm install
npm run build
cd ..
```

This creates `frontend/dist/`, which Django reads as both a template directory (for `index.html`) and a static files directory (for JS/CSS bundles).

**3. Django — migrations, fixtures, server:**

```bash
python manage.py migrate
python manage.py loaddata fixtures.json
python manage.py runserver
```

> The startup log should say **"Starting ASGI/Daphne version 4.x development server"** — that confirms WebSockets are wired up. If it instead says "Starting development server" (WSGI), check that `daphne` is listed first in `INSTALLED_APPS`.

**4. Open in the browser** — Django serves on port **8000**:

```
http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/
http://localhost:8000/login/
http://localhost:8000/admin/
```

> ❗ Do **not** open `http://127.0.0.1:5173/` — that's the Vite dev server port and is only active if you separately run `npm run dev` inside `frontend/`. For normal manual setup everything is served by Django on **port 8000**.

**Re-running after code changes:**

* Backend changes (Python) — just restart `python manage.py runserver`.
* Frontend changes (React) — re-run `npm run build` inside `frontend/`, then refresh the browser. (Or use `npm run dev` on port 5173 for hot reload during active development — but API and WebSocket calls still go to Django on 8000.)

---

## 🔌 Which port do I use? (Dev workflow: 8000 vs 5173)

This trips everyone up. There are **two servers**, each with its own job:

| Port | Server | What it does | When it runs |
|------|--------|--------------|--------------|
| **8000** | **Django** | Backend: REST API, database, WebSocket chat, media. Also serves the **built** frontend. | Always (your `runserver` / PyCharm). |
| **5173** | **Vite** | Frontend dev server (React UI) with **instant hot-reload**. Talks to Django on 8000 for all data. | Only while `npm run dev` is running. |

**Two ways to run the app:**

**A) Dev mode (recommended while coding) — two terminals, open `:5173`**

Terminal 1 — backend:
```bash
python manage.py runserver        # → http://localhost:8000  (banner must say "Starting ASGI/Daphne")
```
Terminal 2 — frontend:
```bash
cd frontend
npm run dev                       # → http://localhost:5173
```
Then **open `http://localhost:5173/`**. Editing a React file updates the page instantly. API and chat calls still go to Django on 8000 behind the scenes.

**B) Production-style — one server, open `:8000`**

Build the frontend once, then Django serves everything itself:
```bash
cd frontend && npm run build && cd ..
python manage.py runserver        # → open http://localhost:8000/
```
No hot-reload — re-run `npm run build` after each frontend change.

**Rule of thumb when something seems broken:**

* `localhost:5173` won't load but `8000` works → **Vite isn't running.** Start `npm run dev`.
* `5173` loads pages but login / data / chat fail → **Django isn't running** (or not on 8000).
* Chat specifically dead → make sure **only one** `runserver` is running and its banner says **"Starting ASGI/Daphne"**. Kill any stray `runserver` processes squatting port 8000 (`Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*runserver*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }` on Windows).

---

### Import a Lesson from HTML

```bash
python manage.py import_lesson path/to/lesson.html --course-id <uuid> --order 1
```

---

## 🎯 API Endpoints

### Auth

```
POST   /api/auth/register/          Register new user
POST   /api/auth/login/             Login, get JWT tokens
POST   /api/auth/token/refresh/     Refresh access token
GET    /api/auth/me/                Current user info
```

### Courses & Lessons

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

### Code Execution

```
POST   /api/run-code/               Run Python code, get stdout/stderr
POST   /api/run-tests/              Run code against test cases, get pass/fail
POST   /api/upload-image/           Upload a lesson image (author only) → returns URL
```

### Author Tools

```
GET    /api/courses/my_courses/                            Author's own courses
POST   /api/courses/{id}/enroll_student/                   Enroll student by username
```

### Messaging (history)

```
GET    /api/messages/?course={id}              Message history for a course
POST   /api/messages/                          (Legacy HTTP send — kept for compatibility)
```

### WebSocket — Real-Time Chat

```
ws://host/ws/chat/{course_id}/{other_user_id}/?token={jwt_access_token}
```

Send a message: client → server JSON `{"text": "..."}`.
Receive messages: server → client serialized `Message` JSON, broadcast to both participants the moment it's saved.

---

## 🖥️ Frontend Routes

```
/login/                                    Login form
/register/                                 Registration with role selector (Student/Author)
/dashboard/                                Role-based dashboard
/courses/:courseId/                        Course detail (author/student views)
/courses/:courseId/students/:studentId/    Author: per-student progress with attempt history
/lesson/:lessonId/                         Lesson viewer
/lesson/:lessonId/edit/                     Author: visual block editor
```

**Author dashboard:** lists own courses (from `/api/courses/my_courses/`), inline "Create Course" form.
**Student dashboard:** lists enrolled courses with enrollment dates.
**Author course page:** lessons list (each with **✎ Edit** and **Delete** buttons), add-lesson form, students list with **Progress** and **💬 Chat** buttons. Chat opens a WebSocket connection scoped to that student.
**Lesson editor (author):** add/edit/delete/reorder TEXT, QUIZ and CODE blocks with per-type forms and a WYSIWYG editor for theory; **👁 Preview** opens the student view.
**Student progress page:** completion %, tasks done, quizzes correct, plus per-lesson breakdown. Each task shows a `▶ попыток: N` pill — click it to expand the full submission history with timestamps; click any attempt to view the submitted code/answer in a syntax-highlighted viewer.
**Lesson viewer:** PyCharm-style CodeMirror editor for code tasks, floating chat bubble with WebSocket connection to the teacher.

---

## 📦 Tech Stack

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

## 🧪 Test Users

Loaded automatically via `fixtures.json` (both with Docker and `loaddata`):

| Username     | Role    | Password    |
|--------------|---------|-------------|
| admin        | Admin   | (set yours) |
| john_author  | AUTHOR  | password123 |
| alice        | STUDENT | password123 |

Test lesson URL: `http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/`

> 💡 To test the chat as two users, open Alice's view in an **incognito window** (or a different browser profile). The same browser shares `localStorage`, so both tabs would otherwise be logged in as the same user.

---

## 📊 Project Progress

| Step | Feature                                          | Status |
|------|--------------------------------------------------|--------|
| 1    | Basic API setup                                  | ✅     |
| 2    | Database models                                  | ✅     |
| 3    | Serializers + CRUD                               | ✅     |
| 4    | JWT Authentication                               | ✅     |
| 5    | Permissions + roles                              | ✅     |
| 6    | Validation + filtering                           | ✅     |
| 7    | Block system + HTML importer                     | ✅     |
| 8    | Enrollment API                                   | ✅     |
| 9    | Progress tracking API                            | ✅     |
| 10   | React frontend — lesson viewer                   | ✅     |
| 11   | iframe embedding                                 | ✅     |
| 12   | Docker                                           | ✅     |
| 13   | Management dashboard + messaging                 | ✅     |
| 14   | PyCharm-style code editor (CodeMirror + Darcula) | ✅     |
| 15   | Real-time chat via WebSockets (Channels + Daphne)| ✅     |
| 16   | Full attempt history (per-submission timestamps + answer viewer) | ✅     |
| 17   | In-app visual block editor (WYSIWYG TEXT, QUIZ & CODE forms, reorder) | ✅     |
| 18   | Image upload in blocks + fill-in-the-blanks (FILL) task type | ✅     |

---

<div align="center">

Made with Django + React + Channels

**[View on GitHub](https://github.com/EugeneMorrison/learning-platform)**

</div>
