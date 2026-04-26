# 🎓 Learning Platform

**[Русская версия](README.ru.md)**

> An interactive learning platform inspired by Stepik and Google Colab. Built with Django + React, designed to be embedded on external websites via iframe.

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0.3-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.16.1-red.svg)](https://www.django-rest-framework.org/)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![JWT](https://img.shields.io/badge/Auth-JWT-orange.svg)](https://django-rest-framework-simplejwt.readthedocs.io/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg)](https://www.docker.com/)

---

## 📋 What It Does

Authors create courses made of **blocks** — theory text, quizzes, and coding exercises. Students work through lessons interactively. The platform can be embedded on any website using a simple `<iframe>` tag.

**Author can:**

* Create and edit courses, lessons, and blocks
* Import lessons from HTML files automatically
* Give students access via enrollment
* View student progress and statistics

**Student can:**

* Read theory blocks with syntax-highlighted code examples
* Answer quiz questions with instant feedback and retry on wrong answers
* Write and run Python code directly in the browser
* Track their progress through lessons

---

## 🏗️ Architecture

```
learning-platform/
├── backend/                  # Django project settings
├── api/                      # Main app
│   ├── models.py             # User, Course, Lesson, Block, Enrollment, Progress, Message
│   ├── serializers.py        # JSON serializers
│   ├── views.py              # API views + code execution + messaging + student progress
│   ├── urls.py               # URL routing
│   ├── permissions.py        # IsAuthor, IsOwnerOrReadOnly
│   └── management/
│       └── commands/
│           └── import_lesson.py   # HTML → database importer
├── frontend/                 # React app (Vite)
│   └── src/
│       ├── api.js            # Axios client with JWT auth
│       ├── App.jsx           # Routing for all pages
│       ├── pages/
│       │   ├── LoginPage.jsx
│       │   ├── RegisterPage.jsx
│       │   ├── DashboardPage.jsx        # Role-based dashboard
│       │   ├── CoursePage.jsx           # Course detail (author/student views)
│       │   ├── StudentProgressPage.jsx  # Author views per-student progress
│       │   └── LessonViewer.jsx         # Reads lesson ID from URL path
│       └── components/
│           ├── TextBlock.jsx
│           ├── QuizBlock.jsx
│           └── CodeBlock.jsx
├── Dockerfile                # Multi-stage build: Node → Python
├── docker-compose.yml        # One-command launch
├── .dockerignore
├── fixtures.json             # Test data (users, courses, lessons, blocks)
├── requirements.txt
└── manage.py
```

---

## 🧱 Block System

Each lesson is made of blocks. Three types are supported:

| Type | Description               | Content stored as                                                                      |
|------|---------------------------|----------------------------------------------------------------------------------------|
| TEXT | Theory with HTML formatting | `{"html": "<p>...</p>"}`                                                             |
| QUIZ | Multiple choice question  | `{"question": "...", "options": [...], "correct_answer": 0, "explanation": "..."}`   |
| CODE | Python coding exercise    | `{"prompt": "...", "starter_code": "...", "tests": [...]}`                           |

---

## 🔐 Authentication & Roles

JWT-based authentication with two roles:

* **AUTHOR** — can create/edit/delete their own courses, lessons, blocks
* **STUDENT** — can view published courses, enroll, submit answers

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
- Installs all Python and Node dependencies
- Builds the React frontend
- Runs database migrations
- Loads test data (users, courses, lessons, blocks)
- Starts the server on port 8000

**2. Open the lesson directly in the browser:**

```
http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/
```

**3. Test iframe embedding:**

Open `iframe_test.html` from the project root in your browser (double-click it in File Explorer). It loads the same lesson inside an `<iframe>` — this is how the platform is meant to be used on external websites.

To embed a lesson on your own page:

```html
<iframe
  src="http://your-server/lesson/<lesson-uuid>/"
  width="100%"
  height="800px"
  frameborder="0">
</iframe>
```

**To stop:** `Ctrl+C` in the terminal, then `docker-compose down`

**Next runs** (no code changes): `docker-compose up` — no `--build` needed, uses cached image.

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
GET    /api/lessons/{id}/           Lesson detail
GET    /api/blocks/?lesson={id}     List blocks in a lesson
```

### Enrollment

```
GET    /api/enrollments/                    My enrollments
POST   /api/enrollments/                    Enroll in a course
DELETE /api/enrollments/{course_id}/        Unenroll
```

### Progress

```
POST   /api/progress/submit/                Submit block answer
GET    /api/progress/course/{id}/           Progress for a course
GET    /api/progress/stats/                 Overall statistics
```

### Code Execution

```
POST   /api/run-code/               Run Python code, get stdout/stderr
POST   /api/run-tests/              Run code against test cases, get pass/fail
```

### Author Tools (Step 13)

```
GET    /api/courses/my_courses/                            Author's own courses
POST   /api/courses/{id}/enroll_student/                   Enroll student by username
GET    /api/progress/course/{id}/student/{student_id}/     View specific student's progress
```

### Messaging (Step 13)

```
GET    /api/messages/?course={id}&user={id}    List messages between teacher and student
POST   /api/messages/                          Send a message
```

---

## 🖥️ Frontend Routes (Step 13)

```
/login/                                    Login form
/register/                                 Registration with role selector (Student/Author)
/dashboard/                                Role-based dashboard
/courses/:courseId/                        Course detail (author/student views)
/courses/:courseId/students/:studentId/    Author: per-student progress
/lesson/:lessonId/                         Lesson viewer
```

**Author dashboard:** lists own courses (from `/api/courses/my_courses/`), inline "Create Course" form.
**Student dashboard:** lists enrolled courses with enrollment dates.
**Author course page:** lessons list, add-lesson form, students list with **Progress** and **💬 Chat** buttons (inline chat per student).
**Student progress page:** completion %, tasks done, quizzes correct, plus per-lesson breakdown of each block's status, correctness, and completion date.

---

## 📦 Tech Stack

### Backend

| Package                          | Purpose                |
|----------------------------------|------------------------|
| Django 6.0.3                     | Web framework          |
| Django REST Framework 3.16.1     | API toolkit            |
| djangorestframework-simplejwt    | JWT authentication     |
| django-cors-headers              | Cross-origin requests  |
| django-filter                    | Search and filtering   |
| BeautifulSoup4                   | HTML lesson importer   |

### Frontend

| Package      | Purpose             |
|--------------|---------------------|
| React 19     | UI framework        |
| Vite 8       | Build tool          |
| Axios        | HTTP client         |
| highlight.js | Syntax highlighting |

### Infrastructure

| Tool           | Purpose                          |
|----------------|----------------------------------|
| Docker         | Containerization                 |
| docker-compose | Multi-container orchestration    |
| SQLite         | Database                         |

---

## 🧪 Test Users

Loaded automatically via `fixtures.json` (both with Docker and `loaddata`):

| Username     | Role    | Password    |
|--------------|---------|-------------|
| admin        | Admin   | (set yours) |
| john_author  | AUTHOR  | password123 |
| alice        | STUDENT | password123 |

Test lesson URL: `http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/`

---

## 📊 Project Progress

| Step | Feature                         | Status |
|------|---------------------------------|--------|
| 1    | Basic API setup                 | ✅     |
| 2    | Database models                 | ✅     |
| 3    | Serializers + CRUD              | ✅     |
| 4    | JWT Authentication              | ✅     |
| 5    | Permissions + roles             | ✅     |
| 6    | Validation + filtering          | ✅     |
| 7    | Block system + HTML importer    | ✅     |
| 8    | Enrollment API                  | ✅     |
| 9    | Progress tracking API           | ✅     |
| 10   | React frontend — lesson viewer  | ✅     |
| 11   | iframe embedding                | ✅     |
| 12   | Docker                          | ✅     |
| 13   | Management dashboard + messaging| ✅     |

---

<div align="center">

Made with Django + React

**[View on GitHub](https://github.com/EugeneMorrison/learning-platform)**

</div>
