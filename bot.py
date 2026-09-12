class RegisterBody(BaseModel):
    initData: str = ""
    name: str
    guest_id: str = ""   # ← новое: с фронта, для браузера

@app.post("/api/register")
def register(body: RegisterBody):
    # 1. Пытаемся проверить Telegram
    user = verify_init_data(body.initData) if body.initData else None

    # 2. Определяем уникальный внешний ключ игрока
    if user:
        # Из Telegram — используем реальный TG ID
        external_id = "tg_" + str(user["id"])
        default_name = user.get("first_name", "Игрок")
    else:
        # Браузер — используем guest_id с фронта или генерируем
        guest_id = (body.guest_id or "").strip()
        if not guest_id or len(guest_id) < 8:
            # генерируем новый guest_id
            import uuid
            guest_id = uuid.uuid4().hex[:16]
        external_id = "guest_" + guest_id
        default_name = "Гость"

    name = (body.name or "").strip()[:20] or default_name

    conn = db()
    row = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (external_id,)).fetchone()

    if row:
        # обновим имя
        conn.execute("UPDATE online_players SET name = ? WHERE telegram_id = ?", (name, external_id))
        conn.commit()
        row = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (external_id,)).fetchone()
        conn.close()
        return {"ok": True, "player": dict(row), "new": False, "guest_id": guest_id if not user else ""}

    # новый игрок
    gid = generate_game_id(conn)
    conn.execute(
        "INSERT INTO online_players (telegram_id, game_id, name) VALUES (?, ?, ?)",
        (external_id, gid, name)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM online_players WHERE telegram_id = ?", (external_id,)).fetchone()
    conn.close()
    return {"ok": True, "player": dict(row), "new": True, "guest_id": guest_id if not user else ""}
