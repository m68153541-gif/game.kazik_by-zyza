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
from aiohttp import web

# ============ НАСТРОЙКИ ============
BOT_TOKEN = os.getenv("BOT_TOKEN")  # добавь в Render → Environment
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

def play_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎮 Играть", web_app=WebAppInfo(url=WEBAPP_URL))]
        ]
    )

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=play_kb())

@dp.message(F.web_app_data)
async def on_webapp_data(message: Message):
    await message.answer(f"📩 Данные: <code>{message.web_app_data.data}</code>")

# ============ HEALTH CHECK ДЛЯ RENDER ============
async def handle_health(request):
    return web.Response(text="Bot is running!")

async def main():
    # мини-веб-сервер для Render
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web-сервер запущен на порту {port}")

    # запуск бота
    print("Бот запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
