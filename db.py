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
CREATE TABLE IF NOT EXISTS bot_users (
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

CREATE TABLE IF NOT EXISTS bot_events (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES bot_users(user_id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    event        TEXT NOT NULL,
    content_type TEXT,
    text         TEXT,
    source       TEXT
);

CREATE INDEX IF NOT EXISTS bot_events_user_time_idx ON bot_events (user_id, created_at);

CREATE OR REPLACE VIEW bot_users_overview WITH (security_invoker = true) AS
SELECT
    u.user_id,
    CASE WHEN u.username IS NOT NULL THEN '@' || u.username END AS username,
    concat_ws(' ', u.first_name, u.last_name) AS name,
    COALESCE(u.source, 'none') AS source,
    u.last_source,
    (u.first_seen AT TIME ZONE 'Europe/Moscow')::timestamp(0) AS first_seen_msk,
    (u.last_seen AT TIME ZONE 'Europe/Moscow')::timestamp(0) AS last_seen_msk,
    u.starts_count,
    COUNT(e.id) FILTER (WHERE e.event = 'message') AS messages_count,
    COUNT(e.id) FILTER (WHERE e.event = 'about') AS about_clicks,
    string_agg(
        to_char(e.created_at AT TIME ZONE 'Europe/Moscow', 'DD.MM.YYYY HH24:MI') || '  ' ||
        CASE e.event
            WHEN 'start'   THEN '/start' || COALESCE(' ' || e.source, '')
            WHEN 'about'   THEN '[кнопка «О приложении»]'
            WHEN 'back'    THEN '[кнопка «Назад»]'
            ELSE concat_ws(' ',
                CASE e.content_type
                    WHEN 'text'       THEN NULL
                    WHEN 'photo'      THEN '[фото]'
                    WHEN 'video'      THEN '[видео]'
                    WHEN 'video_note' THEN '[кружок]'
                    WHEN 'voice'      THEN '[голосовое]'
                    WHEN 'audio'      THEN '[аудио]'
                    WHEN 'document'   THEN '[файл]'
                    WHEN 'sticker'    THEN '[стикер]'
                    WHEN 'animation'  THEN '[гиф]'
                    ELSE '[' || COALESCE(e.content_type, 'сообщение') || ']'
                END,
                NULLIF(e.text, ''))
        END,
        E'\\n' ORDER BY e.created_at
    ) AS history
FROM bot_users u
LEFT JOIN bot_events e ON e.user_id = u.user_id
GROUP BY u.user_id
ORDER BY u.last_seen DESC;

ALTER TABLE bot_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_events ENABLE ROW LEVEL SECURITY;

-- В Supabase закрываем таблицы от публичного API: читать их можно только из панели
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON bot_users, bot_events, bot_users_overview FROM anon, authenticated;
    END IF;
END $$;
"""

UPSERT_USER = """
INSERT INTO bot_users (user_id, username, first_name, last_name, language_code, is_premium,
                       source, last_source, starts_count)
VALUES ($1, $2, $3, $4, $5, $6, $7, $7, $8)
ON CONFLICT (user_id) DO UPDATE SET
    username      = EXCLUDED.username,
    first_name    = EXCLUDED.first_name,
    last_name     = EXCLUDED.last_name,
    language_code = EXCLUDED.language_code,
    is_premium    = EXCLUDED.is_premium,
    source        = COALESCE(bot_users.source, EXCLUDED.source),
    last_source   = COALESCE(EXCLUDED.last_source, bot_users.last_source),
    starts_count  = bot_users.starts_count + EXCLUDED.starts_count,
    last_seen     = now()
"""

INSERT_EVENT = """
INSERT INTO bot_events (user_id, event, content_type, text, source)
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
