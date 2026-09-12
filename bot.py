import asyncio
import logging
import os
import sqlite3
import random
import json
from urllib.parse import parse_qsl
import hashlib
import hmac

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ============ НАСТРОЙКИ ============
BOT_TOKEN = os.getenv("BOT_TOKEN", "ТОКЕН_СЮДА")
WEBAPP_URL = "https://m68153541-gif.github.io/game.kazik_by-zyza/"
# ==================================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ============ БАЗА ДАННЫХ ============
DB_FILE = "kazik.db"

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS online_players (
            telegram_id INTEGER PRIMARY KEY,
            game_id     TEXT UNIQUE NOT NULL,
            name        TEXT NOT NULL,
            balance     INTEGER DEFAULT 100000,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ============ ПРОВЕРКА TELEGRAM initData ============
def verify_init_data(init_data: str):
    """Проверяет подпись Telegram. Возвращает dict или None."""
    if not init_data:
        return None
    try:
        data = dict(parse_qsl(init_data))
        hash_ = data.pop("hash", None)
        if not hash_:
            return None
        check_str = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check_str.encode(), hashlib.sha256).hexdigest()
        if calc != hash_:
            return None
        return json.loads(data.get("user", "{}"))
    except Exception as e:
        print("verify_init_data error:", e)
        return None

# ============ ГЕНЕРАЦИЯ 6-ЗНАЧНОГО ID ============
def generate_game_id(conn):
    while True:
        gid = str(random.randint(100000, 999999))
        row = conn.execute("SELECT 1 FROM online_players WHERE game_id = ?", (gid,)).fetchone()
        if not row:
            return gid

# ============ FASTAPI ============
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class RegisterBody(BaseModel):
    initData: str
    name: str

@app.get("/")
def health():
    return {"status": "Bot is running!"}

@app.post("/api/register")
def register(body: RegisterBody):
    user = verify_init_data(body.initData)
    if not user:
        return {"error": "bad_auth"}

    tg_id = user.get("id")
    name = (body.name or "").strip()[:20] or user.get("first_name", "Игрок")

    conn = db()
    row = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (tg_id,)).fetchone()

    if row:
        # уже зарегистрирован — обновим имя и вернём
        conn.execute("UPDATE online_players SET name = ? WHERE telegram_id = ?", (name, tg_id))
        conn.commit()
        row = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (tg_id,)).fetchone()
        conn.close()
        return {"ok": True, "player": dict(row), "new": False}

    # новый игрок
    gid = generate_game_id(conn)
    conn.execute(
        "INSERT INTO online_players (telegram_id, game_id, name) VALUES (?, ?, ?)",
        (tg_id, gid, name)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (tg_id,)).fetchone()
    conn.close()
    return {"ok": True, "player": dict(row), "new": True}

@app.get("/api/me")
def get_me(initData: str):
    user = verify_init_data(initData)
    if not user:
        return {"error": "bad_auth"}
    tg_id = user.get("id")
    conn = db()
    row = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (tg_id,)).fetchone()
    conn.close()
    if not row:
        return {"error": "not_registered"}
    return {"ok": True, "player": dict(row)}

# ============ TELEGRAM БОТ ============
WELCOME_TEXT = (
    "👋 <b>Привет!</b>\n\n"
    "🎰 Я бот для игры в <b>мини-казино</b>!\n\n"
    "✨ Играй в слоты, рулетку, блэкджек, кости и другие игры.\n\n"
    "🚀 Скоро — онлайн-режим!\n\n"
    "👇 Жми кнопку ниже и играй:"
)

def play_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🎮 Играть", web_app=WebAppInfo(url=WEBAPP_URL))
        ]]
    )

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=play_kb())

# ============ ЗАПУСК ============
async def main():
    init_db()
    print("Сервер и бот запускаются...")
    await bot.delete_webhook(drop_pending_updates=True)

    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)), log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        server.serve(),
        dp.start_polling(bot),
    )

if __name__ == "__main__":
    asyncio.run(main())
