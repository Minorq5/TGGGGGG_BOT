# Бот «Вишня»

Telegram-бот для продвижения мобильного приложения «Вишня». Показывает приветственный экран с картинкой,
описание приложения и ссылку на RuStore. На aiogram 3 и aiohttp, база данных не нужна.

## Структура

| Файл | Назначение |
|------|------------|
| `main.py` | Точка входа: вебхук (aiohttp) или long polling |
| `handlers.py` | Обработчики `/start`, кнопок и прочих сообщений |
| `keyboards.py` | Inline-клавиатуры |
| `texts.py` | Все тексты и ссылки |
| `config.py` | Чтение переменных окружения |
| `welcome.jpg` | Картинка приветствия |
| `render.yaml` | Описание сервиса для Render |

## Переменные окружения

| Переменная | Обязательна | Описание |
|------------|-------------|----------|
| `BOT_TOKEN` | да | Токен от @BotFather |
| `WEBHOOK_BASE_URL` | нет | Публичный адрес сервиса, например `https://vishnya-bot.onrender.com`. Если не задан, берётся `RENDER_EXTERNAL_URL` (Render выставляет её сам). Если нет ни той, ни другой, бот работает через long polling |
| `WEBHOOK_SECRET` | нет | Секрет вебхука (только `A-Z a-z 0-9 _ -`, до 256 символов). Если не задан, генерируется при каждом старте |
| `PORT` | нет | Порт HTTP-сервера, по умолчанию `8080` (Render задаёт его сам) |

HTTP-адреса в режиме вебхука:
- `GET /` отвечает `ok` (health-check и пинг от UptimeRobot);
- `POST /webhook/<секрет>` принимает обновления от Telegram, запросы без правильного заголовка `X-Telegram-Bot-Api-Secret-Token` отклоняются (401).

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # впишите BOT_TOKEN, WEBHOOK_BASE_URL оставьте пустым
python main.py
```

Без `WEBHOOK_BASE_URL` бот стартует в режиме long polling. При запуске он снимает вебхук, так что после
локальных тестов бот на Render нужно перезапустить (Manual Deploy → Restart), чтобы он снова поставил вебхук.

## Деплой на Render: пошагово

### 1. Создать бота в @BotFather
1. Откройте в Telegram [@BotFather](https://t.me/BotFather) и отправьте `/newbot`.
2. Задайте имя и username (должен заканчиваться на `bot`).
3. Скопируйте токен вида `123456789:AA...` и никому его не показывайте.
4. Если нужно, задайте описание и аватар через `/setdescription` и `/setuserpic`.

### 2. Залить проект на GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<ваш-логин>/<репозиторий>.git
git push -u origin main
```
Файл `.env` в репозиторий не попадает (он в `.gitignore`). Токен храните только в настройках Render.

