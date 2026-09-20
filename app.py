import os
import json
import time
import random
import string
import threading
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify, send_from_directory
from flask_sock import Sock

app = Flask(__name__, static_folder='.')
sock = Sock(app)


@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp


# ============================================================
#  КОНСТАНТЫ
# ============================================================
ADMIN_LOGIN = '2'
ADMIN_PASSWORD = 'диана'
HOUR_BONUS = 0.2
HOUR_SECONDS = 3600
MIN_WITHDRAW = 50
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8665249676:AAGF5cu1i29JHgCUqYJ6iRfBYqSILA44Jag')
GAME_URL = os.environ.get('GAME_URL', 'https://game-kazik-by-zyza.onrender.com')
BOT_DATA_FILE = 'bot_subscribers.json'
DATA_FILE = 'data.json'
SAVE_INTERVAL = 60
MINI_APP_SHORT_NAME = os.environ.get('MINI_APP_SHORT_NAME', '')
MAX_PLAYERS = 2000
PLAYER_TTL_DAYS = 30

# ============================================================
#  ХРАНИЛИЩА
# ============================================================
players = {}
guests = {}
tg_users = {}
lobbies = {}
lobby_sockets = {}
player_sockets = {}
lock = threading.Lock()

VIRTUAL_PLAYER_ID = '999999'
VIRTUAL_PLAYER_GUEST = 'virtual_keepalive_bot'
ADMIN_TOKENS_FILE = 'admin_tokens.json'

# Кэш админки
_admin_cache = {'players': None, 'ts': 0}
ADMIN_CACHE_TTL = 2

global_settings = {
    'tech_break': False,
    'tech_break_message': '🔧 Технический перерыв\n\nСкоро вернёмся!',
    'keepalive': False,
    'autorequest': False,
    'autorequest_log': []
}

# ============================================================
#  МАГАЗИН ОФОРМЛЕНИЙ
# ============================================================
SHOP_ITEMS = {
    # ФОНЫ
    'bg_dark':     {'name': '🌑 Тёмный фон',     'desc': 'Минимализм и элегантность',    'price': 0,     'type': 'bg',  'value': 'linear-gradient(180deg,#0a0a0a 0%,#1a1a1a 50%,#0a0a0a 100%)'},
    'bg_gold':     {'name': '👑 Золотой фон',    'desc': 'Классическое золото казино',    'price': 15000, 'type': 'bg',  'value': 'linear-gradient(180deg,#1a1408 0%,#3d2f08 50%,#1a1408 100%)'},
    'bg_emerald':  {'name': '💎 Изумрудный фон', 'desc': 'Роскошь и стабильность',      'price': 15000, 'type': 'bg',  'value': 'linear-gradient(180deg,#051a14 0%,#0d3d2f 50%,#051a14 100%)'},
    'bg_purple':   {'name': '🔮 Фиолетовый фон', 'desc': 'Мистика и загадка',           'price': 18000, 'type': 'bg',  'value': 'linear-gradient(180deg,#14082a 0%,#3a1d6b 50%,#14082a 100%)'},
    'bg_blood':    {'name': '🩸 Кровавый фон',   'desc': 'Для настоящих азартных',        'price': 25000, 'type': 'bg',  'value': 'linear-gradient(180deg,#1a0505 0%,#4a0d0d 50%,#1a0505 100%)'},
    'bg_ocean':    {'name': '🌊 Океанский фон',  'desc': 'Спокойствие и глубина',          'price': 22000, 'type': 'bg',  'value': 'linear-gradient(180deg,#041425 0%,#0c3d5e 50%,#041425 100%)'},
    'bg_rainbow':  {'name': '🌈 Радужный фон',   'desc': 'Для ярких личностей',           'price': 50000, 'type': 'bg',  'value': 'linear-gradient(180deg,#2a0a3d 0%,#0a3d3d 25%,#3d2a0a 50%,#3d0a2a 75%,#2a0a3d 100%)'},

    # ЦВЕТА
    'accent_gold':    {'name': '👑 Золотой акцент',    'desc': 'По умолчанию',   'price': 0,     'type': 'accent', 'value': '#d4af37'},
    'accent_emerald': {'name': '💚 Изумрудный акцент', 'desc': 'Зелёный стиль',  'price': 10000, 'type': 'accent', 'value': '#10b981'},
    'accent_purple':  {'name': '💜 Фиолетовый акцент', 'desc': 'Мистический',    'price': 10000, 'type': 'accent', 'value': '#a855f7'},
    'accent_red':     {'name': '❤️ Красный акцент',    'desc': 'Для азартных',   'price': 12000, 'type': 'accent', 'value': '#ff5252'},
    'accent_cyan':    {'name': '💠 Голубой акцент',    'desc': 'Технологичный',  'price': 12000, 'type': 'accent', 'value': '#22d3ee'},
    'accent_pink':    {'name': '💗 Розовый акцент',    'desc': 'Нежный стиль',   'price': 15000, 'type': 'accent', 'value': '#ff2d95'},
    'accent_rainbow': {'name': '🌈 Радужный акцент',   'desc': 'Анимированный',  'price': 75000, 'type': 'accent', 'value': 'rainbow'},

    # ФОРМЫ
    'shape_default': {'name': '⬛ Классика',   'desc': 'Скруглённые углы',   'price': 0,     'type': 'shape',  'value': '22px 10px 22px 10px'},
    'shape_round':   {'name': '⚪ Круглые',    'desc': 'Полностью круглые',  'price': 8000,  'type': 'shape',  'value': '24px'},
    'shape_sharp':   {'name': '🔲 Острые',     'desc': 'Строгие прямые',     'price': 8000,  'type': 'shape',  'value': '4px'},
    'shape_diamond': {'name': '💎 Ромбы',      'desc': 'Алмазная форма',     'price': 20000, 'type': 'shape',  'value': '30px 4px 30px 4px'},
    'shape_soft':    {'name': '🌊 Мягкие',     'desc': 'Очень плавные',      'price': 12000, 'type': 'shape',  'value': '30px'},

    # ЛОГО
    'logo_crown':    {'name': '👑 Золотая корона', 'desc': 'Классика',     'price': 0,     'type': 'logo', 'value': '👑'},
    'logo_diamond':  {'name': '💎 Алмаз',          'desc': 'Драгоценный',   'price': 25000, 'type': 'logo', 'value': '💎'},
    'logo_lion':     {'name': '🦁 Лев',            'desc': 'Царь зверей',   'price': 30000, 'type': 'logo', 'value': '🦁'},
    'logo_skull':    {'name': '💀 Череп',          'desc': 'Для азартных',  'price': 35000, 'type': 'logo', 'value': '💀'},
    'logo_dragon':   {'name': '🐉 Дракон',         'desc': 'Мифический',    'price': 50000, 'type': 'logo', 'value': '🐉'},
    'logo_phoenix':  {'name': '🔥 Феникс',         'desc': 'Возрождение',   'price': 60000, 'type': 'logo', 'value': '🔥'},
}

