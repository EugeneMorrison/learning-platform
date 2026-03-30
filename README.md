# 🎓 Learning Platform

> An interactive learning platform inspired by Stepik and Google Colab. Built with Django + React, designed to be embedded on external websites via iframe.

[![Python](https://img.shields.io/badge/Python-3.14.3-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0.3-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.16.1-red.svg)](https://www.django-rest-framework.org/)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![JWT](https://img.shields.io/badge/Auth-JWT-orange.svg)](https://django-rest-framework-simplejwt.readthedocs.io/)

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
│   ├── models.py             # User, Course, Lesson, Block, Enrollment, Progress
│   ├── serializers.py        # JSON serializers
│   ├── views.py              # API views + code execution
│   ├── urls.py               # URL routing
│   ├── permissions.py        # IsAuthor, IsOwnerOrReadOnly
│   └── management/
│       └── commands/
│           └── import\_lesson.py   # HTML → database importer
├── frontend/                 # React app (Vite)
│   └── src/
│       ├── api.js            # Axios client with JWT auth
│       ├── pages/
│       │   └── LessonViewer.jsx
│       └── components/
│           ├── TextBlock.jsx
│           ├── QuizBlock.jsx
│           └── CodeBlock.jsx
├── requirements.txt
└── manage.py
```

---

## 🧱 Block System

Each lesson is made of blocks. Three types are supported:

|Type|Description|Content stored as|
|-|-|-|
|TEXT|Theory with HTML formatting|`{"html": "<p>...</p>"}`|
|QUIZ|Multiple choice question|`{"question": "...", "options": \[...], "correct\_answer": 0, "explanation": "..."}`|
|CODE|Python coding exercise|`{"prompt": "...", "starter\_code": "...", "tests": \[...]}`|

---

## 🔐 Authentication \& Roles

JWT-based authentication with two roles:

* **AUTHOR** — can create/edit/delete their own courses, lessons, blocks
* **STUDENT** — can view published courses, enroll, submit answers

---

## 🎯 API Endpoints

### Auth

```
POST   /api/auth/register/          Register new user
POST   /api/auth/login/             Login, get JWT token
POST   /api/auth/refresh/           Refresh token
GET    /api/auth/user/              Current user info
```

### Courses \& Lessons

```
GET    /api/courses/                List published courses
POST   /api/courses/                Create course (author only)
GET    /api/courses/{id}/           Course detail
PUT    /api/courses/{id}/           Update course (author only)
DELETE /api/courses/{id}/           Delete course (author only)
GET    /api/lessons/?course={id}    List lessons in a course
GET    /api/blocks/?lesson={id}     List blocks in a lesson
```

### Enrollment

```
GET    /api/enrollments/                    My enrollments
POST   /api/enrollments/                    Enroll in a course
DELETE /api/enrollments/{course\_id}/        Unenroll
GET    /api/courses/{id}/enrollments/       Author sees their students
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

---

## 🚀 Getting Started

### Prerequisites

* Python 3.10+
* Node.js 18+

### Backend Setup

```bash
# Clone the repo
git clone https://github.com/EugeneMorrison/learning-platform.git
cd learning-platform

# Create and activate virtual environment
python -m venv venv
venv\\Scripts\\activate        # Windows
source venv/bin/activate     # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Seed sample data (optional)
python manage.py seed\_data

# Start backend server
python manage.py runserver 8000
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` to see the lesson viewer.

### Import a Lesson from HTML

```bash
python manage.py import\_lesson path/to/lesson.html --course-id <uuid> --order 1
```

---

## 🔗 Embedding via iframe

Once deployed, any lesson can be embedded on an external website:

```html
<iframe
  src="https://your-platform.com/lesson/<lesson-id>"
  width="100%"
  height="700px"
  frameborder="0">
</iframe>
```

---

## 📦 Tech Stack

### Backend

|Package|Purpose|
|-|-|
|Django 6.0.3|Web framework|
|Django REST Framework|API toolkit|
|djangorestframework-simplejwt|JWT authentication|
|django-cors-headers|Cross-origin requests|
|django-filter|Search and filtering|
|BeautifulSoup4|HTML lesson importer|

### Frontend

| Package      |Purpose|
|--------------|-|
| React 19     |UI framework|
| Vite         |Build tool|
| Axios        |HTTP client|
| highlight.js |Syntax highlighting|

### Database

* **SQLite** 

---

## 📊 Project Progress

|Step|Feature|Status|
|-|-|-|
|1|Basic API setup|✅|
|2|Database models|✅|
|3|Serializers + CRUD|✅|
|4|JWT Authentication|✅|
|5|Permissions + roles|✅|
|6|Validation + filtering|✅|
|7|Block system + HTML importer|✅|
|8|Enrollment API|✅|
|9|Progress tracking API|✅|
|10|React frontend — lesson viewer|✅|
|11|iframe embedding|⏳|
|12|Docker + deployment|⏳|

---

## 🧪 Test Users (after seed\_data)

|Username|Role|Password|
|-|-|-|
|john\_author|AUTHOR|password123|
|alice|STUDENT|password123|

---

<div align="center">

Made with Django + React

**[View on GitHub](https://github.com/EugeneMorrison/learning-platform)**

</div>

