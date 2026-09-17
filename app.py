import os
import json
import time
import random
import string
import threading
import urllib.request
from flask import Flask, request, jsonify, send_from_directory
from flask_sock import Sock

app = Flask(__name__, static_folder='.')
sock = Sock(app)

# ============================================================
#  CORS
# ============================================================
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
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
GAME_URL = 'https://game-kazik-by-zyza.onrender.com'
BOT_DATA_FILE = 'bot_subscribers.json'

# ============================================================
#  ХРАНИЛИЩА ИГРЫ
# ============================================================
players = {}
guests = {}
tg_users = {}
lobbies = {}
lobby_sockets = {}
player_sockets = {}
lock = threading.Lock()

# Виртуальный игрок для антисна
VIRTUAL_PLAYER_ID = '999999'
VIRTUAL_PLAYER_GUEST = 'virtual_keepalive_bot'

ADMIN_TOKENS_FILE = 'admin_tokens.json'

def _load_admin_sessions():
    try:
        with open(ADMIN_TOKENS_FILE, 'r') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _save_admin_sessions(sessions):
    try:
        with open(ADMIN_TOKENS_FILE, 'w') as f:
            json.dump(sessions, f)
    except Exception as e:
        print('save admin tokens error:', e)

admin_sessions = _load_admin_sessions()
ADMIN_TOKEN_TTL = 30 * 24 * 3600

global_settings = {
    'tech_break': False,
    'tech_break_message': '🔧 Технический перерыв\n\nСкоро вернёмся!',
    'keepalive': False
}


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
    return {
        'game_id': player['game_id'],
        'name': player['name'],
        'balance': player.get('balance', 0),
        'pending_bonus': round(player.get('pending_bonus', 0), 2),
        'region': player.get('region', 'Не указан'),
        'friends': player.get('friends', []),
        'friend_requests': player.get('friend_requests', [])
    }


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
#  ВИРТУАЛЬНЫЙ ИГРОК
# ============================================================
def _create_virtual_player():
    with lock:
        if VIRTUAL_PLAYER_ID in players:
            return
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
            'is_virtual': True
        }
        guests[VIRTUAL_PLAYER_GUEST] = VIRTUAL_PLAYER_ID

_create_virtual_player()


# ============================================================
#  АНТИСОН
# ============================================================
_keepalive_stop = threading.Event()

def keepalive_loop():
    while True:
        try:
            if global_settings.get('keepalive'):
                url = os.environ.get('RENDER_EXTERNAL_URL', '')
                if url:
                    ping_url = url.rstrip('/') + '/health'
                else:
                    port = os.environ.get('PORT', '5000')
                    ping_url = f'http://127.0.0.1:{port}/health'
                try:
                    req = urllib.request.Request(ping_url, headers={'User-Agent': 'kazik-keepalive/1.0'})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        print(f'🛡 Антисон пинг → {ping_url} ({resp.status})')
                except Exception as e:
                    print(f'🛡 Антисон ошибка: {e}')
                with lock:
                    if VIRTUAL_PLAYER_ID in players:
                        players[VIRTUAL_PLAYER_ID]['last_seen'] = now()
        except Exception as e:
            print(f'🛡 Антисон loop error: {e}')
        for _ in range(60):
            if _keepalive_stop.is_set():
                _keepalive_stop.clear()
                break
            time.sleep(5)

threading.Thread(target=keepalive_loop, daemon=True).start()


# ============================================================
#  ЕЖЕЧАСНЫЙ БОНУС
# ============================================================
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

threading.Thread(target=hourly_bonus_loop, daemon=True).start()


# ============================================================
#  СТАТИКА
# ============================================================
@app.route('/')
def index():
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
        'players': len(players) - 1,
        'tg_users': len(tg_users),
        'sockets': len(player_sockets),
        'lobbies': len(lobbies),
        'keepalive': global_settings.get('keepalive', False),
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
        'keepalive': global_settings.get('keepalive', False)
    })