DEFAULT_SHOP = {
    'owned': ['accent_gold', 'shape_default', 'logo_crown', 'bg_dark'],
    'equipped': {
        'bg': 'bg_dark',
        'accent': 'accent_gold',
        'shape': 'shape_default',
        'logo': 'logo_crown'
    }
}


def ensure_player_shop(player):
    """Гарантирует наличие полей магазина у игрока."""
    if 'shop' not in player or not isinstance(player['shop'], dict):
        player['shop'] = {
            'owned': list(DEFAULT_SHOP['owned']),
            'equipped': dict(DEFAULT_SHOP['equipped'])
        }
    else:
        if 'owned' not in player['shop'] or not isinstance(player['shop']['owned'], list):
            player['shop']['owned'] = list(DEFAULT_SHOP['owned'])
        if 'equipped' not in player['shop'] or not isinstance(player['shop']['equipped'], dict):
            player['shop']['equipped'] = dict(DEFAULT_SHOP['equipped'])
        for k in DEFAULT_SHOP['owned']:
            if k not in player['shop']['owned']:
                player['shop']['owned'].append(k)
        for k, v in DEFAULT_SHOP['equipped'].items():
            if k not in player['shop']['equipped']:
                player['shop']['equipped'][k] = v
    return player['shop']


def _add_log(msg):
    with lock:
        global_settings['autorequest_log'].append({'time': now(), 'text': msg})
        if len(global_settings['autorequest_log']) > 50:
            global_settings['autorequest_log'] = global_settings['autorequest_log'][-50:]


# ============================================================
#  УТИЛИТЫ
# ============================================================
def gen_id(n=6, digits_only=True):
    chars = string.digits if digits_only else string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=n))


def now():
    return int(time.time())


def find_player(guest_id=None, telegram_id=None):
    if telegram_id and str(telegram_id) in tg_users:
        pid = tg_users[str(telegram_id)]
        if pid in players:
            return players[pid]
    if guest_id and guest_id in guests:
        pid = guests[guest_id]
        if pid in players:
            return players[pid]
    return None


