import asyncio
import logging
import os
import sqlite3
import random
import json
import uuid
import hashlib
import hmac
from urllib.parse import parse_qsl

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
import uvicorn

# ============ НАСТРОЙКИ ============
BOT_TOKEN = os.getenv("BOT_TOKEN", "8665249676:AAGF5cu1i29JHgCUqYJ6iRfBYqSILA44Jag")
WEBAPP_URL = "https://m68153541-gif.github.io/game.kazik_by-zyza/"
DB_FILE = "kazik_v6.db"
# ==================================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ============ БАЗА ============
def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS online_players (
            telegram_id TEXT PRIMARY KEY,
            game_id     TEXT UNIQUE NOT NULL,
            name        TEXT NOT NULL,
            balance     INTEGER DEFAULT 100000,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_game_id ON online_players(game_id);

        CREATE TABLE IF NOT EXISTS lobbies (
            lobby_id   TEXT PRIMARY KEY,
            host_id    TEXT NOT NULL,
            guest_id   TEXT,
            game_type  TEXT,
            status     TEXT DEFAULT 'waiting',
            state      TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            lobby_id   TEXT NOT NULL,
            from_id    TEXT NOT NULL,
            from_name  TEXT NOT NULL,
            text       TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ============ ПРОВЕРКА TELEGRAM ============
def verify_init_data(init_data: str):
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

def get_external_id(initData, guest_id):
    user = verify_init_data(initData) if initData else None
    if user:
        return "tg_" + str(user["id"])
    if guest_id:
        return "guest_" + guest_id
    return None

# ============ ГЕНЕРАЦИЯ ID ============
def generate_game_id(conn):
    for _ in range(30):
        gid = str(random.randint(100000, 999999))
        row = conn.execute("SELECT 1 FROM online_players WHERE game_id = ?", (gid,)).fetchone()
        if not row:
            return gid
    return str(random.randint(1000000, 9999999))

def generate_lobby_id(conn):
    for _ in range(30):
        lid = str(random.randint(100000, 999999))
        row = conn.execute("SELECT 1 FROM lobbies WHERE lobby_id = ?", (lid,)).fetchone()
        if not row:
            return lid
    return str(random.randint(1000000, 9999999))

# ============ FASTAPI ============
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# Универсальный обработчик OPTIONS (preflight)
@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "3600",
        }
    )

class RegisterBody(BaseModel):
    initData: str = ""
    name: str
    guest_id: str = ""

class LobbyCreateBody(BaseModel):
    initData: str = ""
    guest_id: str = ""
    game_type: str = "rps"

class LobbyJoinBody(BaseModel):
    initData: str = ""
    guest_id: str = ""

class LobbyLeaveBody(BaseModel):
    initData: str = ""
    guest_id: str = ""

@app.get("/")
def health():
    return {"status": "Bot is running!", "version": "1.2"}

# ---------- РЕГИСТРАЦИЯ ----------
@app.post("/api/register")
def register(body: RegisterBody):
    user = verify_init_data(body.initData) if body.initData else None

    if user:
        external_id = "tg_" + str(user["id"])
        default_name = user.get("first_name", "Игрок")
        guest_id_out = ""
    else:
        guest_id = (body.guest_id or "").strip()
        if not guest_id or len(guest_id) < 8:
            guest_id = uuid.uuid4().hex[:16]
        external_id = "guest_" + guest_id
        default_name = "Гость"
        guest_id_out = guest_id

    name = (body.name or "").strip()[:20] or default_name

    conn = db()
    row = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (external_id,)).fetchone()

    if row:
        conn.execute("UPDATE online_players SET name = ? WHERE telegram_id = ?", (name, external_id))
        conn.commit()
        row = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (external_id,)).fetchone()
        conn.close()
        return {"ok": True, "player": dict(row), "new": False, "guest_id": guest_id_out}

    gid = generate_game_id(conn)
    conn.execute(
        "INSERT INTO online_players (telegram_id, game_id, name) VALUES (?, ?, ?)",
        (external_id, gid, name)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (external_id,)).fetchone()
    conn.close()
    return {"ok": True, "player": dict(row), "new": True, "guest_id": guest_id_out}

@app.get("/api/me")
def get_me(initData: str = "", guest_id: str = ""):
    external_id = get_external_id(initData, guest_id)
    if not external_id:
        return {"error": "no_credentials"}
    conn = db()
    row = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (external_id,)).fetchone()
    conn.close()
    if not row:
        return {"error": "not_registered"}
    return {"ok": True, "player": dict(row)}

# ---------- ЛОББИ ----------
@app.post("/api/lobby/create")
def lobby_create(body: LobbyCreateBody):
    external_id = get_external_id(body.initData, body.guest_id)
    if not external_id:
        return {"error": "bad_auth"}

    conn = db()
    conn.execute("DELETE FROM lobbies WHERE host_id = ? AND status = 'waiting'", (external_id,))

    lid = generate_lobby_id(conn)
    conn.execute(
        "INSERT INTO lobbies (lobby_id, host_id, game_type, status) VALUES (?, ?, ?, 'waiting')",
        (lid, external_id, body.game_type)
    )
    conn.commit()
    conn.close()
    return {"ok": True, "lobby_id": lid}

