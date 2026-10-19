import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message

import db
import keyboards
import texts

logger = logging.getLogger(__name__)
router = Router()

WELCOME_PATH = Path(__file__).resolve().parent / texts.WELCOME_IMAGE

# file_id картинки после первой загрузки; живёт только в памяти процесса
_welcome_file_id: str | None = None


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    global _welcome_file_id

    source = command.args.strip() if command.args and command.args.strip() else "none"
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info("START user_id=%s source=%s", user_id, source)
    db.track(message.from_user, "start", source=None if source == "none" else source)

    photo = _welcome_file_id or FSInputFile(WELCOME_PATH)
    try:
        sent = await message.answer_photo(
            photo=photo,
            caption=texts.START_CAPTION,
            reply_markup=keyboards.start_keyboard(),
        )
    except TelegramBadRequest:
        if _welcome_file_id is None:
            raise
        # file_id протух — загружаем файл заново
        logger.warning("Cached file_id rejected, re-uploading image")
        _welcome_file_id = None
        sent = await message.answer_photo(
            photo=FSInputFile(WELCOME_PATH),
            caption=texts.START_CAPTION,
            reply_markup=keyboards.start_keyboard(),
        )

    if _welcome_file_id is None and sent.photo:
        _welcome_file_id = sent.photo[-1].file_id


async def _edit_caption(callback: CallbackQuery, caption: str, markup) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.edit_caption(caption=caption, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise


@router.callback_query(F.data == texts.CB_ABOUT)
async def on_about(callback: CallbackQuery) -> None:
    db.track(callback.from_user, "about")
    try:
        await _edit_caption(callback, texts.ABOUT_CAPTION, keyboards.about_keyboard())
    finally:
        await callback.answer()


@router.callback_query(F.data == texts.CB_BACK)
async def on_back(callback: CallbackQuery) -> None:
    db.track(callback.from_user, "back")
    try:
        await _edit_caption(callback, texts.START_CAPTION, keyboards.start_keyboard())
    finally:
        await callback.answer()


@router.callback_query()
async def on_unknown_callback(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message()
async def fallback(message: Message) -> None:
    db.track(
        message.from_user,
        "message",
        content_type=message.content_type,
        text=message.text or message.caption,
    )
    await message.answer(texts.FALLBACK_TEXT)