def _accrue_bonus(player):
    t = now()
    elapsed = t - player.get('last_bonus_ts', t)
    hours = int(elapsed // HOUR_SECONDS)
    if hours > 0:
        player['pending_bonus'] = round(player.get('pending_bonus', 0) + hours * HOUR_BONUS, 2)
        player['last_bonus_ts'] = t


def _pub(player):
    if not player:
        return None
    shop = ensure_player_shop(player)
    return {
        'game_id': player['game_id'],
        'name': player['name'],
        'balance': player.get('balance', 0),
        'pending_bonus': round(player.get('pending_bonus', 0), 2),
        'region': player.get('region', 'Не указан'),
        'friends': player.get('friends', []),
        'friend_requests': player.get('friend_requests', []),
        'shop': shop
    }


# ============================================================
#  СОХРАНЕНИЕ
# ============================================================
def save_all_data():
    try:
        with lock:
            data = {
                'players': players,
                'guests': guests,
                'tg_users': tg_users,
                'lobbies': lobbies,
                'global_settings': {
                    'tech_break': global_settings['tech_break'],
                    'tech_break_message': global_settings['tech_break_message'],
                    'keepalive': global_settings['keepalive'],
                    'autorequest': global_settings['autorequest']
                },
                'saved_at': now()
            }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print('❌ Ошибка сохранения:', e)


def load_all_data():
    global players, guests, tg_users, lobbies
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            players = data.get('players', {})
            guests = data.get('guests', {})
            tg_users = data.get('tg_users', {})
            lobbies = data.get('lobbies', {})
            saved = data.get('global_settings', {})
            if saved:
                global_settings['tech_break'] = saved.get('tech_break', False)
                global_settings['tech_break_message'] = saved.get('tech_break_message', global_settings['tech_break_message'])
                global_settings['keepalive'] = saved.get('keepalive', False)
                global_settings['autorequest'] = saved.get('autorequest', False)
            for pid, p in players.items():
                if not p.get('is_virtual'):
                    ensure_player_shop(p)
            print(f'📂 Загружено: {len(players)} игроков')
    except Exception:
        print('📂 Файл данных пуст')


def _cleanup_old_players():
    """Удаляет неактивных игроков старше PLAYER_TTL_DAYS дней."""
    with lock:
        t = now()
        ttl = PLAYER_TTL_DAYS * 24 * 3600
        to_delete = []
        for pid, p in players.items():
            if p.get('is_virtual'):
                continue
            if t - p.get('last_seen', 0) > ttl:
                to_delete.append(pid)
        for pid in to_delete:
            players.pop(pid, None)
        for gid, gpid in list(guests.items()):
            if gpid not in players:
                guests.pop(gid, None)
        for tid, tpid in list(tg_users.items()):
            if tpid not in players:
                tg_users.pop(tid, None)
        if to_delete:
            print(f'🧹 Удалено {len(to_delete)} неактивных игроков')


# ============================================================
#  ФОНОВЫЕ ЗАДАЧИ
# ============================================================
def autosave_loop():
    last_cleanup = now()
    while True:
        time.sleep(SAVE_INTERVAL)
        try:
            save_all_data()
            if now() - last_cleanup > 24 * 3600:
                _cleanup_old_players()
                last_cleanup = now()
        except Exception as e:
            print('autosave error:', e)


def hourly_bonus_loop():
    while True:
        time.sleep(HOUR_SECONDS)
        try:
            with lock:
                t = now()
                for pid, p in players.items():
                    if p.get('is_virtual'):
                        continue
                    if t - p.get('last_bonus_ts', 0) >= HOUR_SECONDS - 5:
                        p['pending_bonus'] = round(p.get('pending_bonus', 0) + HOUR_BONUS, 2)
                        p['last_bonus_ts'] = t
                        notify_player(pid, {'type': 'bonus_update', 'pending_bonus': p['pending_bonus']})
        except Exception as e:
            print('bonus loop error:', e)


_autorequest_stop = threading.Event()


def autorequest_loop():
    time.sleep(60)
    base = os.environ.get('RENDER_EXTERNAL_URL', '') or f'http://127.0.0.1:{os.environ.get("PORT", "5000")}'
    base = base.rstrip('/')
    while True:
        try:
            if global_settings.get('autorequest'):
                _add_log('🚀 Начало цикла')
                try:
                    _add_log('📡 Пинг /health...')
                    req = urllib.request.Request(base + '/health', headers={'User-Agent': 'GP-AutoReq/1.0'})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        _add_log(f'✅ /health → {resp.status}')
                except Exception as e:
                    _add_log(f'❌ /health: {str(e)[:40]}')
                time.sleep(2)

                try:
                    _add_log('🎮 Создание лобби...')
                    fake_guest = 'auto_' + str(random.randint(1000, 9999))
                    payload = json.dumps({'guest_id': fake_guest}).encode()
                    req = urllib.request.Request(base + '/api/lobby/create', data=payload,
                        headers={'Content-Type': 'application/json'}, method='POST')
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        result = json.loads(resp.read().decode())
                        lobby_id = result.get('lobby_id')
                        if lobby_id:
                            _add_log(f'✅ Лобби #{lobby_id}')
                            time.sleep(2)
                            _add_log('🚪 Выход...')
                            leave_url = base + f'/api/lobby/leave?lobby_id={lobby_id}'
                            payload2 = json.dumps({'guest_id': fake_guest}).encode()
                            req2 = urllib.request.Request(leave_url, data=payload2,
                                headers={'Content-Type': 'application/json'}, method='POST')
                            with urllib.request.urlopen(req2, timeout=10) as resp2:
                                _add_log(f'✅ Выход OK')
                except Exception as e:
                    _add_log(f'❌ Лобби: {str(e)[:40]}')
                time.sleep(2)

                try:
                    _add_log('🔐 Проверка admin...')
                    payload = json.dumps({'login': ADMIN_LOGIN, 'password': ADMIN_PASSWORD}).encode()
                    req = urllib.request.Request(base + '/api/admin/login', data=payload,
                        headers={'Content-Type': 'application/json'}, method='POST')
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        result = json.loads(resp.read().decode())
                        if result.get('token'):
                            _add_log('✅ Admin login OK')
                except Exception as e:
                    _add_log(f'❌ Admin: {str(e)[:40]}')
                time.sleep(2)

                try:
                    _add_log('📊 Проверка статуса...')
                    req = urllib.request.Request(base + '/api/global/status', headers={'User-Agent': 'GP-AutoReq/1.0'})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        _add_log(f'✅ Статус {resp.status}')
                except Exception as e:
                    _add_log(f'❌ Статус: {str(e)[:40]}')

                _add_log('🏁 Цикл завершён')
        except Exception as e:
            _add_log(f'❌ Ошибка: {str(e)[:60]}')

        for _ in range(48):
            if _autorequest_stop.is_set():
                _autorequest_stop.clear()
                break
            time.sleep(5)


load_all_data()

# Создаём виртуального игрока
with lock:
    if VIRTUAL_PLAYER_ID not in players:
        players[VIRTUAL_PLAYER_ID] = {
            'game_id': VIRTUAL_PLAYER_ID,
            'name': '🤖 Хранитель',
            'telegram_id': None,
            'last_seen': now(),
            'balance': 0.0,
            'pending_bonus': 0.0,
            'last_bonus_ts': now(),
            'region': 'Система',
            'friends': [],
            'friend_requests': [],
            'is_virtual': True,
            'shop': {'owned': [], 'equipped': {}}
        }
        guests[VIRTUAL_PLAYER_GUEST] = VIRTUAL_PLAYER_ID


# ============================================================
#  ПУШИ
# ============================================================
def notify_player(player_id, message):
    conns = player_sockets.get(player_id, [])
    dead = []
    for ws in conns:
        try:
            ws.send(json.dumps(message))
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            conns.remove(ws)
        except Exception:
            pass


def notify_all_players(message):
    for pid in list(player_sockets.keys()):
        notify_player(pid, message)


def notify_lobby(lobby_id, message):
    conns = lobby_sockets.get(lobby_id, [])
    dead = []
    for ws in conns:
        try:
            ws.send(json.dumps(message))
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            conns.remove(ws)
        except Exception:
            pass
    lobby = lobbies.get(lobby_id)
    if lobby:
        members = [lobby['host']] + (lobby.get('guests') or [])
        for m in members:
            pid = m.get('game_id')
            if pid:
                notify_player(pid, message)


# ============================================================
#  СТАТИКА (главная — city.html, потом index.html)
# ============================================================
@app.route('/')
def index():
    # Главная — город
    if os.path.exists('city.html'):
        return send_from_directory('.', 'city.html')
    if os.path.exists('index.html'):
        return send_from_directory('.', 'index.html')
    return 'Golden Palace server is running'


@app.route('/<path:path>')
def static_files(path):
    if os.path.exists(path):
        return send_from_directory('.', path)
    return 'Not found', 404


@app.route('/health')
def health():
    return jsonify({
        'ok': True,
        'players': max(0, len(players) - 1),
        'tg_users': len(tg_users),
        'sockets': len(player_sockets),
        'lobbies': len(lobbies),
        'keepalive': global_settings.get('keepalive', False),
        'autorequest': global_settings.get('autorequest', False),
        'tech_break': global_settings.get('tech_break', False),
        'bot_subscribers': _bot_count()
    })


def _bot_count():
    try:
        with open(BOT_DATA_FILE, 'r') as f:
            data = json.load(f)
            return len(data.get('users', {})) + len(data.get('groups', {}))
    except Exception:
        return 0


@app.route('/api/global/status')
def global_status():
    return jsonify({
        'tech_break': global_settings['tech_break'],
        'message': global_settings['tech_break_message'],
        'keepalive': global_settings.get('keepalive', False),
        'autorequest': global_settings.get('autorequest', False)
    })


# ============================================================
#  РЕГИСТРАЦИЯ
# ============================================================
def parse_init_data(init_data):
    if not init_data:
        return None
    try:
        parsed = urllib.parse.parse_qs(init_data)
        user_json = parsed.get('user', [None])[0]
        if not user_json:
            return None
        user = json.loads(user_json)
        return {
            'telegram_id': str(user.get('id', '')),
            'first_name': user.get('first_name', ''),
            'last_name': user.get('last_name', ''),
            'username': user.get('username', ''),
            'language_code': user.get('language_code', 'ru')
        }
    except Exception as e:
        print('parse_init_data error:', e)
        return None


@app.route('/api/register', methods=['POST', 'OPTIONS'])
def register():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()[:20]
    guest_id = data.get('guest_id')
    region = data.get('region')
    init_data = data.get('initData', '')
    tg_info = parse_init_data(init_data)
    telegram_id = tg_info['telegram_id'] if tg_info else None

    if len(name) < 2 and tg_info:
        tg_name = (tg_info['first_name'] + ' ' + tg_info['last_name']).strip()
        name = tg_name[:20] or 'Игрок'
    if len(name) < 2:
        name = 'Игрок'

    with lock:
        player = find_player(guest_id=guest_id, telegram_id=telegram_id)
        if player:
            player['name'] = name
            player['last_seen'] = now()
            if region:
                player['region'] = region
            if telegram_id:
                player['telegram_id'] = telegram_id
                tg_users[telegram_id] = player['game_id']
            if guest_id and guest_id not in guests:
                guests[guest_id] = player['game_id']
            _accrue_bonus(player)
            ensure_player_shop(player)
            return jsonify({'player': _pub(player), 'guest_id': guest_id or player['game_id']})

        if len(players) >= MAX_PLAYERS + 1:
            return jsonify({'error': 'server_full'})

        pid = gen_id(6)
        while pid in players:
            pid = gen_id(6)
        player = {
            'game_id': pid,
            'name': name,
            'telegram_id': telegram_id,
            'last_seen': now(),
            'balance': 5000.0,
            'pending_bonus': 0.0,
            'last_bonus_ts': now(),
            'region': region or 'Не указан',
            'friends': [],
            'friend_requests': [],
            'shop': {
                'owned': list(DEFAULT_SHOP['owned']),
                'equipped': dict(DEFAULT_SHOP['equipped'])
            }
        }
        players[pid] = player
        if guest_id:
            guests[guest_id] = pid
        if telegram_id:
            tg_users[telegram_id] = pid

    return jsonify({'player': _pub(player), 'guest_id': guest_id or pid})


# ============================================================
#  МАГАЗИН
# ============================================================
@app.route('/api/shop/items', methods=['GET', 'POST', 'OPTIONS'])
def shop_items():
    if request.method == 'OPTIONS':
        return '', 204
    return jsonify({
        'items': SHOP_ITEMS,
        'categories': ['bg', 'accent', 'shape', 'logo']
    })


@app.route('/api/shop/buy', methods=['POST', 'OPTIONS'])
def shop_buy():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    guest_id = data.get('guest_id')
    item_key = data.get('item_key')

    if item_key not in SHOP_ITEMS:
        return jsonify({'error': 'item_not_found'})

    item = SHOP_ITEMS[item_key]

    with lock:
        player = find_player(guest_id=guest_id)
        if not player:
            return jsonify({'error': 'not_registered'})

        shop = ensure_player_shop(player)

        if item_key in shop['owned']:
            return jsonify({'error': 'already_owned'})

        price = item['price']
        if player['balance'] < price:
            return jsonify({'error': 'not_enough', 'need': price, 'have': player['balance']})

        player['balance'] = round(player['balance'] - price, 2)
        shop['owned'].append(item_key)

        new_balance = player['balance']
        owned = list(shop['owned'])

    _admin_cache['players'] = None
    save_all_data()
    notify_player(player['game_id'], {'type': 'admin_balance_update', 'balance': new_balance})

    return jsonify({
        'ok': True,
        'balance': new_balance,
        'owned': owned,
        'item': item
    })


@app.route('/api/shop/equip', methods=['POST', 'OPTIONS'])
def shop_equip():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    guest_id = data.get('guest_id')
    item_key = data.get('item_key')

    if item_key not in SHOP_ITEMS:
        return jsonify({'error': 'item_not_found'})

    item = SHOP_ITEMS[item_key]
    item_type = item['type']

    with lock:
        player = find_player(guest_id=guest_id)
        if not player:
            return jsonify({'error': 'not_registered'})

        shop = ensure_player_shop(player)

        if item_key not in shop['owned']:
            return jsonify({'error': 'not_owned'})

        shop['equipped'][item_type] = item_key
        equipped = dict(shop['equipped'])
        owned = list(shop['owned'])

    save_all_data()
    return jsonify({
        'ok': True,
        'equipped': equipped,
        'owned': owned
    })


@app.route('/api/shop/me', methods=['POST', 'OPTIONS'])
def shop_me():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        shop = ensure_player_shop(player)
        return jsonify({
            'owned': list(shop['owned']),
            'equipped': dict(shop['equipped']),
            'balance': player.get('balance', 0)
        })


# ============================================================
#  АДМИН
# ============================================================
def _save_admin_sessions(sessions):
    try:
        with open(ADMIN_TOKENS_FILE, 'w') as f:
            json.dump(sessions, f)
    except Exception as e:
        print('save admin tokens error:', e)


def _load_admin_sessions():
    try:
        with open(ADMIN_TOKENS_FILE, 'r') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


admin_sessions = _load_admin_sessions()
ADMIN_TOKEN_TTL = 30 * 24 * 3600


@app.route('/api/admin/login', methods=['POST', 'OPTIONS'])
def admin_login():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    login = (data.get('login') or '').strip()
    password = (data.get('password') or '').strip()
    if login != ADMIN_LOGIN or password != ADMIN_PASSWORD:
        return jsonify({'error': 'wrong_credentials'})
    token = gen_id(24, digits_only=False)
    with lock:
        admin_sessions[token] = now()
    _save_admin_sessions(admin_sessions)
    return jsonify({'token': token})


def _check_admin(data):
    token = data.get('admin_token')
    if not token or token not in admin_sessions:
        return False
    created = admin_sessions.get(token, 0)
    if now() - created > ADMIN_TOKEN_TTL:
        admin_sessions.pop(token, None)
        _save_admin_sessions(admin_sessions)
        return False
    return True


@app.route('/api/admin/players', methods=['POST', 'OPTIONS'])
def admin_players():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    if not _check_admin(data):
        return jsonify({'error': 'unauthorized'})

    global _admin_cache
    now_ts = now()
    cached = _admin_cache['players']
    if cached and (now_ts - _admin_cache['ts']) < ADMIN_CACHE_TTL:
        result = []
        for p in cached:
            pid = p['game_id']
            result.append({
                **p,
                'online': pid in player_sockets and len(player_sockets.get(pid, [])) > 0
            })
        return jsonify({
            'players': result,
            'tech_break': global_settings['tech_break'],
            'tech_break_message': global_settings['tech_break_message'],
            'autorequest': global_settings.get('autorequest', False),
            'autorequest_log': global_settings.get('autorequest_log', [])
        })

    with lock:
        result = []
        for pid, p in players.items():
            if p.get('is_virtual'):
                continue
            result.append({
                'game_id': p['game_id'],
                'name': p['name'],
                'telegram_id': p.get('telegram_id', ''),
                'balance': p.get('balance', 0),
                'pending_bonus': round(p.get('pending_bonus', 0), 2),
                'region': p.get('region', 'Не указан'),
                'last_seen': p.get('last_seen', 0),
                'online': pid in player_sockets and len(player_sockets.get(pid, [])) > 0
            })
        result.sort(key=lambda x: -x['last_seen'])

    _admin_cache['players'] = result
    _admin_cache['ts'] = now_ts

    return jsonify({
        'players': result,
        'tech_break': global_settings['tech_break'],
        'tech_break_message': global_settings['tech_break_message'],
        'autorequest': global_settings.get('autorequest', False),
        'autorequest_log': global_settings.get('autorequest_log', [])
    })


@app.route('/api/admin/setbalance', methods=['POST', 'OPTIONS'])
def admin_setbalance():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    if not _check_admin(data):
        return jsonify({'error': 'unauthorized'})
    pid = data.get('player_id')
    amount = float(data.get('amount', 0))
    mode = data.get('mode', 'add')
    with lock:
        p = players.get(pid)
        if not p:
            return jsonify({'error': 'player_not_found'})
        if mode == 'set':
            p['balance'] = max(0.0, round(amount, 2))
        else:
            p['balance'] = max(0.0, round(p.get('balance', 0) + amount, 2))
        new_balance = p['balance']
    _admin_cache['players'] = None
    notify_player(pid, {'type': 'admin_balance_update', 'balance': new_balance})
    save_all_data()
    return jsonify({'ok': True, 'balance': new_balance})


@app.route('/api/admin/techbreak', methods=['POST', 'OPTIONS'])
def admin_techbreak():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    if not _check_admin(data):
        return jsonify({'error': 'unauthorized'})
    enabled = bool(data.get('enabled'))
    message = data.get('message')
    global_settings['tech_break'] = enabled
    if message is not None:
        global_settings['tech_break_message'] = message
    notify_all_players({
        'type': 'tech_break_update',
        'tech_break': enabled,
        'message': global_settings['tech_break_message']
    })
    save_all_data()
    return jsonify({'ok': True, 'tech_break': enabled})


@app.route('/api/admin/autorequest', methods=['POST', 'OPTIONS'])
def admin_autorequest():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    if not _check_admin(data):
        return jsonify({'error': 'unauthorized'})
    enabled = bool(data.get('enabled'))
    global_settings['autorequest'] = enabled
    if enabled:
        with lock:
            global_settings['autorequest_log'] = []
        _add_log('▶️ Запрос Авто включён')
        _autorequest_stop.set()
    else:
        _add_log('⏸ Запрос Авто выключен')
    save_all_data()
    return jsonify({'ok': True, 'autorequest': enabled})


@app.route('/api/admin/autorequest/log', methods=['POST', 'OPTIONS'])
def admin_autorequest_log():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    if not _check_admin(data):
        return jsonify({'error': 'unauthorized'})
    with lock:
        log = list(global_settings.get('autorequest_log', []))
    return jsonify({'ok': True, 'log': log})


@app.route('/api/admin/selfbonus', methods=['POST', 'OPTIONS'])
def admin_selfbonus():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    if not _check_admin(data):
        return jsonify({'error': 'unauthorized'})
    guest_id = data.get('guest_id')
    amount = float(data.get('amount', 1000))
    with lock:
        p = find_player(guest_id=guest_id)
        if not p:
            return jsonify({'error': 'player_not_found'})
        p['balance'] = max(0.0, round(p.get('balance', 0) + amount, 2))
        new_balance = p['balance']
    _admin_cache['players'] = None
    notify_player(p['game_id'], {'type': 'admin_balance_update', 'balance': new_balance})
    save_all_data()
    return jsonify({'ok': True, 'balance': new_balance})


# ============================================================
#  ЛОББИ
# ============================================================
@app.route('/api/lobby/create', methods=['POST', 'OPTIONS'])
def create_lobby():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        for lid in list(lobbies.keys()):
            l = lobbies[lid]
            members = [l['host']] + (l.get('guests') or [])
            if any(m['game_id'] == player['game_id'] for m in members):
                del lobbies[lid]
        lobby_id = gen_id(6)
        while lobby_id in lobbies:
            lobby_id = gen_id(6)
        lobby = {
            'lobby_id': lobby_id,
            'host': _pub(player),
            'guests': [],
            'game_state': None,
            'created': now()
        }
        lobbies[lobby_id] = lobby
    return jsonify({'lobby_id': lobby_id, 'host': lobby['host'], 'guests': lobby['guests']})


@app.route('/api/lobby/join', methods=['POST', 'OPTIONS'])
def join_lobby():
    if request.method == 'OPTIONS':
        return '', 204
    lobby_id = (request.args.get('lobby_id') or '').strip()
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        if lobby_id not in lobbies:
            return jsonify({'error': 'not_found'})
        lobby = lobbies[lobby_id]
        if lobby['host']['game_id'] == player['game_id']:
            return jsonify({'error': 'own_lobby'})
        if any(g['game_id'] == player['game_id'] for g in lobby['guests']):
            return jsonify({'error': 'already_in'})
        if len(lobby['guests']) >= 1:
            return jsonify({'error': 'full'})
        lobby['guests'].append(_pub(player))
        msg = {'type': 'players', 'players': [lobby['host']] + lobby['guests']}
        notify_lobby(lobby_id, msg)
        return jsonify({'lobby_id': lobby_id, 'host': lobby['host'], 'guests': lobby['guests']})


@app.route('/api/lobby/leave', methods=['POST', 'OPTIONS'])
def leave_lobby():
    if request.method == 'OPTIONS':
        return '', 204
    lobby_id = (request.args.get('lobby_id') or '').strip()
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player or lobby_id not in lobbies:
            return jsonify({'ok': True})
        lobby = lobbies[lobby_id]
        if lobby['host']['game_id'] == player['game_id']:
            notify_lobby(lobby_id, {'type': 'system', 'text': 'Хост закрыл лобби'})
            del lobbies[lobby_id]
        else:
            lobby['guests'] = [g for g in lobby['guests'] if g['game_id'] != player['game_id']]
            lobby['game_state'] = None
            notify_lobby(lobby_id, {'type': 'system', 'text': f"{player['name']} покинул лобби"})
            notify_lobby(lobby_id, {
                'type': 'players',
                'players': [lobby['host']] + lobby['guests']
            })
    return jsonify({'ok': True})


@app.route('/api/lobby/poll')
def lobby_poll():
    lobby_id = (request.args.get('lobby_id') or '').strip()
    if lobby_id not in lobbies:
        return jsonify({'error': 'not_found'})
    lobby = lobbies[lobby_id]
    return jsonify({
        'lobby_id': lobby_id,
        'players': [lobby['host']] + (lobby.get('guests') or []),
        'game_state': lobby.get('game_state')
    })


# ============================================================
#  ИГРЫ
# ============================================================
def make_deck():
    suits = ['♠', '♥', '♦', '♣']
    ranks = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
    d = [{'s': s, 'r': r} for s in suits for r in ranks]
    random.shuffle(d)
    return d


def hand_score(hand):
    s = 0
    aces = 0
    for c in hand:
        if c['r'] == 'A':
            s += 11
            aces += 1
        elif c['r'] in ('J', 'Q', 'K', '10'):
            s += 10
        else:
            s += int(c['r'])
    while s > 21 and aces > 0:
        s -= 10
        aces -= 1
    return s


def make_initial_state(game_type):
    gs = {'type': game_type, 'phase': 'playing'}
    if game_type == 'lucky20':
        gs['win_idx'] = random.randint(0, 19)
        gs['turn'] = 'host'
        gs['opened'] = []
    elif game_type == 'dice':
        gs['rolls'] = {}
    elif game_type == 'blackjack':
        gs['deck'] = make_deck()
        gs['dealer'] = []
        gs['hands'] = {}
        gs['states'] = {}
        gs['bets'] = {}
        gs['turn_order'] = []
        gs['turn_idx'] = 0
        gs['phase'] = 'betting'
    return gs


@app.route('/api/lobby/game/init', methods=['POST', 'OPTIONS'])
def game_init():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    lobby_id = data.get('lobby_id')
    guest_id = data.get('guest_id')
    game_type = data.get('game_type')
    if lobby_id not in lobbies:
        return jsonify({'error': 'not_found'})
    with lock:
        player = find_player(guest_id=guest_id)
        if not player:
            return jsonify({'error': 'not_registered'})
        lobby = lobbies[lobby_id]
        if lobby['host']['game_id'] != player['game_id']:
            return jsonify({'error': 'not_host'})
        if not lobby['guests']:
            return jsonify({'error': 'no_guest'})
        if game_type not in ('lucky20', 'dice', 'blackjack'):
            return jsonify({'error': 'bad_game'})
        gs = make_initial_state(game_type)
        lobby['game_state'] = gs
        msg = {'type': 'game_init', 'game_state': gs}
        notify_lobby(lobby_id, msg)
    return jsonify({'ok': True})


@app.route('/api/lobby/game/move', methods=['POST', 'OPTIONS'])
def game_move():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    lobby_id = data.get('lobby_id')
    guest_id = data.get('guest_id')
    move = data.get('move', {})
    if lobby_id not in lobbies:
        return jsonify({'error': 'not_found'})
    with lock:
        player = find_player(guest_id=guest_id)
        if not player:
            return jsonify({'error': 'not_registered'})
        lobby = lobbies[lobby_id]
        gs = lobby.get('game_state')
        if not gs:
            return jsonify({'error': 'no_game'})
        pid = player['game_id']
        is_host = lobby['host']['game_id'] == pid

        if gs['type'] == 'lucky20':
            if (is_host and gs['turn'] != 'host') or (not is_host and gs['turn'] != 'guest'):
                return jsonify({'error': 'not_your_turn'})
            idx = int(move.get('idx', -1))
            if idx < 0 or idx > 19 or idx in gs['opened']:
                return jsonify({'error': 'bad_move'})
            gs['opened'].append(idx)
            if idx == gs['win_idx']:
                gs['phase'] = 'done'
                gs['winner'] = pid
            else:
                gs['turn'] = 'guest' if is_host else 'host'

        elif gs['type'] == 'dice':
            dice = move.get('dice', [0, 0])
            if not isinstance(dice, list) or len(dice) != 2:
                return jsonify({'error': 'bad_move'})
            gs['rolls'][pid] = dice
            if len(gs['rolls']) == 2:
                gs['phase'] = 'done'
                items = list(gs['rolls'].items())
                s1 = sum(items[0][1]); s2 = sum(items[1][1])
                if s1 > s2:
                    gs['winner'] = items[0][0]
                elif s2 > s1:
                    gs['winner'] = items[1][0]
                else:
                    gs['winner'] = None

        elif gs['type'] == 'blackjack':
            if gs['phase'] == 'betting':
                bet = int(move.get('bet', 0))
                if bet < 0:
                    return jsonify({'error': 'bad_bet'})
                gs['bets'][pid] = bet
                order = [lobby['host']['game_id']] + [g['game_id'] for g in lobby['guests']]
                gs['turn_order'] = order
                if len(gs['bets']) == len(order):
                    for p in order:
                        gs['hands'][p] = [gs['deck'].pop(), gs['deck'].pop()]
                        gs['states'][p] = 'playing'
                    gs['dealer'] = [gs['deck'].pop(), gs['deck'].pop()]
                    gs['hole_hidden'] = True
                    order_bj = []
                    for p in order:
                        if hand_score(gs['hands'][p]) == 21 and len(gs['hands'][p]) == 2:
                            gs['states'][p] = 'blackjack'
                            order_bj.append(p)
                    if len(order_bj) == len(order):
                        gs['hole_hidden'] = False
                        gs['phase'] = 'done'
                        gs['dealer_score'] = hand_score(gs['dealer'])
                        _bj_finish_online(gs)
                    else:
                        gs['turn_idx'] = 0
                        gs['phase'] = 'playing'
                        while gs['turn_idx'] < len(order) and gs['states'].get(order[gs['turn_idx']]) != 'playing':
                            gs['turn_idx'] += 1
                        if gs['turn_idx'] >= len(order):
                            _bj_dealer_turn_online(gs)

            elif gs['phase'] == 'playing':
                order = gs['turn_order']
                if gs['turn_idx'] >= len(order) or order[gs['turn_idx']] != pid:
                    return jsonify({'error': 'not_your_turn'})
                action = move.get('action')
                hand = gs['hands'][pid]
                if action == 'hit':
                    hand.append(gs['deck'].pop())
                    if hand_score(hand) > 21:
                        gs['states'][pid] = 'bust'
                        _bj_next_turn_online(gs)
                    elif hand_score(hand) == 21:
                        gs['states'][pid] = 'stand'
                        _bj_next_turn_online(gs)
                elif action == 'stand':
                    gs['states'][pid] = 'stand'
                    _bj_next_turn_online(gs)
                elif action == 'double':
                    if len(hand) != 2:
                        return jsonify({'error': 'cant_double'})
                    gs['bets'][pid] = gs['bets'].get(pid, 0) * 2
                    hand.append(gs['deck'].pop())
                    if hand_score(hand) > 21:
                        gs['states'][pid] = 'bust'
                    else:
                        gs['states'][pid] = 'stand'
                    _bj_next_turn_online(gs)

        msg = {'type': 'game_update', 'game_state': gs}
        notify_lobby(lobby_id, msg)
    return jsonify({'ok': True})


def _bj_next_turn_online(gs):
    gs['turn_idx'] += 1
    order = gs['turn_order']
    while gs['turn_idx'] < len(order) and gs['states'].get(order[gs['turn_idx']]) != 'playing':
        gs['turn_idx'] += 1
    if gs['turn_idx'] >= len(order):
        _bj_dealer_turn_online(gs)


def _bj_dealer_turn_online(gs):
    gs['hole_hidden'] = False
    while hand_score(gs['dealer']) < 17 and len(gs['dealer']) < 8:
        gs['dealer'].append(gs['deck'].pop())
    gs['phase'] = 'done'
    gs['dealer_score'] = hand_score(gs['dealer'])
    _bj_finish_online(gs)


def _bj_finish_online(gs):
    sd = gs['dealer_score']
    dealer_bj = (sd == 21 and len(gs['dealer']) == 2)
    winners = []
    results = {}
    for pid, hand in gs['hands'].items():
        s = hand_score(hand)
        state = gs['states'].get(pid, 'playing')
        player_bj = (s == 21 and len(hand) == 2)
        res = None
        if state == 'bust' or s > 21:
            res = 'lose'
        elif player_bj and not dealer_bj:
            res = 'bj'
            winners.append(pid)
        elif dealer_bj and not player_bj:
            res = 'lose'
        elif player_bj and dealer_bj:
            res = 'push'
        elif sd > 21 or s > sd:
            res = 'win'
            winners.append(pid)
        elif s < sd:
            res = 'lose'
        else:
            res = 'push'
        results[pid] = res
    gs['results'] = results
    gs['winners'] = winners
    gs['all_scores'] = {pid: hand_score(h) for pid, h in gs['hands'].items()}


@app.route('/api/lobby/game/reset', methods=['POST', 'OPTIONS'])
def game_reset():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    lobby_id = data.get('lobby_id')
    if lobby_id not in lobbies:
        return jsonify({'error': 'not_found'})
    with lock:
        lobby = lobbies[lobby_id]
        gs = lobby.get('game_state')
        if not gs:
            return jsonify({'error': 'no_game'})
        new_gs = make_initial_state(gs['type'])
        lobby['game_state'] = new_gs
        msg = {'type': 'game_reset', 'game_state': new_gs}
        notify_lobby(lobby_id, msg)
    return jsonify({'ok': True})


# ============================================================
#  WEBSOCKET
# ============================================================
@sock.route('/ws/player/<player_id>')
def player_ws(ws, player_id):
    player_sockets.setdefault(player_id, []).append(ws)
    print(f'🔌 Player WS connected: {player_id}')
    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break
            try:
                msg = json.loads(raw)
                if msg.get('action') == 'ping':
                    ws.send(json.dumps({'type': 'pong', 't': now()}))
            except Exception:
                pass
    except Exception as e:
        print(f'Player WS error ({player_id}):', e)
    finally:
        try:
            player_sockets[player_id].remove(ws)
            if not player_sockets[player_id]:
                del player_sockets[player_id]
            print(f'🔌 Player WS disconnected: {player_id}')
        except Exception:
            pass


@sock.route('/ws/lobby/<lobby_id>')
def lobby_ws(ws, lobby_id):
    if lobby_id not in lobbies:
        try:
            ws.send(json.dumps({'type': 'system', 'text': 'Лобби не существует'}))
            ws.close()
        except Exception:
            pass
        return
    lobby_sockets.setdefault(lobby_id, []).append(ws)
    player_name = 'Игрок'
    player_id = None
    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            action = msg.get('action')
            if action == 'hello':
                player_name = msg.get('name', 'Игрок')
                player_id = msg.get('player_id')
                if player_id:
                    player_sockets.setdefault(player_id, []).append(ws)
                notify_lobby(lobby_id, {'type': 'system', 'text': f"{player_name} подключился"})
                lobby = lobbies.get(lobby_id)
                if lobby:
                    notify_lobby(lobby_id, {
                        'type': 'players',
                        'players': [lobby['host']] + lobby['guests']
                    })
                    if lobby.get('game_state'):
                        notify_lobby(lobby_id, {
                            'type': 'game_update',
                            'game_state': lobby['game_state']
                        })
            elif action == 'chat':
                notify_lobby(lobby_id, {
                    'type': 'chat',
                    'text': msg.get('text', ''),
                    'name': player_name
                })
            elif action == 'ping':
                try:
                    ws.send(json.dumps({'type': 'pong', 't': now()}))
                except Exception:
                    pass
    except Exception as e:
        print(f'Lobby WS error: {e}')
    finally:
        try:
            lobby_sockets[lobby_id].remove(ws)
            if player_id and player_id in player_sockets:
                try:
                    player_sockets[player_id].remove(ws)
                except Exception:
                    pass
            notify_lobby(lobby_id, {'type': 'system', 'text': f"{player_name} отключился"})
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
#  TELEGRAM-БОТ
# ═══════════════════════════════════════════════════════════
bot_subscribers = {'users': {}, 'groups': {}}
BROADCAST_INTERVAL = 3600
SEND_DELAY = 3


def bot_load_data():
    global bot_subscribers
    try:
        with open(BOT_DATA_FILE, 'r') as f:
            data = json.load(f)
            bot_subscribers['users'] = data.get('users', {})
            bot_subscribers['groups'] = data.get('groups', {})
            print(f'📊 Бот: {len(bot_subscribers["users"])} юзеров, {len(bot_subscribers["groups"])} групп')
    except Exception:
        print('📊 Бот: файл подписчиков пуст')


def bot_save_data():
    try:
        with open(BOT_DATA_FILE, 'w') as f:
            json.dump(bot_subscribers, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print('❌ Бот: ошибка сохранения:', e)


def bot_api(method, payload):
    if not BOT_TOKEN:
        return None
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/{method}'
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f'❌ Bot API {method}:', e)
        return None


def bot_send(chat_id, text, keyboard=None):
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }
    if keyboard:
        payload['reply_markup'] = keyboard
    return bot_api('sendMessage', payload)


