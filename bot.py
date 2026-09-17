"""
Telegram-бот для Golden Palace
- Приветствие при /start
- Рассылка каждый час — всем сразу, но разными сообщениями
- Задержка 3 секунды между отправками
- Интересные факты, напоминания, новости
- Работает в личке и в группах
"""
import os
import json
import time
import random
import threading
import urllib.request

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
GAME_URL = 'https://game-kazik-by-zyza.onrender.com'
DATA_FILE = 'bot_subscribers.json'

# ═══════════════════════════════════════════════════════════
#  ХРАНИЛИЩЕ ПОДПИСЧИКОВ
# ═══════════════════════════════════════════════════════════
subscribers = {
    'users': {},   # {chat_id: {'first_name': ..., 'username': ..., 'added_at': ts}}
    'groups': {}   # {chat_id: {'title': ..., 'added_at': ts}}
}

# Настройки рассылки
BROADCAST_INTERVAL = 3600      # 1 час между рассылками
SEND_DELAY = 3                 # 3 секунды между отправками


def load_data():
    global subscribers
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            subscribers['users'] = data.get('users', {})
            subscribers['groups'] = data.get('groups', {})
            print(f'📊 Загружено: {len(subscribers["users"])} юзеров, {len(subscribers["groups"])} групп')
    except Exception:
        print('📊 Файл подписчиков пуст — создаём новый')


def save_data():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(subscribers, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print('❌ Ошибка сохранения подписчиков:', e)


# ═══════════════════════════════════════════════════════════
#  TELEGRAM API
# ═══════════════════════════════════════════════════════════
def api_call(method, payload):
    if not BOT_TOKEN:
        return None
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/{method}'
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f'❌ API {method} error:', e)
        return None


def send_message(chat_id, text, keyboard=None, parse_mode='HTML'):
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode,
        'disable_web_page_preview': True
    }
    if keyboard:
        payload['reply_markup'] = keyboard
    return api_call('sendMessage', payload)


def play_button():
    return {'inline_keyboard': [[{'text': '🎰 ИГРАТЬ', 'url': GAME_URL}]]}


def play_button_group():
    return {'inline_keyboard': [[{'text': '🎰 ИГРАТЬ С ДРУЗЬЯМИ', 'url': GAME_URL}]]}


# ═══════════════════════════════════════════════════════════
#  КОНТЕНТ
# ═══════════════════════════════════════════════════════════
WELCOME_TEXT = """👑 <b>ДОБРО ПОЖАЛОВАТЬ В GOLDEN PALACE!</b> 👑

🎰 <b>Премиум казино прямо в Telegram</b>

Здесь ты найдёшь:
🎯 <b>Plinko</b> — падающий шарик с множителями до ×5
🎱 <b>Keno</b> — угадай число, выиграй ×2
🎲 <b>Dice</b> — больше или меньше
🃏 <b>Blackjack</b> — набери 21
🎡 <b>Roulette</b> — красное или чёрное
🎰 <b>Slots</b> — лови три в ряд
🪙 <b>Coin Flip</b> — орёл или решка
🐎 <b>Horse Race</b> — почувствуй азарт
💎 <b>Lucky 20</b> — найди алмаз

🌐 <b>Онлайн-режим</b> — играй с друзьями!

💰 Начинаешь с <b>5000 монет</b>
🎁 Каждый час +0.2 монеты бонусом

Жми кнопку и вперёд за удачей! 👇"""


REMINDERS = [
    """👋 <b>Скучаешь?</b>

В Golden Palace ждут тебя:
🎯 Plinko с множителем до ×5
🎱 Keno — угадай число
🃏 Blackjack — набери 21

Заходи, забери свой куш! 💰""",

    """🔥 <b>Заходи, мы скучали!</b>

Твои монеты застоялись — пора их приумножить:
🎰 Slots крутится, ждёт тебя
🎡 Roulette готова к обороту
🎲 Dice катится к победе

Всего 1 клик до азарта! 👇""",

    """💎 <b>Тебя ждут 5000+ монет!</b>

В твоём распоряжении:
🎯 Plinko — падающий шарик
💎 Lucky 20 — найди алмаз
🐎 Horse Race — выбери коня
🎡 Roulette — угадай цвет

Не заставляй удачу ждать! 💰""",

    """⏰ <b>Напоминание от Golden Palace</b>

Твой ежечасный бонус капает!
Загляни — вдруг уже накопилось на хорошую ставку?

🎰 Играй, выигрывай, наслаждайся!""",

    """🎰 <b>Golden Palace заждалось!</b>

Попробуй свои силы:
🔥 Plinko — ×5 в центре
🎱 Keno — угадай число
🃏 Blackjack — 21 и победа
🎲 Dice — больше или меньше

Играй прямо сейчас! 👇""",

    """🎯 <b>Пора играть!</b>

Одна ставка — и ты можешь стать легендой!
🎱 Keno ×2 · 🃏 BJ ×2.5 · 🎰 Slots ×15

Попробуй удачу! 👇""",
]


