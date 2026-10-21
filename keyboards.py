from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import texts


def _rustore_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text=texts.BTN_RUSTORE, url=texts.RUSTORE_URL)


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_ABOUT, callback_data=texts.CB_ABOUT)],
            [_rustore_button()],
        ]
    )


def about_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_BACK, callback_data=texts.CB_BACK)],
            [_rustore_button()],
        ]
    )