_bot_username_cache = None


def _get_bot_username():
    global _bot_username_cache
    if _bot_username_cache:
        return _bot_username_cache
    result = bot_api('getMe', {})
    if result and result.get('ok'):
        _bot_username_cache = result['result'].get('username', '')
    return _bot_username_cache or ''


def btn_play():
    if MINI_APP_SHORT_NAME:
        username = _get_bot_username()
        if username:
            return {'inline_keyboard': [[{
                'text': '🎰 ИГРАТЬ',
                'url': f'https://t.me/{username}/{MINI_APP_SHORT_NAME}'
            }]]}
    return {'inline_keyboard': [[{
        'text': '🎰 ИГРАТЬ',
        'web_app': {'url': GAME_URL}
    }]]}


def btn_play_group():
    return {'inline_keyboard': [[{
        'text': '🎰 ИГРАТЬ С ДРУЗЬЯМИ',
        'url': GAME_URL
    }]]}


BOT_WELCOME = """👑 <b>ДОБРО ПОЖАЛОВАТЬ В GOLDEN PALACE!</b> 👑

🎰 <b>Премиум казино прямо в Telegram</b>

🎯 <b>Plinko</b> · 🎱 <b>Keno</b> · 🎲 <b>Dice</b>
🃏 <b>Blackjack</b> · 🎡 <b>Roulette</b> · 🎰 <b>Slots</b>
🪙 <b>Coin Flip</b> · 🐎 <b>Horse Race</b> · 💎 <b>Lucky 20</b>

🌐 <b>Онлайн-режим</b> — играй с друзьями!
🛒 <b>Магазин оформлений</b> — золото, изумруд, фиолет!

💰 Начинаешь с <b>5000 монет</b>

Жми кнопку и вперёд! 👇"""


