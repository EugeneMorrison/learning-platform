🎓 Learning Platform - Interactive Course Management System

A Django-based learning platform inspired by Stepik and Google Colab, featuring interactive lessons with text, quizzes, and code exercises.

This project is a full-stack learning management system that allows:

Authors to create and manage interactive courses
Students to enroll in courses and track their progress
Automatic parsing of HTML lesson files into structured content blocks

The platform features three types of content blocks:

📝 TEXT - Theory and explanations
❓ QUIZ - Interactive multiple-choice questions
💻 CODE - Programming exercises with automated test cases


✨ Features
🔐 Authentication & Authorization

JWT-based authentication system
Role-based access control (Author/Student roles)
Secure password hashing
Token refresh mechanism

📚 Course Management

Create and publish courses
Organize content into lessons and blocks
Search and filter courses
Course enrollment system
Progress tracking for students

🎨 Content Block System

TEXT blocks: Rich HTML content with formatting
QUIZ blocks: Multiple-choice questions with instant feedback
CODE blocks: Programming exercises with test cases

📤 HTML Lesson Import

Automatic parsing of HTML files
Intelligent block type detection
Bulk content import with one command
Preserves formatting and structure

🛡️ Security Features

CORS protection
Permission-based access control
Input validation and sanitization
SQL injection prevention via Django ORM

🔍 Advanced Features

Full-text search across courses
Ordering and filtering
Duplicate prevention
Custom validation rules

🛠️ Tech Stack
Backend

Django 6.0.3 - Web framework
Django REST Framework - API toolkit
Simple JWT - Authentication
BeautifulSoup4 - HTML parsing

Database

SQLite (Development)
PostgreSQL (Production-ready)

Frontend

HTML5 / CSS3 / JavaScript
Responsive design
No framework dependencies

Tools & Libraries

django-filter - Advanced filtering
django-cors-headers - CORS handling
Git - Version control


Access the application

Admin Panel: http://127.0.0.1:9000/admin/
API Root: http://127.0.0.1:9000/api/
Lesson Viewer: http://127.0.0.1:9000/static/lesson_viewer.html

