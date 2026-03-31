# 🎓 Обучающая платформа

**[English version](README.md)**

> Интерактивная обучающая платформа по типу Stepik и Google Colab. Построена на Django + React, может встраиваться на внешние сайты через iframe.

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0.3-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.16.1-red.svg)](https://www.django-rest-framework.org/)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![JWT](https://img.shields.io/badge/Auth-JWT-orange.svg)](https://django-rest-framework-simplejwt.readthedocs.io/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg)](https://www.docker.com/)

---

## 📋 Что делает платформа

Авторы создают курсы из **блоков** — теория, тесты и задачи на код. Студенты проходят уроки интерактивно. Платформа встраивается на любой сайт через `<iframe>`.

**Автор может:**

* Создавать и редактировать курсы, уроки и блоки
* Импортировать уроки из HTML-файлов
* Давать студентам доступ через систему записи на курс
* Просматривать прогресс студентов и статистику

**Ученик может:**

* Читать блок с теорией с подсветкой синтаксиса
* Отвечать на тесты с обратной связью и повторными попытками
* Писать и запускать Python-код прямо в браузере
* Отслеживать свой прогресс по урокам

---

## 🏗️ Архитектура

```
learning-platform/
├── backend/                  # Настройки Django-проекта
├── api/                      # Основное приложение
│   ├── models.py             # User, Course, Lesson, Block, Enrollment, Progress
│   ├── serializers.py        # JSON-сериализаторы
│   ├── views.py              # API-представления + выполнение кода
│   ├── urls.py               # Маршрутизация URL
│   ├── permissions.py        # IsAuthor, IsOwnerOrReadOnly
│   └── management/
│       └── commands/
│           └── import_lesson.py   # Импортер HTML → база данных
├── frontend/                 # React-приложение (Vite)
│   └── src/
│       ├── api.js            # Axios-клиент с JWT-авторизацией
│       ├── pages/
│       │   └── LessonViewer.jsx   # Считывает ID урока из URL
│       └── components/
│           ├── TextBlock.jsx
│           ├── QuizBlock.jsx
│           └── CodeBlock.jsx
├── Dockerfile                # Многоэтапная сборка: Node → Python
├── docker-compose.yml        # Запуск одной командой
├── .dockerignore
├── fixtures.json             # Тестовые данные (пользователи, курсы, уроки, блоки)
├── requirements.txt
└── manage.py
```

---

## 🧱 Система блоков

Каждый урок состоит из блоков. Поддерживаются три типа:

| Тип  | Описание                      | Формат хранения                                                                        |
|------|-------------------------------|----------------------------------------------------------------------------------------|
| TEXT | Теория с HTML-форматированием | `{"html": "<p>...</p>"}`                                                               |
| QUIZ | Тест с выбором ответа        | `{"question": "...", "options": [...], "correct_answer": 0, "explanation": "..."}`     |
| CODE | Задача на Python              | `{"prompt": "...", "starter_code": "...", "tests": [...]}`                             |

---

## 🔐 Аутентификация и роли

JWT-аутентификация с двумя ролями:

* **AUTHOR** — может создавать/редактировать/удалять свои курсы, уроки, блоки
* **STUDENT** — может просматривать опубликованные курсы, записываться, отправлять ответы

---

## 🔗 Встраивание через iframe

Каждый урок доступен по адресу `/lesson/<uuid>/`. Django отдает React-приложение, которое считывает UUID из URL и загружает урок через API. Маршрут помечен декоратором `@xframe_options_exempt`, что позволяет встраивать страницу на внешних сайтах.

```html
<iframe
  src="http://your-server/lesson/<lesson-uuid>/"
  width="100%"
  height="700px"
  frameborder="0">
</iframe>
```

В корне репозитория есть файл `iframe_test.html` для локального тестирования.

---

## 🚀 Как запустить

Установить/запустить [Docker Desktop](https://www.docker.com/products/docker-desktop/).

**1. Клонировать и запустить:**

```bash
git clone https://github.com/EugeneMorrison/learning-platform.git
cd learning-platform
docker-compose up --build
```

Docker автоматически сделает все:
- Установит все зависимости Python и Node
- Соберет React-фронтенд
- Выполнит миграции базы данных
- Загрузит тестовые данные (пользователи, курсы, уроки, блоки)
- Запустит сервер на порту 8000

**2. Открыть урок в браузере:**

```
http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/
```

**3. Проверить встраивание через iframe:**

Откройте `iframe_test.html` из корня проекта в браузере (двойной клик в Проводнике). Он загружает тот же урок внутри `<iframe>` — именно так платформа встраивается на внешних сайтах.

Чтобы встроить урок на свою страницу:

```html
<iframe
  src="http://your-server/lesson/<lesson-uuid>/"
  width="100%"
  height="800px"
  frameborder="0">
</iframe>
```

**Остановить:** `Ctrl+C` в терминале, затем `docker-compose down`

**Повторный запуск** (без изменений в коде): `docker-compose up` — без `--build`, используется кешированный образ.

---

### Импорт урока из HTML

```bash
python manage.py import_lesson path/to/lesson.html --course-id <uuid> --order 1
```

---

## 🎯 API-эндпоинты

### Авторизация

```
POST   /api/auth/register/          Регистрация нового пользователя
POST   /api/auth/login/             Вход, получение JWT-токенов
POST   /api/auth/token/refresh/     Обновление access-токена
GET    /api/auth/me/                Информация о текущем пользователе
```

### Курсы и уроки

```
GET    /api/courses/                Список опубликованных курсов
POST   /api/courses/                Создать курс (только автор)
GET    /api/courses/{id}/           Детали курса
PUT    /api/courses/{id}/           Обновить курс (только автор)
DELETE /api/courses/{id}/           Удалить курс (только автор)
GET    /api/lessons/?course={id}    Список уроков в курсе
GET    /api/lessons/{id}/           Детали урока
GET    /api/blocks/?lesson={id}     Список блоков в уроке
```

### Запись на курс

```
GET    /api/enrollments/                    Мои записи на курсы
POST   /api/enrollments/                    Записаться на курс
DELETE /api/enrollments/{course_id}/        Отписаться от курса
```

### Прогресс

```
POST   /api/progress/submit/                Отправить ответ на блок
GET    /api/progress/course/{id}/           Прогресс по курсу
GET    /api/progress/stats/                 Общая статистика
```

### Выполнение кода

```
POST   /api/run-code/               Запустить Python-код, получить stdout/stderr
POST   /api/run-tests/              Запустить код против тестов, получить результат
```

---

## 📦 Технологии

### Бэкенд

| Пакет                            | Назначение               |
|----------------------------------|--------------------------|
| Django 6.0.3                     | Веб-фреймворк            |
| Django REST Framework 3.16.1     | API-инструментарий       |
| djangorestframework-simplejwt    | JWT-аутентификация       |
| django-cors-headers              | Кросс-доменные запросы   |
| django-filter                    | Поиск и фильтрация      |
| BeautifulSoup4                   | Импортер HTML-уроков     |

### Фронтенд

| Пакет        | Назначение              |
|--------------|-------------------------|
| React 19     | UI-фреймворк            |
| Vite 8       | Сборщик                 |
| Axios        | HTTP-клиент             |
| highlight.js | Подсветка синтаксиса    |

### Инфраструктура

| Инструмент     | Назначение                   |
|----------------|------------------------------|
| Docker         | Контейнеризация              |
| docker-compose | Оркестрация контейнеров      |
| SQLite         | База данных                  |

---

## 🧪 Тестовые пользователи

Загружаются автоматически из `fixtures.json` (и через Docker, и через `loaddata`):

| Имя пользователя | Роль    | Пароль      |
|-------------------|---------|-------------|
| admin             | Admin   | (свой)      |
| john_author       | AUTHOR  | password123 |
| alice             | STUDENT | password123 |

URL тестового урока: `http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/`

---

## 📊 Прогресс проекта

| Шаг  | Функциональность              | Статус |
|------|-------------------------------|--------|
| 1    | Базовая настройка API         | ✅     |
| 2    | Модели базы данных            | ✅     |
| 3    | Сериализаторы + CRUD          | ✅     |
| 4    | JWT-аутентификация            | ✅     |
| 5    | Права доступа и роли          | ✅     |
| 6    | Валидация и фильтрация        | ✅     |
| 7    | Система блоков + HTML-импортер| ✅     |
| 8    | API записи на курсы           | ✅     |
| 9    | API отслеживания прогресса    | ✅     |
| 10   | React-фронтенд — просмотр уроков | ✅ |
| 11   | Встраивание через iframe      | ✅     |
| 12   | Docker                        | ✅     |

---

<div align="center">

Сделано на Django + React

**[Посмотреть на GitHub](https://github.com/EugeneMorrison/learning-platform)**

</div>