FACTS = [
    """🎲 <b>Интересный факт</b>

Самое старое казино в мире — <b>Casino di Venezia</b> (Венеция, 1638 год). Ему уже почти 400 лет! 🏛️

Хочешь почувствовать себя частью истории? Сыграй в Golden Palace! 👇""",

    """🎰 <b>Знаешь ли ты?</b>

Игровой автомат <b>«Liberty Bell»</b> (1895) стал первым в мире слотом с 3 барабанами. Именно он подарил нам символы 🍒🍋🍇!

Испытай удачу в Slots! 👇""",

    """💎 <b>Интересный факт</b>

Слово «казино» с итальянского означает <b>«маленький дом»</b>. Изначально так называли загородные виллы знати, где устраивали игры.

В Golden Palace мы тоже дома 🏠 Играй!""",

    """🎡 <b>Про рулетку</b>

В европейской рулетке <b>37 чисел</b> (0-36), а в американской — <b>38</b> (ещё 00). Из-за этого шансы игрока чуть ниже!

У нас классическая европейская 🎯""",

    """🃏 <b>Знаешь ли ты?</b>

В Blackjack комбинация <b>«Ace + 10»</b> = 21 называется «блэкджек» и платит <b>×2.5</b> вместо обычных ×2!

Испытай свою удачу в картах! 👇""",

    """🎱 <b>Про Keno</b>

Keno появилось в Древнем Китае более <b>2000 лет назад</b>. Тогда вместо шариков использовали деревянные дощечки!

Попробуй современную версию! 👇""",

    """🐎 <b>Интересный факт</b>

Скачки — один из старейших видов азартных игр. Первые записи о ставках на лошадей датируются <b>VI веком н.э.</b> в Греции.

Выбери своего фаворита! 🏁""",

    """🎯 <b>Про Plinko</b>

Название «Plinko» происходит от звука, который издаёт шарик — <b>«plink»</b> — когда ударяется о пеги!

Запусти шарик и услышь это сам! 👇""",

    """💰 <b>Интересный факт</b>

В Монте-Карло казино запрещено местным жителям — только туристам. Своим вход туда закрыт с 1911 года!

А в Golden Palace вход открыт всем 🎰""",

    """🎲 <b>Про кубики</b>

Игра в кости — <b>древнейшая</b> азартная игра. Ей больше 5000 лет, играли ещё в Древнем Египте и Месопотамии!

Кинь кубики в Dice! 👇""",
]


NEWS = [
    """📢 <b>Новости Golden Palace</b>

🎱 <b>Новая игра — Keno!</b>
Угадай число от 1 до 10 и выиграй ×2 от ставки!

Попробуй прямо сейчас 👇""",

    """📢 <b>Обновление!</b>

🌐 Теперь доступен <b>онлайн-режим</b> — играй с друзьями в Lucky 20 и Dice!

Создавай лобби, зови друзей по ID!

🎰 Заходи играть 👇""",

    """📢 <b>Что нового в Golden Palace</b>

✨ Обновили дизайн — стало ещё красивее!
🎵 Добавили фоновую музыку
👑 Премиум-стиль во всём

Загляни посмотреть! 👇""",

    """📢 <b>Golden Palace растёт!</b>

👥 Уже сотни игроков заходят каждый день
💰 Разыгрываются миллионы монет
🎁 Почасовой бонус для всех

Присоединяйся! 👇""",
]


