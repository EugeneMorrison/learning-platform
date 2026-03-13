# Learning Platform - Interactive Course Management System

A Django-based learning platform inspired by Stepik and Google Colab, featuring interactive lessons with text, quizzes, and code exercises.

This project is a full-stack learning management system that allows:
- Authors to create and manage interactive courses
- Students to enroll in courses and track their progress
- Automatic parsing of HTML lesson files into structured content blocks

The platform features three types of content blocks:
- **TEXT** - Theory and explanations
- **QUIZ** - Interactive multiple-choice questions
- **CODE** - Programming exercises with automated test cases

## Features

### Authentication & Authorization
- JWT-based authentication system
- Role-based access control (Author/Student roles)
- Secure password hashing
- Token refresh mechanism

### Course Management
- Create and publish courses
- Organize content into lessons and blocks
- Search and filter courses
- Course enrollment system
- Progress tracking for students

### Content Block System
- TEXT blocks: Rich HTML content with formatting
- QUIZ blocks: Multiple-choice questions with instant feedback
- CODE blocks: Programming exercises with test cases

### HTML Lesson Import
- Automatic parsing of HTML files
- Intelligent block type detection
- Bulk content import with one command
- Preserves formatting and structure

### Security Features
- CORS protection
- Permission-based access control
- Input validation and sanitization
- SQL injection prevention via Django ORM

### Advanced Features
- Full-text search across courses
- Ordering and filtering
- Duplicate prevention
- Custom validation rules

## Requirements

- Python 3.10+
- Git

## Setup

**1. Clone the repository**
```bash
git clone https://github.com/YOUR_USERNAME/learning-platform.git
cd learning-platform
```

**2. Create and activate virtual environment**
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac/Linux
python -m venv venv
source venv/bin/activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Apply migrations**
```bash
python manage.py migrate
```

**5. Create admin user (optional)**
```bash
python manage.py createsuperuser
```

**6. Run the server**
```bash
python manage.py runserver
```

Server will be available at:

| Page | URL |
|------|-----|
| Admin Panel | http://127.0.0.1:8000/admin/ |
| API Root | http://127.0.0.1:8000/api/ |
| Lesson Viewer | http://127.0.0.1:8000/static/lesson_viewer.html |

## Project Structure

```
learning-platform/
├── api/              # Main app (models, views, serializers)
├── backend/          # Django settings and URLs
├── static/           # Static files
├── manage.py
└── requirements.txt
```

## Tech Stack

- Django 6.0.3
- Django REST Framework
- SimpleJWT (authentication)
- CORS Headers
