import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)

# ============ НАСТРОЙКИ ============
BOT_TOKEN = os.getenv("BOT_TOKEN", "8665249676:AAGF5cu1i29JHgCUqYJ6iRfBYqSILA44Jag")
WEBAPP_URL = "https://m68153541-gif.github.io/game.kazik_by-zyza/"
# ==================================

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


WELCOME_TEXT = (
    "👋 <b>Привет!</b>\n\n"
    "🎰 Я бот для игры в <b>мини-казино</b> — прямо внутри Telegram!\n\n"
    "✨ Я полностью <b>развлекательный</b>: играй в слоты, рулетку, "
    "блэкджек, кости и «20 ячеек» — без регистрации и вложений.\n\n"
    "🚀 Разработчик уже готовит <b>новые обновления</b>: онлайн-режим, "
    "новые игры и бонусы.\n\n"
    "😂 Со мной <b>весело и не скучно</b> — заходи и проверь сам!\n\n"
    "👇 Жми кнопку ниже и играй:"
)


def play_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 Играть",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ]
    )


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=play_kb())


@dp.message(F.web_app_data)
async def on_webapp_data(message: Message):
    await message.answer(
        f"📩 Данные из Mini App:\n<code>{message.web_app_data.data}</code>"
    )


async def main():
    print("Бот запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
