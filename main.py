import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from config import Config, load_config
from handlers import router

logger = logging.getLogger("bot")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # aiohttp.access пишет каждый запрос с путём, а в пути — секрет вебхука
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


async def health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


def run_webhook(config: Config) -> None:
    bot = Bot(token=config.bot_token)
    dp = build_dispatcher()

    async def on_startup(bot: Bot) -> None:
        await bot.set_webhook(
            url=config.webhook_url,
            secret_token=config.webhook_secret,
            drop_pending_updates=False,
            allowed_updates=dp.resolve_used_update_types(),
        )
        logger.info("Webhook set: %s/webhook/***", config.webhook_base_url)

    async def on_shutdown(bot: Bot) -> None:
        # Вебхук не удаляем: при рестарте на Render новый процесс поставит его заново,
        # а входящие апдейты Telegram подержит и доставит повторно
        await bot.session.close()
        logger.info("Bot session closed")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    app.router.add_get("/", health)
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=config.webhook_secret,
    ).register(app, path=config.webhook_path)
    setup_application(app, dp, bot=bot)

    logger.info("Starting webhook server on 0.0.0.0:%s", config.port)
    web.run_app(app, host="0.0.0.0", port=config.port, print=None)


async def run_polling(config: Config) -> None:
    bot = Bot(token=config.bot_token)
    dp = build_dispatcher()
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("WEBHOOK_BASE_URL not set, starting long polling")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        logger.info("Bot session closed")


def main() -> None:
    setup_logging()
    config = load_config()
    if config.use_webhook:
        run_webhook(config)
    else:
        asyncio.run(run_polling(config))


if __name__ == "__main__":
    main()