BOT_REMINDERS = [
    """👋 <b>Скучаешь?</b>\n\n🎯 Plinko ×5 · 🎱 Keno ×2\n🃏 Blackjack · 🎰 Slots\n\nЗабери куш! 💰""",
    """🔥 <b>Заходи!</b>\n\n🎰 Slots · 🎡 Roulette · 🎲 Dice\n\n1 клик до азарта! 👇""",
    """💎 <b>5000+ монет ждут!</b>\n\n🎯 Plinko · 💎 Lucky 20 · 🐎 Horse Race\n\nНе заставляй удачу ждать! 💰""",
    """⏰ <b>Бонус капает!</b>\n\nЗагляни — вдруг уже на хорошую ставку? 🎰""",
    """🎰 <b>Golden Palace!</b>\n\n🔥 Plinko ×5 · 🃏 BJ ×2.5 · 🎰 Slots ×15\n\nИграй! 👇""",
]

BOT_FACTS = [
    """🎲 <b>Интересный факт</b>\n\nСамое старое казино — <b>Casino di Venezia</b> (1638). Ему почти 400 лет! 🏛️\n\nСыграй! 👇""",
    """🎰 <b>Знаешь ли ты?</b>\n\nАвтомат <b>«Liberty Bell»</b> (1895) — первый слот с 3 барабанами!\n\nИспытай удачу! 👇""",
    """💎 <b>Интересный факт</b>\n\n«Казино» с итальянского — <b>«маленький дом»</b>.\n\nУ нас тоже дом 🏠""",
    """🃏 <b>Знаешь ли ты?</b>\n\n«Ace + 10» в BJ = блэкджек, платит <b>×2.5</b>!\n\nИспытай! 👇""",
    """🎱 <b>Про Keno</b>\n\nKeno в Китае <b>2000+ лет</b>.\n\nПопробуй! 👇""",
]

