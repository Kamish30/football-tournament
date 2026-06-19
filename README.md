# ⚽ Турнир-менеджер

Система управления любительским футбольным турниром.

## Возможности

- **Группы** по годам рождения
- **Команды и игроки** с номерами
- **Матчи** — создание, редактирование счёта, автоголы, батл вратарей
- **Турнирная таблица** — автоматический расчёт очков
- **Шахматка** — перекрёстная таблица результатов
- **Рейтинг вратарей** — отдельный подсчёт баттлов
- **Бомбардиры и ассистенты** — рейтинги игроков
- **Авторизация** — редакторы входят по логину, зрители смотрят без входа
- **Оптимистичная блокировка** — защита от конфликтов при одновременном редактировании

## Быстрый старт (локально)

```bash
# 1. Установить Python 3.10+
# 2. Установить зависимости
pip install -r requirements.txt

# 3. Запустить
uvicorn main:app --reload --port 8000

# 4. Открыть http://localhost:8000
# Логин по умолчанию: admin / admin123
```

## Деплой на Railway (бесплатно)

### Шаг 1: Создать аккаунт GitHub
Если нет — зарегистрируйтесь на https://github.com

### Шаг 2: Загрузить проект на GitHub
1. Создайте новый репозиторий на GitHub (кнопка "New repository")
2. Назовите его, например, `football-tournament`
3. Загрузите все файлы проекта в репозиторий

Через терминал:
```bash
cd tournament
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/ВАШЛОГИН/football-tournament.git
git push -u origin main
```

Или просто перетащите файлы на страницу репозитория в браузере.

### Шаг 3: Развернуть на Railway
1. Зайдите на https://railway.app и войдите через GitHub
2. Нажмите **New Project** → **Deploy from GitHub repo**
3. Выберите ваш репозиторий `football-tournament`
4. Railway автоматически обнаружит Procfile и запустит проект
5. Перейдите в **Settings** → **Networking** → **Generate Domain**
6. Получите адрес вида `football-tournament-abc.up.railway.app`

### Шаг 4: Настроить секретный ключ
В Railway → Variables добавьте:
- `SECRET_KEY` = любая длинная случайная строка (например: `my-super-secret-key-2024-xyz`)

### Шаг 5: Готово!
- Откройте полученный адрес на телефоне
- Войдите: **admin** / **admin123**
- Сразу смените пароль через создание нового пользователя
- Создайте редакторов для операторов

## Альтернатива: Render (тоже бесплатно)

1. Зайдите на https://render.com
2. New → Web Service → Connect GitHub repo
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Выберите Free план

## Учётные записи

| Роль | Что может |
|------|-----------|
| **admin** | Всё + создание/удаление пользователей |
| **editor** | Создание групп, команд, игроков, матчей, ввод результатов |
| **зритель** (без входа) | Просмотр расписания, таблиц, рейтингов |

Логин по умолчанию: `admin` / `admin123` — **смените пароль при первом деплое!**

## Структура проекта

```
tournament/
├── main.py           # FastAPI приложение, все маршруты
├── db.py             # Модели базы данных (SQLAlchemy + SQLite)
├── auth.py           # Авторизация (JWT)
├── schemas.py        # Валидация данных (Pydantic)
├── requirements.txt  # Python зависимости
├── Procfile          # Для Railway/Render
├── static/
│   ├── style.css     # Стили (mobile-first)
│   └── app.js        # JS клиент (API, авторизация)
└── templates/
    ├── index.html    # Главная — список групп
    ├── login.html    # Страница входа
    └── group.html    # Страница группы (все вкладки)
```

## Технологии

- **Backend:** Python 3.10+, FastAPI, SQLAlchemy, SQLite
- **Frontend:** Vanilla JS, CSS (mobile-first)
- **Авторизация:** JWT токены (72 часа)
- **База данных:** SQLite с WAL-режимом (быстрые параллельные чтения)