### 3. Создать Web Service на Render
Вариант А, через Blueprint (используется `render.yaml`):
1. [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**.
2. Выберите репозиторий. Render прочитает `render.yaml` и попросит значение `BOT_TOKEN`; вставьте токен.
3. Нажмите **Apply**.

Вариант Б, вручную:
1. **New** → **Web Service** → выберите репозиторий.
2. Runtime: **Python 3**, Build Command: `pip install -r requirements.txt`, Start Command: `python main.py`, Instance Type: **Free**.
3. В **Environment** добавьте `BOT_TOKEN` = ваш токен (и, по желанию, `PYTHON_VERSION` = `3.12.8`).
4. **Create Web Service**.

После деплоя в логах появится строка `Webhook set: https://<сервис>.onrender.com/webhook/***`.
Откройте бота в Telegram и отправьте `/start`.

### 4. Настроить UptimeRobot
Бесплатный сервис на Render засыпает примерно через 15 минут без входящих запросов. Чтобы этого не было:
1. Зарегистрируйтесь на [uptimerobot.com](https://uptimerobot.com).
2. **Add New Monitor** → тип **HTTP(s)**.
3. URL: адрес сервиса, например `https://vishnya-bot.onrender.com/` (корень, он отвечает `ok`).
4. Monitoring Interval: **5 minutes** → **Create Monitor**.

Учтите, что бесплатный тариф Render даёт ограниченное число часов работы в месяц на аккаунт. Одного
постоянно работающего сервиса в этот лимит хватает.

### 5. Логи и рекламные метки
Логи: страница сервиса на Render → вкладка **Logs**.

Для каждой рекламной площадки делайте свою ссылку с параметром:
```
https://t.me/<username_бота>?start=tiktok_1
https://t.me/<username_бота>?start=vk_ads
```
Параметр может содержать только `A-Z a-z 0-9 _ -` и быть не длиннее 64 символов.
При каждом `/start` в логах появляется строка:
```
START user_id=123456789 source=tiktok_1
```
Без параметра будет `source=none`. Чтобы посмотреть переходы с конкретной площадки, введите в поиск
по логам Render, например, `source=tiktok_1`. Бот ничего не хранит, а Render держит логи бесплатного
сервиса ограниченное время, так что если статистика нужна надолго, выгружайте её регулярно.

### 6. Перенос на VPS (код менять не нужно)
Задайте `WEBHOOK_BASE_URL` = ваш HTTPS-адрес (например, `https://bot.example.com`) и проксируйте его через
nginx/Caddy на `PORT`. Telegram принимает вебхуки только по HTTPS на портах 443, 80, 88 или 8443.
Без `WEBHOOK_BASE_URL` бот будет работать через polling, тогда ни домен, ни HTTPS не нужны.

**systemd**, файл `/etc/systemd/system/vishnya-bot.service`:
```ini
[Unit]
Description=Vishnya Telegram bot
After=network-online.target

[Service]
WorkingDirectory=/opt/vishnya-bot
EnvironmentFile=/opt/vishnya-bot/.env
ExecStart=/opt/vishnya-bot/.venv/bin/python main.py
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vishnya-bot
journalctl -u vishnya-bot -f            # логи, в том числе строки START
```

**Docker**, `Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```
```bash
docker build -t vishnya-bot .
docker run -d --restart=always --env-file .env -p 8080:8080 --name vishnya-bot vishnya-bot
docker logs -f vishnya-bot
```

## Принятые решения
- **Картинка `welcome.jpg`** — баннер приложения. Чтобы сменить его, замените файл, сохранив имя.
- **Путь вебхука** строится из секрета (`/webhook/<WEBHOOK_SECRET>`), а не из токена, чтобы токен не попадал в URL.
  Секрет также передаётся в `set_webhook` как `secret_token`, и каждый входящий запрос проверяется.
- **Сгенерированный секрет** меняется при каждом рестарте. Это не проблема, потому что вебхук ставится заново при
  каждом старте. Если нужен постоянный адрес, задайте `WEBHOOK_SECRET` вручную.
- **Вебхук при остановке не удаляется**, закрывается только HTTP-сессия бота. Так при перезапуске или передеплое
  на Render Telegram придержит входящие сообщения и доставит их новому процессу, а не потеряет.
- **Access-лог aiohttp отключён**, потому что в нём виден путь вебхука с секретом. Токен в логи не пишется.
- **Кэш `file_id`** живёт в памяти. После рестарта первый `/start` снова загрузит файл с диска. Если Telegram
  отклонит закэшированный `file_id`, бот загрузит картинку заново.
- **Версия Python** на Render зафиксирована как 3.12.8 через `PYTHON_VERSION` в `render.yaml`.
- **`.env`** читается встроенным мини-парсером в `config.py` только для локального запуска, без лишней зависимости.
  Переменные окружения имеют приоритет над `.env`.
- **Неизвестные callback-кнопки** (например, со старых сообщений) просто закрываются через `answer()`.
