# 🎓 Обучающая платформа

**[English version](README.md)**

> Интерактивная обучающая платформа по типу Stepik и Google Colab. Построена на Django + React, может встраиваться на внешние сайты через iframe. Чат в реальном времени по WebSocket, редактор кода в стиле PyCharm прямо в браузере, полная история отправок ответов для преподавателя.

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.0.3-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.16.1-red.svg)](https://www.django-rest-framework.org/)
[![Channels](https://img.shields.io/badge/Channels-4.3-purple.svg)](https://channels.readthedocs.io/)
[![React](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![CodeMirror](https://img.shields.io/badge/CodeMirror-6-d30707.svg)](https://codemirror.net/)
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
* Смотреть **каждую отправку студента** — включая неверные попытки, с точностью до секунды и фактическим кодом, который студент написал
* Общаться с каждым студентом в чате в реальном времени

**Ученик может:**

* Читать блок с теорией с подсветкой синтаксиса
* Отвечать на тесты с обратной связью и повторными попытками
* Писать и запускать Python-код в **редакторе в стиле PyCharm** (CodeMirror 6 с темой Darcula — подсветка ключевых слов, парные скобки, подсветка встроенных функций Python)
* Отслеживать свой прогресс по урокам
* Общаться с преподавателем в чате в реальном времени

---

## 🏗️ Архитектура

```
learning-platform/
├── backend/                  # Настройки Django-проекта
│   ├── settings.py           # Настроены ASGI и Channels
│   └── asgi.py               # ProtocolTypeRouter: HTTP → Django, WS → ChatConsumer
├── api/                      # Основное приложение
│   ├── models.py             # User, Course, Lesson, Block, Enrollment, Progress, Attempt, Message
│   ├── serializers.py        # JSON-сериализаторы
│   ├── views.py              # REST-вьюхи + выполнение кода + прогресс + история сообщений
│   ├── urls.py               # HTTP-маршрутизация
│   ├── consumers.py          # ChatConsumer (WebSocket) — обмен сообщениями в реальном времени
│   ├── routing.py            # WebSocket-маршруты
│   ├── ws_auth.py            # JWT-middleware для WebSocket (токен из query-string)
│   ├── permissions.py        # IsAuthor, IsOwnerOrReadOnly
│   └── management/
│       └── commands/
│           └── import_lesson.py   # Импортер HTML → база данных
├── frontend/                 # React-приложение (Vite)
│   └── src/
│       ├── api.js            # Axios-клиент с JWT-авторизацией и interceptor для refresh
│       ├── App.jsx           # Маршрутизация всех страниц
│       ├── pages/
│       │   ├── LoginPage.jsx
│       │   ├── RegisterPage.jsx
│       │   ├── DashboardPage.jsx        # Дашборд по роли
│       │   ├── CoursePage.jsx           # Страница курса (автор/студент) + WebSocket-чат
│       │   ├── StudentProgressPage.jsx  # Прогресс студента + раскрывающаяся история попыток
│       │   └── LessonViewer.jsx         # Считывает ID урока из URL, WebSocket-чат с преподавателем
│       └── components/
│           ├── TextBlock.jsx
│           ├── QuizBlock.jsx
│           ├── CodeBlock.jsx          # Редактор CodeMirror 6 с темой PyCharm Darcula
│           └── pycharmDarcula.js      # Тема + подсветка встроенных функций Python
├── Dockerfile                # Многоэтапная сборка: Node → Python
├── docker-compose.yml        # Запуск одной командой
├── .dockerignore
├── fixtures.json             # Тестовые данные (пользователи, курсы, уроки, блоки)
├── requirements.txt          # Включая channels и daphne
└── manage.py
```

---

## 🧱 Система блоков

Каждый урок состоит из блоков. Поддерживаются три типа:

| Тип  | Описание                      | Формат хранения                                                                        |
|------|-------------------------------|----------------------------------------------------------------------------------------|
| TEXT | Теория с HTML-форматированием | `{"html": "<p>...</p>"}`                                                               |
| QUIZ | Тест с выбором ответа         | `{"question": "...", "options": [...], "correct_answer": 0, "explanation": "..."}`     |
| CODE | Задача на Python              | `{"prompt": "...", "starter_code": "...", "tests": [...]}`                             |

**CODE-блоки** используют **CodeMirror 6** с собственной темой **PyCharm Darcula** (`frontend/src/components/pycharmDarcula.js`):

* Оранжевые ключевые слова (`if`, `def`, `and`, `True`)
* Зелёные строки, синие числа, фиолетовые встроенные функции Python (`print`, `input`, `len`, `range` — всего ~60 функций, распознавание через ViewPlugin, который обходит синтаксическое дерево)
* Шрифт JetBrains Mono, тёмный фон `#2B2B2B`
* Подсветка парных скобок, авто-отступ, Tab для отступа
* Нативная нумерация строк CodeMirror и подсветка активной строки в нумерации

---

## 💬 Чат в реальном времени (WebSocket)

Чат «преподаватель↔студент» работает через **Django Channels** — сообщения появляются мгновенно, без поллинга и без перезагрузки страницы.

* **Бэкенд:** ASGI-сервер (Daphne) + Channels 4. WebSocket-эндпоинт: `ws/chat/<course_id>/<other_user_id>/?token=<jwt>`.
* **Авторизация:** браузер не может добавить заголовок Authorization в WebSocket-handshake, поэтому JWT access-токен передаётся в query-string. Middleware (`api/ws_auth.py`) валидирует его и кладёт `User` в scope соединения.
* **Комнаты:** имя группы вычисляется из отсортированной пары `(user_id_A, user_id_B)` внутри курса — обе стороны попадают в одну и ту же группу независимо от того, кто подключился первым. Посторонние и пары «студент↔студент» отклоняются с кодом закрытия WebSocket 4003.
* **Channel layer:** `InMemoryChannelLayer` в разработке (никакой дополнительной инфраструктуры не нужно). Для продакшена — `channels_redis` + Redis.
* **Хранение:** история сообщений всё ещё отдаётся существующим HTTP-эндпоинтом (загружается один раз при открытии чата). WebSocket только транслирует новые сообщения.

---

## 📊 История попыток

Каждая отправка ответа на QUIZ или CODE сохраняется в новую таблицу `Attempt` — отдельно от `Progress`, которая по-прежнему хранит только последний ответ и счётчик попыток.

* Автор открывает страницу прогресса студента и кликает по «пилюле» **`▶ попыток: N`** рядом с любой задачей, чтобы развернуть полную историю отправок.
* Каждая запись показывает время с точностью до секунды (`ДД.ММ.ГГГГ ЧЧ:ММ:СС`) и значок ✓/✗ корректности.
* Клик по конкретной попытке раскрывает её содержимое: для CODE-блока — отправленный код с **той же темой PyCharm Darcula**, что и в редакторе; для QUIZ-блока — номер выбранного варианта.

---

## 🔐 Аутентификация и роли

JWT-аутентификация с двумя ролями:

* **AUTHOR** — может создавать/редактировать/удалять свои курсы, уроки, блоки
* **STUDENT** — может просматривать опубликованные курсы, записываться, отправлять ответы

Access-токены живут 7 дней, refresh-токены — 30 дней. Axios-interceptor в `frontend/src/api.js` автоматически обновляет access-токен по 401 и повторяет исходный запрос — сессия очищается только если сам refresh-запрос провалился.

---

## 🔗 Встраивание через iframe

Каждый урок доступен по адресу `/lesson/<uuid>/`. Django отдаёт React-приложение, которое считывает UUID из URL и загружает урок через API. Маршрут помечен декоратором `@xframe_options_exempt`, что позволяет встраивать страницу на внешних сайтах.

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

Docker автоматически сделает всё:
- Установит все зависимости Python и Node (включая Channels и Daphne)
- Соберёт React-фронтенд
- Выполнит миграции базы данных
- Загрузит тестовые данные (пользователи, курсы, уроки, блоки)
- Запустит ASGI-сервер на порту 8000

**2. Открыть урок в браузере:**

```
http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/
```

**3. Проверить встраивание через iframe:**

Откройте `iframe_test.html` из корня проекта в браузере (двойной клик в Проводнике). Он загружает тот же урок внутри `<iframe>` — именно так платформа встраивается на внешних сайтах.

**Остановить:** `Ctrl+C` в терминале, затем `docker-compose down`

**Повторный запуск** (без изменений в коде): `docker-compose up` — без `--build`, используется кешированный образ.

---

## 🛠️ Ручная установка (без Docker)

Рекомендуемый способ — Docker, но проект можно запустить и вручную. Понадобятся:

* **Python 3.12+** — [python.org](https://www.python.org/downloads/)
* **Node.js 20+** — [nodejs.org](https://nodejs.org/) (нужен для сборки React-фронтенда)

> ⚠️ **Важно:** папка `frontend/dist/` находится в `.gitignore` (это артефакт сборки). После свежего клонирования её нет, и Django не сможет отдавать фронтенд, пока вы его не соберёте. Если запустить только шаги Django, появится предупреждение `staticfiles.W004` и страница урока будет пустой. Docker собирает фронтенд автоматически — при ручной установке это нужно делать самому.

**1. Бэкенд — Python-зависимости:**

```bash
python -m venv venv
venv\Scripts\activate           # Windows (PowerShell/CMD)
# source venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
```

**2. Фронтенд — собрать React-приложение** (этот шаг легко пропустить):

```bash
cd frontend
npm install
npm run build
cd ..
```

Эта команда создаёт `frontend/dist/`, которую Django использует и как директорию шаблонов (для `index.html`), и как директорию статических файлов (для JS/CSS-бандлов).

**3. Django — миграции, фикстуры, сервер:**

```bash
python manage.py migrate
python manage.py loaddata fixtures.json
python manage.py runserver
```

> В логе запуска должно появиться **"Starting ASGI/Daphne version 4.x development server"** — это подтверждает, что WebSocket работают. Если вместо этого пишет «Starting development server» (WSGI), проверьте, что `daphne` стоит первым в `INSTALLED_APPS`.

**4. Открыть в браузере** — Django работает на порту **8000**:

```
http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/
http://localhost:8000/login/
http://localhost:8000/admin/
```

> ❗ **Не** открывайте `http://127.0.0.1:5173/` — это порт dev-сервера Vite, он работает только если вы отдельно запустили `npm run dev` внутри `frontend/`. При обычной ручной установке всё отдаёт Django на порту **8000**.

**Повторный запуск после изменений в коде:**

* Изменения в бэкенде (Python) — достаточно перезапустить `python manage.py runserver`.
* Изменения во фронтенде (React) — заново выполните `npm run build` в `frontend/` и обновите страницу. (Или используйте `npm run dev` на порту 5173 для горячей перезагрузки во время активной разработки — но API- и WebSocket-запросы всё равно идут в Django на порт 8000.)

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
POST   /api/progress/submit/                              Отправить ответ на блок (одновременно создаёт запись в Attempt)
GET    /api/progress/course/{id}/                         Прогресс по курсу
GET    /api/progress/stats/                               Общая статистика
GET    /api/progress/student/{student_id}/course/{id}/    Прогресс конкретного студента с полной историей попыток
```

### Выполнение кода

```
POST   /api/run-code/               Запустить Python-код, получить stdout/stderr
POST   /api/run-tests/              Запустить код против тестов, получить результат
```

### Инструменты автора

```
GET    /api/courses/my_courses/                            Курсы текущего автора
POST   /api/courses/{id}/enroll_student/                   Записать студента по username
```

### Сообщения (история)

```
GET    /api/messages/?course={id}              Переписка преподавателя и студента (история)
POST   /api/messages/                          (Старая HTTP-отправка — оставлена для совместимости)
```

### WebSocket — чат в реальном времени

```
ws://host/ws/chat/{course_id}/{other_user_id}/?token={jwt_access_token}
```

Отправка сообщения: клиент → сервер JSON `{"text": "..."}`.
Получение сообщений: сервер → клиент сериализованный `Message` JSON, рассылается обоим участникам сразу после сохранения.

---

## 🖥️ Маршруты фронтенда

```
/login/                                    Форма входа
/register/                                 Регистрация с выбором роли (Студент/Автор)
/dashboard/                                Дашборд по роли пользователя
/courses/:courseId/                        Страница курса (автор/студент)
/courses/:courseId/students/:studentId/    Автор: прогресс студента с историей попыток
/lesson/:lessonId/                         Просмотр урока
```

**Дашборд автора:** список своих курсов (через `/api/courses/my_courses/`), форма создания курса.
**Дашборд студента:** список курсов, на которые записан, с датами записи.
**Страница курса (автор):** уроки, форма добавления урока, список студентов с кнопками **Прогресс** и **💬 Чат**. Чат открывает WebSocket-соединение, привязанное к конкретному студенту.
**Страница прогресса студента:** % завершения, выполненные задачи, правильные тесты, плюс разбивка по урокам. Рядом с каждой задачей появляется пилюля `▶ попыток: N` — клик по ней раскрывает полную историю отправок с временными метками; клик по конкретной попытке показывает отправленный код/ответ в окне с подсветкой синтаксиса.
**Просмотр урока:** редактор CodeMirror в стиле PyCharm для CODE-блоков, всплывающий чат с WebSocket-соединением к преподавателю.

---

## 📦 Технологии

### Бэкенд

| Пакет                            | Назначение                                |
|----------------------------------|-------------------------------------------|
| Django 6.0.3                     | Веб-фреймворк                             |
| Django REST Framework 3.16.1     | API-инструментарий                        |
| djangorestframework-simplejwt    | JWT-аутентификация                        |
| Channels 4.3.2                   | WebSocket / ASGI                          |
| Daphne 4.2.2                     | ASGI-сервер (заменяет стандартный runserver) |
| django-cors-headers              | Кросс-доменные запросы                    |
| django-filter                    | Поиск и фильтрация                        |
| BeautifulSoup4                   | Импортер HTML-уроков                      |

### Фронтенд

| Пакет                    | Назначение                                |
|--------------------------|-------------------------------------------|
| React 19                 | UI-фреймворк                              |
| Vite 8                   | Сборщик                                   |
| Axios                    | HTTP-клиент (с interceptor для refresh JWT) |
| @uiw/react-codemirror    | React-обёртка для CodeMirror 6            |
| @codemirror/lang-python  | Синтаксический парсер Python              |
| highlight.js             | Подсветка синтаксиса в read-only теории   |

### Инфраструктура

| Инструмент     | Назначение                                |
|----------------|-------------------------------------------|
| Docker         | Контейнеризация                           |
| docker-compose | Оркестрация контейнеров                   |
| SQLite         | База данных                               |
| InMemory layer | Брокер сообщений Channels (в разработке — для продакшена заменить на Redis) |

---

## 🧪 Тестовые пользователи

Загружаются автоматически из `fixtures.json` (и через Docker, и через `loaddata`):

| Имя пользователя  | Роль    | Пароль      |
|-------------------|---------|-------------|
| admin             | Admin   | (свой)      |
| john_author       | AUTHOR  | password123 |
| alice             | STUDENT | password123 |

URL тестового урока: `http://localhost:8000/lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/`

> 💡 Чтобы протестировать чат от лица двух пользователей, откройте страницу Алисы в **окне инкогнито** (или в другом профиле браузера). Один и тот же браузер делит `localStorage` между вкладками, поэтому иначе обе вкладки будут залогинены под одним пользователем.

---

## 📊 Прогресс проекта

| Шаг  | Функциональность                                          | Статус |
|------|-----------------------------------------------------------|--------|
| 1    | Базовая настройка API                                     | ✅     |
| 2    | Модели базы данных                                        | ✅     |
| 3    | Сериализаторы + CRUD                                      | ✅     |
| 4    | JWT-аутентификация                                        | ✅     |
| 5    | Права доступа и роли                                      | ✅     |
| 6    | Валидация и фильтрация                                    | ✅     |
| 7    | Система блоков + HTML-импортер                            | ✅     |
| 8    | API записи на курсы                                       | ✅     |
| 9    | API отслеживания прогресса                                | ✅     |
| 10   | React-фронтенд — просмотр уроков                          | ✅     |
| 11   | Встраивание через iframe                                  | ✅     |
| 12   | Docker                                                    | ✅     |
| 13   | Дашборд управления + сообщения                            | ✅     |
| 14   | Редактор кода в стиле PyCharm (CodeMirror + Darcula)      | ✅     |
| 15   | Чат в реальном времени по WebSocket (Channels + Daphne)   | ✅     |
| 16   | Полная история попыток (время до секунды + просмотр кода) | ✅     |

---

<div align="center">

Сделано на Django + React + Channels

**[Посмотреть на GitHub](https://github.com/EugeneMorrison/learning-platform)**

</div>