GROUP_MESSAGES = [
    """👑 <b>Golden Palace — премиум казино!</b>

🎰 Здесь ты найдёшь:
🎯 Plinko, 🎱 Keno, 🎲 Dice, 🃏 Blackjack
🎡 Roulette, 🎰 Slots, 🪙 Coin Flip
🐎 Horse Race, 💎 Lucky 20

💰 Начинаешь с 5000 монет бесплатно!
🎁 +0.2 монеты каждый час бонусом

Жми кнопку и играй! 👇""",

    """🎰 <b>Пора играть!</b>

Попробуй свои силы в <b>Golden Palace</b>:
🎯 Plinko — множитель до ×5
🎱 Keno — угадай число
🃏 Blackjack — набери 21

Всего 1 клик до азарта! 👇""",

    """💎 <b>Golden Palace ждёт!</b>

Сыграй в лучшие мини-игры прямо в Telegram:
🎲 Dice · 🎡 Roulette · 🎰 Slots
🐎 Horse Race · 💎 Lucky 20

Играй с друзьями онлайн! 👇""",

    """🔥 <b>Не пропусти!</b>

В <b>Golden Palace</b> можно играть бесплатно:
💰 5000 монет при первом входе
🎁 Почасовой бонус
🌐 Онлайн-режим с друзьями

Заходи, попробуй! 👇""",

    """🎯 <b>Испытай удачу!</b>

В <b>Golden Palace</b> каждый может стать миллионером:
🎰 Slots ×15 · 🃏 BJ ×2.5
🎱 Keno ×2 · 🎯 Plinko ×5

Попробуй прямо сейчас! 👇""",

    """🎁 <b>Хочешь лёгких денег?</b>

<b>Golden Palace</b> выдаёт:
💰 5000 монет новым игрокам
🎁 0.2 монеты каждый час
🏆 Множители до ×15

Жми и забирай! 👇""",
]


# ═══════════════════════════════════════════════════════════
#  РАССЫЛКА — ВСЕМ СРАЗУ, НО РАЗНЫЕ СООБЩЕНИЯ
# ═══════════════════════════════════════════════════════════
def hourly_broadcast_loop():
    """
    Каждый час:
    1. Собираем всех подписчиков (юзеры + группы)
    2. Перемешиваем
    3. Каждому отправляем СЛУЧАЙНОЕ сообщение
    4. Задержка 3 секунды между отправками
    """
    time.sleep(120)  # ждём 2 минуты после запуска
    print('📢 Рассылка запущена (каждый час, задержка 3 сек)')

    while True:
        try:
            all_recipients = []
            for chat_id, info in subscribers['users'].items():
                all_recipients.append(('user', chat_id, info))
            for chat_id, info in subscribers['groups'].items():
                all_recipients.append(('group', chat_id, info))

            if not all_recipients:
                print('📢 Нет подписчиков — спим час')
                time.sleep(BROADCAST_INTERVAL)
                continue

            random.shuffle(all_recipients)
            total = len(all_recipients)
            print(f'📢 Рассылка для {total} получателей')
            print(f'⏱ Займёт примерно {total * SEND_DELAY} секунд ({(total * SEND_DELAY) // 60} мин)')

            sent_count = 0
            failed_count = 0

            for idx, (rec_type, chat_id, info) in enumerate(all_recipients, 1):
                try:
                    if rec_type == 'user':
                        # Для юзера — случайное из пула
                        pool = random.choice([REMINDERS, FACTS, NEWS, REMINDERS])
                        text = random.choice(pool)
                        send_message(chat_id, text, play_button())
                    else:
                        # Для группы — отдельный пул
                        text = random.choice(GROUP_MESSAGES)
                        send_message(chat_id, text, play_button_group())

                    sent_count += 1
                    if idx % 10 == 0:
                        print(f'  📤 {idx}/{total} отправлено')

                    # Задержка между отправками
                    time.sleep(SEND_DELAY)

                except Exception as e:
                    failed_count += 1
                    print(f'  ❌ Ошибка {chat_id}:', e)

            print(f'✅ Рассылка завершена: {sent_count} успешно, {failed_count} ошибок')

            # Спим час до следующей рассылки
            time.sleep(BROADCAST_INTERVAL)

        except Exception as e:
            print('❌ Ошибка рассылки:', e)
            time.sleep(300)