BOT_NEWS = [
    """📢 <b>Новости</b>\n\n🎱 <b>Keno!</b> Угадай число ×2!\n\nПопробуй 👇""",
    """📢 <b>Обновление!</b>\n\n🌐 Онлайн с друзьями!\n\nЗаходи 👇""",
    """📢 <b>🛒 Магазин оформлений!</b>\n\n👑 Золото · 💎 Изумруд · 🔮 Фиолет\n\nЗагляни! 👇""",
]

BOT_GROUP_MSGS = [
    """👑 <b>Golden Palace!</b>\n\n🎯 Plinko · 🎱 Keno · 🎲 Dice\n🃏 BJ · 🎡 Roulette · 🎰 Slots\n\n💰 5000 монет! 🎁 +0.2/час\n\nЖми 👇""",
    """🎰 <b>Пора играть!</b>\n\n🎯 Plinko ×5 · 🎱 Keno ×2 · 🃏 BJ ×2.5\n\n1 клик до азарта! 👇""",
    """💎 <b>Golden Palace!</b>\n\n🎲 Dice · 🎡 Roulette · 🎰 Slots\n\nОнлайн! 👇""",
    """🔥 <b>Не пропусти!</b>\n\n💰 5000 монет\n🛒 Магазин оформлений\n\nЗаходи! 👇""",
]


