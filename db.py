"""Хранение пользователей и их активности в PostgreSQL (например, Supabase).

Если DATABASE_URL не задана или база недоступна, бот работает без неё.
Запись идёт в фоне, чтобы не задерживать ответы пользователю.
"""

import asyncio
import logging

import asyncpg
from aiogram.types import User

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS bot;

-- Старые объекты из public переносим в схему bot (данные сохраняются)
DROP VIEW IF EXISTS public.bot_users_overview;
DO $$
BEGIN
    IF to_regclass('public.bot_users') IS NOT NULL AND to_regclass('bot.users') IS NULL THEN
        ALTER TABLE public.bot_users SET SCHEMA bot;
        ALTER TABLE bot.bot_users RENAME TO users;
    END IF;
    IF to_regclass('public.bot_events') IS NOT NULL AND to_regclass('bot.events') IS NULL THEN
        ALTER TABLE public.bot_events SET SCHEMA bot;
        ALTER TABLE bot.bot_events RENAME TO events;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS bot.users (
    user_id       BIGINT PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    last_name     TEXT,
    language_code TEXT,
    is_premium    BOOLEAN,
    source        TEXT,
    last_source   TEXT,
    starts_count  INTEGER NOT NULL DEFAULT 0,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bot.events (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES bot.users(user_id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    event        TEXT NOT NULL,
    content_type TEXT,
    text         TEXT,
    source       TEXT
);

CREATE INDEX IF NOT EXISTS bot_events_user_time_idx ON bot.events (user_id, created_at);

ALTER TABLE bot.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot.events ENABLE ROW LEVEL SECURITY;

COMMENT ON SCHEMA bot IS 'Служебные таблицы бота. Смотреть удобнее через представления в public';
COMMENT ON TABLE bot.users IS 'Пользователи бота (сырые данные)';
COMMENT ON TABLE bot.events IS 'Все действия пользователей (сырые данные)';

-- Читаемый тип сообщения
CREATE OR REPLACE FUNCTION bot.content_label(content_type TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $f$
    SELECT CASE content_type
        WHEN 'text'       THEN 'текст'
        WHEN 'photo'      THEN 'фото'
        WHEN 'video'      THEN 'видео'
        WHEN 'video_note' THEN 'кружок'
        WHEN 'voice'      THEN 'голосовое'
        WHEN 'audio'      THEN 'аудио'
        WHEN 'document'   THEN 'файл'
        WHEN 'sticker'    THEN 'стикер'
        WHEN 'animation'  THEN 'гиф'
        WHEN 'contact'    THEN 'контакт'
        WHEN 'location'   THEN 'геолокация'
        ELSE COALESCE(content_type, 'сообщение')
    END
$f$;

-- Одна строка истории: действие или сообщение
CREATE OR REPLACE FUNCTION bot.event_label(event TEXT, content_type TEXT, text TEXT, source TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE AS $f$
    SELECT CASE event
        WHEN 'start' THEN '/start' || COALESCE(' ' || source, '')
        WHEN 'about' THEN '[кнопка «О приложении»]'
        WHEN 'back'  THEN '[кнопка «Назад»]'
        ELSE concat_ws(' ',
            CASE WHEN content_type = 'text' THEN NULL
                 ELSE '[' || bot.content_label(content_type) || ']' END,
            NULLIF(text, ''))
    END
$f$;

DROP VIEW IF EXISTS public."Пользователи";
CREATE VIEW public."Пользователи" WITH (security_invoker = true) AS
SELECT
    u.user_id AS "ID",
    CASE WHEN u.username IS NOT NULL THEN '@' || u.username END AS "Юзернейм",
    NULLIF(concat_ws(' ', u.first_name, u.last_name), '') AS "Имя",
    COALESCE(u.source, 'без метки') AS "Откуда пришёл",
    u.last_source AS "Последняя метка",
    (u.first_seen AT TIME ZONE 'Europe/Moscow')::timestamp(0) AS "Первый заход (МСК)",
    (u.last_seen AT TIME ZONE 'Europe/Moscow')::timestamp(0) AS "Последний визит (МСК)",
    u.starts_count AS "Нажал /start",
    COUNT(e.id) FILTER (WHERE e.event = 'message') AS "Сообщений",
    COUNT(e.id) FILTER (WHERE e.event = 'about') AS "Открыл «О приложении»",
    string_agg(
        to_char(e.created_at AT TIME ZONE 'Europe/Moscow', 'DD.MM.YYYY HH24:MI') || '  ' ||
        bot.event_label(e.event, e.content_type, e.text, e.source),
        E'\\n' ORDER BY e.created_at
    ) AS "История",
    u.language_code AS "Язык",
    COALESCE(u.is_premium, false) AS "Premium"
FROM bot.users u
LEFT JOIN bot.events e ON e.user_id = u.user_id
GROUP BY u.user_id
ORDER BY u.last_seen DESC;

COMMENT ON VIEW public."Пользователи" IS
    'Все, кто заходил в бота: откуда пришёл, когда, сколько писал. Нажмите на ячейку «История», чтобы увидеть всю переписку';
COMMENT ON COLUMN public."Пользователи"."ID" IS 'ID пользователя в Telegram';
COMMENT ON COLUMN public."Пользователи"."Юзернейм" IS '@username в Telegram (пусто, если его нет)';
COMMENT ON COLUMN public."Пользователи"."Имя" IS 'Имя и фамилия из профиля Telegram';
COMMENT ON COLUMN public."Пользователи"."Откуда пришёл" IS 'Рекламная метка первого захода (ссылка t.me/бот?start=метка)';
COMMENT ON COLUMN public."Пользователи"."Последняя метка" IS 'Метка последнего перехода, если человек заходил повторно по другой ссылке';
COMMENT ON COLUMN public."Пользователи"."Первый заход (МСК)" IS 'Когда впервые написал боту, московское время';
COMMENT ON COLUMN public."Пользователи"."Последний визит (МСК)" IS 'Последнее действие в боте, московское время';
COMMENT ON COLUMN public."Пользователи"."Нажал /start" IS 'Сколько раз открывал меню командой /start';
COMMENT ON COLUMN public."Пользователи"."Сообщений" IS 'Сколько сообщений написал боту';
COMMENT ON COLUMN public."Пользователи"."Открыл «О приложении»" IS 'Сколько раз нажимал кнопку «О приложении»';
COMMENT ON COLUMN public."Пользователи"."История" IS 'Все действия и сообщения по порядку';
COMMENT ON COLUMN public."Пользователи"."Язык" IS 'Язык интерфейса Telegram';
COMMENT ON COLUMN public."Пользователи"."Premium" IS 'Есть ли Telegram Premium';

DROP VIEW IF EXISTS public."Сообщения";
CREATE VIEW public."Сообщения" WITH (security_invoker = true) AS
SELECT
    (e.created_at AT TIME ZONE 'Europe/Moscow')::timestamp(0) AS "Время (МСК)",
    e.user_id AS "ID",
    CASE WHEN u.username IS NOT NULL THEN '@' || u.username END AS "Юзернейм",
    NULLIF(concat_ws(' ', u.first_name, u.last_name), '') AS "Имя",
    bot.content_label(e.content_type) AS "Тип",
    e.text AS "Текст",
    COALESCE(u.source, 'без метки') AS "Откуда пришёл"
FROM bot.events e
JOIN bot.users u ON u.user_id = e.user_id
WHERE e.event = 'message'
ORDER BY e.created_at DESC;

COMMENT ON VIEW public."Сообщения" IS 'Все сообщения пользователей, новые сверху';
COMMENT ON COLUMN public."Сообщения"."Время (МСК)" IS 'Когда отправлено, московское время';
COMMENT ON COLUMN public."Сообщения"."ID" IS 'ID пользователя в Telegram';
COMMENT ON COLUMN public."Сообщения"."Юзернейм" IS '@username отправителя';
COMMENT ON COLUMN public."Сообщения"."Имя" IS 'Имя отправителя из профиля Telegram';
COMMENT ON COLUMN public."Сообщения"."Тип" IS 'текст, фото, видео, голосовое и т. д.';
COMMENT ON COLUMN public."Сообщения"."Текст" IS 'Текст сообщения или подпись к фото/видео';
COMMENT ON COLUMN public."Сообщения"."Откуда пришёл" IS 'Рекламная метка отправителя';

DROP VIEW IF EXISTS public."Источники";
CREATE VIEW public."Источники" WITH (security_invoker = true) AS
WITH per_user AS (
    SELECT
        u.user_id,
        COALESCE(u.source, 'без метки') AS source,
        u.first_seen,
        u.last_seen,
        EXISTS (SELECT 1 FROM bot.events e WHERE e.user_id = u.user_id AND e.event = 'message') AS wrote,
        EXISTS (SELECT 1 FROM bot.events e WHERE e.user_id = u.user_id AND e.event = 'about') AS opened_about
    FROM bot.users u
)
SELECT
    source AS "Источник",
    COUNT(*) AS "Пользователей",
    COUNT(*) FILTER (WHERE first_seen >= now() - interval '1 day') AS "Новых за 24 часа",
    COUNT(*) FILTER (WHERE first_seen >= now() - interval '7 days') AS "Новых за 7 дней",
    COUNT(*) FILTER (WHERE opened_about) AS "Открыли «О приложении»",
    COUNT(*) FILTER (WHERE wrote) AS "Написали боту",
    (MIN(first_seen) AT TIME ZONE 'Europe/Moscow')::timestamp(0) AS "Первый заход (МСК)",
    (MAX(last_seen) AT TIME ZONE 'Europe/Moscow')::timestamp(0) AS "Последняя активность (МСК)"
FROM per_user
GROUP BY source
ORDER BY COUNT(*) DESC;

COMMENT ON VIEW public."Источники" IS 'Статистика по рекламным меткам: сколько людей пришло с каждой ссылки';
COMMENT ON COLUMN public."Источники"."Источник" IS 'Рекламная метка из ссылки t.me/бот?start=метка';
COMMENT ON COLUMN public."Источники"."Пользователей" IS 'Сколько человек пришло с этой метки за всё время';
COMMENT ON COLUMN public."Источники"."Новых за 24 часа" IS 'Пришли за последние сутки';
COMMENT ON COLUMN public."Источники"."Новых за 7 дней" IS 'Пришли за последнюю неделю';
COMMENT ON COLUMN public."Источники"."Открыли «О приложении»" IS 'Сколько из них хотя бы раз нажали «О приложении»';
COMMENT ON COLUMN public."Источники"."Написали боту" IS 'Сколько из них хотя бы раз написали боту';
COMMENT ON COLUMN public."Источники"."Первый заход (МСК)" IS 'Когда пришёл первый человек с этой метки';
COMMENT ON COLUMN public."Источники"."Последняя активность (МСК)" IS 'Последнее действие кого-либо с этой метки';

-- В Supabase закрываем данные от публичного API: смотреть их можно только из панели
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA bot FROM anon, authenticated;
        REVOKE ALL ON SCHEMA bot FROM anon, authenticated;
        REVOKE ALL ON public."Пользователи", public."Сообщения", public."Источники"
            FROM anon, authenticated;
    END IF;
END $$;
"""

UPSERT_USER = """
INSERT INTO bot.users AS u (user_id, username, first_name, last_name, language_code, is_premium,
                       source, last_source, starts_count)
VALUES ($1, $2, $3, $4, $5, $6, $7, $7, $8)
ON CONFLICT (user_id) DO UPDATE SET
    username      = EXCLUDED.username,
    first_name    = EXCLUDED.first_name,
    last_name     = EXCLUDED.last_name,
    language_code = EXCLUDED.language_code,
    is_premium    = EXCLUDED.is_premium,
    source        = COALESCE(u.source, EXCLUDED.source),
    last_source   = COALESCE(EXCLUDED.last_source, u.last_source),
    starts_count  = u.starts_count + EXCLUDED.starts_count,
    last_seen     = now()
"""

INSERT_EVENT = """
INSERT INTO bot.events (user_id, event, content_type, text, source)
VALUES ($1, $2, $3, $4, $5)
"""

_pool: asyncpg.Pool | None = None
_tasks: set[asyncio.Task] = set()


async def connect(dsn: str | None) -> None:
    global _pool
    if not dsn:
        logger.info("DATABASE_URL not set, activity is not stored")
        return
    try:
        # statement_cache_size=0 нужен для работы через пулер Supabase
        _pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=5, statement_cache_size=0, timeout=15
        )
        async with _pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(SCHEMA)
        logger.info("Database connected")
    except Exception as e:
        # Пароль из строки подключения в лог не попадает: пишем только тип ошибки
        logger.error("Database unavailable, continuing without it: %s", type(e).__name__)
        if _pool is not None:
            await _pool.close()
        _pool = None


async def close() -> None:
    global _pool
    if _tasks:
        await asyncio.gather(*_tasks, return_exceptions=True)
    if _pool is not None:
        await _pool.close()
        _pool = None


async def _save(user: User, event: str, content_type: str | None, text: str | None,
                source: str | None) -> None:
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    UPSERT_USER,
                    user.id, user.username, user.first_name, user.last_name,
                    user.language_code, user.is_premium,
                    source if event == "start" else None,
                    1 if event == "start" else 0,
                )
                await conn.execute(INSERT_EVENT, user.id, event, content_type, text, source)
    except Exception:
        logger.exception("Failed to save event %s for user_id=%s", event, user.id)


def track(user: User | None, event: str, *, content_type: str | None = None,
          text: str | None = None, source: str | None = None) -> None:
    """Сохранить событие в фоне. Ничего не делает, если базы нет."""
    if _pool is None or user is None:
        return
    task = asyncio.create_task(_save(user, event, content_type, text, source))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