# ═══════════════════════════════════════════════════════════
#  ОБРАБОТКА СООБЩЕНИЙ
# ═══════════════════════════════════════════════════════════
def handle_update(update):
    msg = update.get('message') or update.get('edited_message')
    if not msg:
        my_chat = update.get('my_chat_member')
        if my_chat:
            handle_my_chat_member(my_chat)
        return

    chat = msg.get('chat', {})
    chat_id = chat.get('id')
    chat_type = chat.get('type')
    text = (msg.get('text') or '').strip()
    from_user = msg.get('from', {})

    # Группа
    if chat_type in ('group', 'supergroup'):
        if str(chat_id) not in subscribers['groups']:
            subscribers['groups'][str(chat_id)] = {
                'title': chat.get('title', 'Группа'),
                'added_at': int(time.time())
            }
            save_data()
            print(f'➕ Новая группа: {chat.get("title")} ({chat_id})')

        if text == '/start':
            send_message(chat_id, GROUP_MESSAGES[0], play_button_group())
        elif text == '/play':
            send_message(chat_id, '🎰 <b>Играть</b> 👇', play_button_group())
        return

    # Личка
    if chat_type == 'private':
        if str(chat_id) not in subscribers['users']:
            subscribers['users'][str(chat_id)] = {
                'first_name': from_user.get('first_name', ''),
                'username': from_user.get('username', ''),
                'added_at': int(time.time())
            }
            save_data()
            print(f'➕ Новый юзер: {from_user.get("first_name")} ({chat_id})')

        if text == '/start':
            send_message(chat_id, WELCOME_TEXT, play_button())
        elif text == '/play':
            send_message(chat_id, '🎰 <b>Погнали!</b> 👇', play_button())
        elif text == '/help':
            send_message(chat_id,
                '👑 <b>Golden Palace</b>\n\n'
                '📋 Доступные команды:\n'
                '/start — приветствие\n'
                '/play — начать игру\n'
                '/help — эта справка\n\n'
                '🎰 Играй прямо в Telegram!',
                play_button())


def handle_my_chat_member(update):
    chat = update.get('chat', {})
    chat_id = chat.get('id')
    new_status = update.get('new_chat_member', {}).get('status')
    old_status = update.get('old_chat_member', {}).get('status')

    if old_status in ('left', 'kicked') and new_status in ('member', 'administrator'):
        subscribers['groups'][str(chat_id)] = {
            'title': chat.get('title', 'Группа'),
            'added_at': int(time.time())
        }
        save_data()
        print(f'➕ Бот добавлен в группу: {chat.get("title")}')
        send_message(chat_id, GROUP_MESSAGES[0], play_button_group())

    elif new_status in ('left', 'kicked'):
        if str(chat_id) in subscribers['groups']:
            del subscribers['groups'][str(chat_id)]
            save_data()
            print(f'➖ Бот удалён из группы: {chat.get("title")}')


def polling_loop():
    print('🤖 Бот запущен (polling)')
    offset = 0

    while True:
        try:
            url = f'https://api.telegram.org/bot{BOT_TOKEN}/getUpdates'
            payload = {
                'offset': offset,
                'timeout': 30,
                'allowed_updates': ['message', 'edited_message', 'my_chat_member']
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

            with urllib.request.urlopen(req, timeout=35) as resp:
                result = json.loads(resp.read().decode())

            if result.get('ok'):
                for update in result.get('result', []):
                    try:
                        handle_update(update)
                    except Exception as e:
                        print('❌ Ошибка обработки:', e)
                    offset = update['update_id'] + 1

        except Exception as e:
            print('❌ Polling error:', e)
            time.sleep(5)


# ═══════════════════════════════════════════════════════════
#  ЗАПУСК
# ═══════════════════════════════════════════════════════════
def start_bot():
    if not BOT_TOKEN:
        print('⚠️ BOT_TOKEN не задан — бот не запущен')
        return

    load_data()
    threading.Thread(target=polling_loop, daemon=True).start()
    threading.Thread(target=hourly_broadcast_loop, daemon=True).start()
    print('✅ Бот инициализирован')


if __name__ == '__main__':
    start_bot()
    while True:
        time.sleep(60)