def bot_broadcast_loop():
    time.sleep(120)
    print('📢 Бот: рассылка запущена')
    while True:
        try:
            recipients = []
            for cid in bot_subscribers['users'].keys():
                recipients.append(('user', cid))
            for cid in bot_subscribers['groups'].keys():
                recipients.append(('group', cid))
            if not recipients:
                time.sleep(BROADCAST_INTERVAL)
                continue
            random.shuffle(recipients)
            for idx, (rtype, chat_id) in enumerate(recipients, 1):
                try:
                    if rtype == 'user':
                        pool = random.choice([BOT_REMINDERS, BOT_FACTS, BOT_NEWS])
                        bot_send(chat_id, random.choice(pool), btn_play())
                    else:
                        bot_send(chat_id, random.choice(BOT_GROUP_MSGS), btn_play_group())
                    time.sleep(SEND_DELAY)
                except Exception as e:
                    print(f'  ❌ {chat_id}:', e)
            time.sleep(BROADCAST_INTERVAL)
        except Exception as e:
            print('❌ Бот: ошибка:', e)
            time.sleep(300)


def bot_handle_update(update):
    msg = update.get('message') or update.get('edited_message')
    if not msg:
        my_chat = update.get('my_chat_member')
        if my_chat:
            bot_handle_my_chat_member(my_chat)
        return
    chat = msg.get('chat', {})
    chat_id = chat.get('id')
    chat_type = chat.get('type')
    text = (msg.get('text') or '').strip()
    from_user = msg.get('from', {})

    if chat_type in ('group', 'supergroup'):
        if str(chat_id) not in bot_subscribers['groups']:
            bot_subscribers['groups'][str(chat_id)] = {
                'title': chat.get('title', 'Группа'),
                'added_at': int(time.time())
            }
            bot_save_data()
        if text == '/start':
            bot_send(chat_id, BOT_GROUP_MSGS[0], btn_play_group())
        elif text == '/play':
            bot_send(chat_id, '🎰 <b>Играть</b> 👇', btn_play_group())
        return

    if chat_type == 'private':
        if str(chat_id) not in bot_subscribers['users']:
            bot_subscribers['users'][str(chat_id)] = {
                'first_name': from_user.get('first_name', ''),
                'username': from_user.get('username', ''),
                'added_at': int(time.time())
            }
            bot_save_data()
        if text == '/start':
            bot_send(chat_id, BOT_WELCOME, btn_play())
        elif text == '/play':
            bot_send(chat_id, '🎰 <b>Погнали!</b> 👇', btn_play())
        elif text == '/help':
            bot_send(chat_id,
                '👑 <b>Golden Palace</b>\n\n/start — привет\n/play — играть\n/help — справка',
                btn_play())