# ============================================================
#  АВТО-РЕГИСТРАЦИЯ
# ============================================================
def parse_init_data(init_data):
    if not init_data:
        return None
    try:
        import urllib.parse
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
            return jsonify({'player': _pub(player), 'guest_id': guest_id or player['game_id']})

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
            'friend_requests': []
        }
        players[pid] = player
        if guest_id:
            guests[guest_id] = pid
        if telegram_id:
            tg_users[telegram_id] = pid
    return jsonify({'player': _pub(player), 'guest_id': guest_id or pid})


# ============================================================
#  АДМИН
# ============================================================
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
        return jsonify({
            'players': result,
            'tech_break': global_settings['tech_break'],
            'tech_break_message': global_settings['tech_break_message'],
            'keepalive': global_settings.get('keepalive', False)
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
        notify_player(pid, {'type': 'admin_balance_update', 'balance': new_balance})
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
    return jsonify({'ok': True, 'tech_break': enabled})


@app.route('/api/admin/keepalive', methods=['POST', 'OPTIONS'])
def admin_keepalive():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    if not _check_admin(data):
        return jsonify({'error': 'unauthorized'})
    enabled = bool(data.get('enabled'))
    global_settings['keepalive'] = enabled
    if enabled:
        _keepalive_stop.set()
    print(f'🛡 Антисон: {"ВКЛ" if enabled else "ВЫКЛ"}')
    return jsonify({'ok': True, 'keepalive': enabled})


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
        notify_player(p['game_id'], {'type': 'admin_balance_update', 'balance': p['balance']})
        return jsonify({'ok': True, 'balance': p['balance']})


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
#  ИГРЫ — Lucky20 и Dice
# ============================================================
def make_initial_state(game_type):
    gs = {'type': game_type, 'phase': 'playing'}
    if game_type == 'lucky20':
        gs['win_idx'] = random.randint(0, 19)
        gs['turn'] = 'host'
        gs['opened'] = []
    elif game_type == 'dice':
        gs['rolls'] = {}
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
        if game_type not in ('lucky20', 'dice'):
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

        msg = {'type': 'game_update', 'game_state': gs}
        notify_lobby(lobby_id, msg)
    return jsonify({'ok': True})


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
#  WEBSOCKET — ИГРОК
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


# ============================================================
#  WEBSOCKET — ЛОББИ
# ============================================================
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
#  TELEGRAM-БОТ (встроен в тот же процесс)
# ═══════════════════════════════════════════════════════════
bot_subscribers = {
    'users': {},
    'groups': {}
}
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
        with urllib.request.urlopen(req, timeout=15) as resp:
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


def btn_play():
    return {'inline_keyboard': [[{'text': '🎰 ИГРАТЬ', 'url': GAME_URL}]]}


def btn_play_group():
    return {'inline_keyboard': [[{'text': '🎰 ИГРАТЬ С ДРУЗЬЯМИ', 'url': GAME_URL}]]}


BOT_WELCOME = """👑 <b>ДОБРО ПОЖАЛОВАТЬ В GOLDEN PALACE!</b> 👑

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


BOT_REMINDERS = [
    """👋 <b>Скучаешь?</b>\n\nВ Golden Palace ждут:\n🎯 Plinko до ×5\n🎱 Keno\n🃏 Blackjack\n\nЗабери свой куш! 💰""",
    """🔥 <b>Заходи, мы скучали!</b>\n\n🎰 Slots · 🎡 Roulette · 🎲 Dice\n\nВсего 1 клик до азарта! 👇""",
    """💎 <b>Тебя ждут 5000+ монет!</b>\n\n🎯 Plinko · 💎 Lucky 20 · 🐎 Horse Race\n\nНе заставляй удачу ждать! 💰""",
    """⏰ <b>Напоминание от Golden Palace</b>\n\nТвой ежечасный бонус капает! Загляни — вдруг уже на хорошую ставку? 🎰""",
    """🎰 <b>Golden Palace заждалось!</b>\n\n🔥 Plinko ×5 · 🃏 BJ ×2.5 · 🎰 Slots ×15\n\nИграй прямо сейчас! 👇""",
    """🎯 <b>Пора играть!</b>\n\nОдна ставка — и ты легенда!\n🎱 Keno ×2 · 🃏 BJ ×2.5 · 🎰 Slots ×15""",
]

BOT_FACTS = [
    """🎲 <b>Интересный факт</b>\n\nСамое старое казино в мире — <b>Casino di Venezia</b> (Венеция, 1638). Ему почти 400 лет! 🏛️\n\nСыграй в Golden Palace! 👇""",
    """🎰 <b>Знаешь ли ты?</b>\n\nАвтомат <b>«Liberty Bell»</b> (1895) — первый в мире слот с 3 барабанами. Он подарил нам 🍒🍋🍇!\n\nИспытай удачу! 👇""",
    """💎 <b>Интересный факт</b>\n\nСлово «казино» с итальянского — <b>«маленький дом»</b>. Так называли виллы знати, где устраивали игры.\n\nВ Golden Palace мы тоже дома 🏠""",
    """🎡 <b>Про рулетку</b>\n\nВ европейской рулетке <b>37 чисел</b>, в американской — <b>38</b> (ещё 00). У нас классическая европейская 🎯""",
    """🃏 <b>Знаешь ли ты?</b>\n\nВ Blackjack «Ace + 10» = блэкджек, платит <b>×2.5</b> вместо ×2!\n\nИспытай удачу! 👇""",
    """🎱 <b>Про Keno</b>\n\nKeno появилось в Древнем Китае <b>2000+ лет назад</b>. Вместо шариков — деревянные дощечки!\n\nПопробуй современную версию! 👇""",
    """🐎 <b>Интересный факт</b>\n\nПервые записи о ставках на лошадей — <b>VI век н.э.</b> в Греции.\n\nВыбери фаворита! 🏁""",
    """🎯 <b>Про Plinko</b>\n\n«Plinko» — от звука, который издаёт шарик <b>«plink»</b>, ударяясь о пеги!\n\nЗапусти и услышь сам! 👇""",
    """💰 <b>Интересный факт</b>\n\nВ Монте-Карло казино запрещено местным — только туристам. С 1911 года!\n\nА у нас вход открыт всем 🎰""",
    """🎲 <b>Про кубики</b>\n\nИгра в кости — <b>древнейшая</b> азартная игра. Ей больше 5000 лет!\n\nКинь кубики в Dice! 👇""",
]

BOT_NEWS = [
    """📢 <b>Новости Golden Palace</b>\n\n🎱 <b>Новая игра — Keno!</b>\nУгадай число 1-10 и выиграй ×2!\n\nПопробуй 👇""",
    """📢 <b>Обновление!</b>\n\n🌐 <b>Онлайн-режим</b> — играй с друзьями в Lucky 20 и Dice!\n\nЗаходи 👇""",
    """📢 <b>Что нового</b>\n\n✨ Обновили дизайн\n🎵 Добавили музыку\n👑 Премиум-стиль\n\nЗагляни! 👇""",
    """📢 <b>Golden Palace растёт!</b>\n\n👥 Сотни игроков\n💰 Миллионы монет\n🎁 Почасовой бонус\n\nПрисоединяйся! 👇""",
]

BOT_GROUP_MSGS = [
    """👑 <b>Golden Palace — премиум казино!</b>\n\n🎯 Plinko · 🎱 Keno · 🎲 Dice\n🃏 Blackjack · 🎡 Roulette · 🎰 Slots\n🪙 Coin Flip · 🐎 Horse Race · 💎 Lucky 20\n\n💰 5000 монет бесплатно!\n🎁 +0.2 монеты каждый час\n\nЖми 👇""",
    """🎰 <b>Пора играть!</b>\n\n🎯 Plinko ×5 · 🎱 Keno ×2 · 🃏 BJ ×2.5\n\nВсего 1 клик до азарта! 👇""",
    """💎 <b>Golden Palace ждёт!</b>\n\n🎲 Dice · 🎡 Roulette · 🎰 Slots\n🐎 Horse Race · 💎 Lucky 20\n\nОнлайн с друзьями! 👇""",
    """🔥 <b>Не пропусти!</b>\n\n💰 5000 монет новым\n🎁 Почасовой бонус\n🌐 Онлайн-режим\n\nЗаходи! 👇""",
    """🎯 <b>Испытай удачу!</b>\n\n🎰 Slots ×15 · 🃏 BJ ×2.5\n🎱 Keno ×2 · 🎯 Plinko ×5\n\nПопробуй! 👇""",
    """🎁 <b>Хочешь лёгких денег?</b>\n\n💰 5000 монет новым\n🎁 0.2 монеты/час\n🏆 Множители до ×15\n\nЖми 👇""",
]


def bot_broadcast_loop():
    """Рассылка ВСЕМ сразу каждые BROADCAST_INTERVAL секунд, с задержкой SEND_DELAY"""
    time.sleep(120)
    print('📢 Бот: рассылка запущена')

    while True:
        try:
            recipients = []
            for cid, info in bot_subscribers['users'].items():
                recipients.append(('user', cid))
            for cid, info in bot_subscribers['groups'].items():
                recipients.append(('group', cid))

            if not recipients:
                print('📢 Бот: нет подписчиков — спим')
                time.sleep(BROADCAST_INTERVAL)
                continue

            random.shuffle(recipients)
            total = len(recipients)
            print(f'📢 Бот: рассылка для {total} получателей')
            print(f'⏱ Займёт ~{total * SEND_DELAY} сек ({(total * SEND_DELAY) // 60} мин)')

            sent = 0
            for idx, (rtype, chat_id) in enumerate(recipients, 1):
                try:
                    if rtype == 'user':
                        pool = random.choice([BOT_REMINDERS, BOT_FACTS, BOT_NEWS, BOT_REMINDERS])
                        text = random.choice(pool)
                        bot_send(chat_id, text, btn_play())
                    else:
                        text = random.choice(BOT_GROUP_MSGS)
                        bot_send(chat_id, text, btn_play_group())
                    sent += 1
                    if idx % 10 == 0:
                        print(f'  📤 {idx}/{total}')
                    time.sleep(SEND_DELAY)
                except Exception as e:
                    print(f'  ❌ {chat_id}:', e)

            print(f'✅ Бот: рассылка завершена ({sent}/{total})')
            time.sleep(BROADCAST_INTERVAL)

        except Exception as e:
            print('❌ Бот: ошибка рассылки:', e)
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
            print(f'➕ Бот: группа {chat.get("title")}')
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
            print(f'➕ Бот: юзер {from_user.get("first_name")}')
        if text == '/start':
            bot_send(chat_id, BOT_WELCOME, btn_play())
        elif text == '/play':
            bot_send(chat_id, '🎰 <b>Погнали!</b> 👇', btn_play())
        elif text == '/help':
            bot_send(chat_id,
                '👑 <b>Golden Palace</b>\n\n'
                '📋 Команды:\n'
                '/start — приветствие\n'
                '/play — начать игру\n'
                '/help — справка\n\n'
                '🎰 Играй прямо в Telegram!',
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
        print(f'➕ Бот добавлен в группу: {chat.get("title")}')
        bot_send(chat_id, BOT_GROUP_MSGS[0], btn_play_group())
    elif new_status in ('left', 'kicked'):
        if str(chat_id) in bot_subscribers['groups']:
            del bot_subscribers['groups'][str(chat_id)]
            bot_save_data()
            print(f'➖ Бот удалён из группы: {chat.get("title")}')


def bot_polling_loop():
    print('🤖 Бот: polling запущен')
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
                        bot_handle_update(update)
                    except Exception as e:
                        print('❌ Бот: ошибка обработки:', e)
                    offset = update['update_id'] + 1
        except Exception as e:
            print('❌ Бот: polling error:', e)
            time.sleep(5)


def start_bot():
    if not BOT_TOKEN:
        print('⚠️ BOT_TOKEN не задан — бот не запущен')
        return
    bot_load_data()
    threading.Thread(target=bot_polling_loop, daemon=True).start()
    threading.Thread(target=bot_broadcast_loop, daemon=True).start()
    print('✅ Бот инициализирован')


# Запускаем бота сразу при импорте
start_bot()


# ============================================================
#  ЗАПУСК СЕРВЕРА
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