@app.post("/api/lobby/join")
def lobby_join(body: LobbyJoinBody, lobby_id: str = Query(...)):
    external_id = get_external_id(body.initData, body.guest_id)
    if not external_id:
        return {"error": "bad_auth"}

    conn = db()
    lob = conn.execute("SELECT * FROM lobbies WHERE lobby_id = ?", (lobby_id,)).fetchone()
    if not lob:
        conn.close()
        return {"error": "not_found"}
    if lob["host_id"] == external_id:
        conn.close()
        return {"error": "own_lobby"}
    if lob["status"] not in ("waiting", "playing"):
        conn.close()
        return {"error": "closed"}

    conn.execute("UPDATE lobbies SET guest_id = ?, status = 'playing' WHERE lobby_id = ?",
                 (external_id, lobby_id))
    conn.commit()

    host = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (lob["host_id"],)).fetchone()
    guest = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (external_id,)).fetchone()
    conn.close()
    return {"ok": True, "lobby_id": lobby_id, "host": dict(host), "guest": dict(guest)}

@app.get("/api/lobby/{lobby_id}")
def lobby_info(lobby_id: str):
    conn = db()
    lob = conn.execute("SELECT * FROM lobbies WHERE lobby_id = ?", (lobby_id,)).fetchone()
    if not lob:
        conn.close()
        return {"error": "not_found"}
    result = {"ok": True, "lobby": dict(lob)}
    if lob["host_id"]:
        h = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (lob["host_id"],)).fetchone()
        if h: result["host"] = dict(h)
    if lob["guest_id"]:
        g = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (lob["guest_id"],)).fetchone()
        if g: result["guest"] = dict(g)
    conn.close()
    return result

@app.post("/api/lobby/leave")
def lobby_leave(body: LobbyLeaveBody, lobby_id: str = Query(...)):
    external_id = get_external_id(body.initData, body.guest_id)
    conn = db()
    lob = conn.execute("SELECT * FROM lobbies WHERE lobby_id = ?", (lobby_id,)).fetchone()
    if not lob:
        conn.close()
        return {"ok": True}
    if lob["host_id"] == external_id:
        conn.execute("DELETE FROM lobbies WHERE lobby_id = ?", (lobby_id,))
    else:
        conn.execute("UPDATE lobbies SET guest_id = NULL, status = 'waiting' WHERE lobby_id = ?",
                     (lobby_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

# ---------- WEBSOCKET ----------
active_lobbies = {}

@app.websocket("/ws/lobby/{lobby_id}")
async def ws_lobby(ws: WebSocket, lobby_id: str):
    await ws.accept()

    if lobby_id not in active_lobbies:
        active_lobbies[lobby_id] = []

    info = {"ws": ws, "player_id": None, "name": None}
    active_lobbies[lobby_id].append(info)

    try:
        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
            except:
                continue

            action = msg.get("action")

            if action == "hello":
                info["player_id"] = msg.get("player_id")
                info["name"] = msg.get("name") or "Игрок"

                await broadcast(lobby_id, {"type": "system", "text": info["name"] + " вошёл в лобби"})

                players = [{"id": c["player_id"], "name": c["name"]}
                           for c in active_lobbies[lobby_id] if c["player_id"]]
                await broadcast(lobby_id, {"type": "players", "players": players})

            elif action == "chat":
                txt = (msg.get("text") or "").strip()[:200]
                if not txt:
                    continue
                conn = db()
                conn.execute(
                    "INSERT INTO chat_messages (lobby_id, from_id, from_name, text) VALUES (?, ?, ?, ?)",
                    (lobby_id, info["player_id"], info["name"], txt)
                )
                conn.commit()
                conn.close()
                await broadcast(lobby_id, {
                    "type": "chat",
                    "from": info["player_id"],
                    "name": info["name"],
                    "text": txt
                })

            elif action == "game_move":
                await broadcast(lobby_id, {
                    "type": "game_move",
                    "from": info["player_id"],
                    "data": msg.get("data")
                }, skip=info["player_id"])

            elif action == "game_start":
                await broadcast(lobby_id, {
                    "type": "game_start",
                    "game_type": msg.get("game_type"),
                    "from": info["player_id"]
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("ws error:", e)
    finally:
        if info in active_lobbies.get(lobby_id, []):
            active_lobbies[lobby_id].remove(info)

        if lobby_id in active_lobbies and active_lobbies[lobby_id]:
            await broadcast(lobby_id, {
                "type": "system",
                "text": (info["name"] or "Игрок") + " вышел из лобби"
            })

        if lobby_id in active_lobbies and not active_lobbies[lobby_id]:
            del active_lobbies[lobby_id]

async def broadcast(lobby_id: str, msg: dict, skip: str = None):
    if lobby_id not in active_lobbies:
        return
    text = json.dumps(msg, ensure_ascii=False)
    for c in list(active_lobbies[lobby_id]):
        if skip and c["player_id"] == skip:
            continue
        try:
            await c["ws"].send_text(text)
        except:
            pass

# ============ БОТ ============
WELCOME_TEXT = (
    "👋 <b>Привет!</b>\n\n"
    "🎰 Я бот для игры в <b>мини-казино</b>!\n\n"
    "✨ Играй в слоты, рулетку, блэкджек, кости и другие игры.\n\n"
    "🚀 Теперь работает <b>онлайн-режим</b> — создавай лобби и играй с друзьями!\n\n"
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