def bot_handle_my_chat_member(update):
    chat = update.get('chat', {})
    chat_id = chat.get('id')
    new_status = update.get('new_chat_member', {}).get('status')
    old_status = update.get('old_chat_member', {}).get('status')
    if old_status in ('left', 'kicked') and new_status in ('member', 'administrator'):
        bot_subscribers['groups'][str(chat_id)] = {
            'title': chat.get('title', 'Группа'),
            'added_at': int(time.time())
        }
        bot_save_data()
        bot_send(chat_id, BOT_GROUP_MSGS[0], btn_play_group())
    elif new_status in ('left', 'kicked'):
        if str(chat_id) in bot_subscribers['groups']:
            del bot_subscribers['groups'][str(chat_id)]
            bot_save_data()


def bot_polling_loop():
    print('🤖 Бот: polling запущен')
    try:
        bot_api('deleteWebhook', {'drop_pending_updates': False})
    except Exception:
        pass

    offset = 0
    error_count = 0
    while True:
        try:
            url = f'https://api.telegram.org/bot{BOT_TOKEN}/getUpdates'
            payload = {
                'offset': offset,
                'timeout': 25,
                'allowed_updates': ['message', 'edited_message', 'my_chat_member']
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
            if result.get('ok'):
                error_count = 0
                for update in result.get('result', []):
                    try:
                        bot_handle_update(update)
                    except Exception as e:
                        print('❌ Бот: ошибка обработки:', e)
                    offset = update['update_id'] + 1
            else:
                desc = result.get('description', '')
                if 'Conflict' in desc:
                    print('⚠️ Бот: конфликт polling — ждём 30 сек')
                    time.sleep(30)
                else:
                    print(f'⚠️ Бот: {desc}')
                    time.sleep(5)
        except Exception as e:
            error_count += 1
            print('❌ Бот: polling error:', e)
            time.sleep(min(5 * error_count, 60))


def start_bot():
    if not BOT_TOKEN:
        print('⚠️ BOT_TOKEN не задан — бот отключён')
        return
    try:
        me = bot_api('getMe', {})
        if me and me.get('ok'):
            username = me['result'].get('username', '?')
            print(f'✅ Бот: @{username}')
        else:
            print('⚠️ Бот: getMe не ответил, продолжаем')
    except Exception as e:
        print('⚠️ Бот: getMe error:', e)

    bot_load_data()
    threading.Thread(target=bot_polling_loop, daemon=True).start()
    threading.Thread(target=bot_broadcast_loop, daemon=True).start()
    print('✅ Бот инициализирован')


# ============================================================
#  ЗАПУСК ФОНОВЫХ ЗАДАЧ (ОДИН РАЗ)
# ============================================================
_bg_started = False


def _start_background_tasks():
    global _bg_started
    if _bg_started:
        return
    _bg_started = True

    threading.Thread(target=autosave_loop, daemon=True).start()
    threading.Thread(target=autorequest_loop, daemon=True).start()
    threading.Thread(target=hourly_bonus_loop, daemon=True).start()
    start_bot()
    print('✅ Фоновые задачи запущены')


_start_background_tasks()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
