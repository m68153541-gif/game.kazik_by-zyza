import os
import json
import time
import random
import string
import threading
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

# Токены админа — в файле, чтобы переживали перезапуск
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
    'tech_break_message': '🔧 Технический перерыв\n\nСкоро вернёмся!'
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


def hourly_bonus_loop():
    while True:
        time.sleep(HOUR_SECONDS)
        try:
            with lock:
                t = now()
                for pid, p in players.items():
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
    return 'Kazik server is running'


@app.route('/<path:path>')
def static_files(path):
    if os.path.exists(path):
        return send_from_directory('.', path)
    return 'Not found', 404


@app.route('/health')
def health():
    return jsonify({
        'ok': True,
        'players': len(players),
        'lobbies': len(lobbies),
        'tg_users': len(tg_users)
    })


@app.route('/api/global/status')
def global_status():
    return jsonify({
        'tech_break': global_settings['tech_break'],
        'message': global_settings['tech_break_message']
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
#  ПРОФИЛЬ / РЕГИОН
# ============================================================
@app.route('/api/profile/region', methods=['POST', 'OPTIONS'])
def set_region():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        player['region'] = (data.get('region') or 'Не указан').strip()[:30]
        return jsonify({'ok': True, 'region': player['region']})


# ============================================================
#  ДРУЗЬЯ
# ============================================================
@app.route('/api/friends/search', methods=['POST', 'OPTIONS'])
def friends_search():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        query = (data.get('query') or '').strip()
        if not query:
            return jsonify({'results': []})
        results = []
        for pid, p in players.items():
            if pid == player['game_id']:
                continue
            if query in pid or query.lower() in p['name'].lower():
                results.append({
                    'game_id': pid,
                    'name': p['name'],
                    'region': p.get('region', 'Не указан'),
                    'online': any(
                        pl['game_id'] == pid for lob in lobbies.values()
                        for pl in [lob['host']] + (lob.get('guests') or [])
                    )
                })
        return jsonify({'results': results[:20]})


@app.route('/api/friends/request', methods=['POST', 'OPTIONS'])
def friends_request():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        target_id = data.get('target_id')
        target = players.get(target_id)
        if not target:
            return jsonify({'error': 'player_not_found'})
        if target_id == player['game_id']:
            return jsonify({'error': 'own_id'})
        if target_id in player.get('friends', []):
            return jsonify({'error': 'already_friends'})
        if target_id in player.get('friend_requests', []):
            return jsonify({'error': 'already_sent'})
        if player['game_id'] in target.get('friend_requests', []):
            target['friend_requests'].remove(player['game_id'])
            if target_id not in player['friends']:
                player.setdefault('friends', []).append(target_id)
            if player['game_id'] not in target['friends']:
                target.setdefault('friends', []).append(player['game_id'])
            notify_player(target_id, {'type': 'friends_update'})
            notify_player(player['game_id'], {'type': 'friends_update'})
            return jsonify({'ok': True, 'mutual': True})
        target.setdefault('friend_requests', []).append(player['game_id'])
        notify_player(target_id, {'type': 'friend_request', 'from': {'game_id': player['game_id'], 'name': player['name']}})
        return jsonify({'ok': True})


@app.route('/api/friends/accept', methods=['POST', 'OPTIONS'])
def friends_accept():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        from_id = data.get('from_id')
        if from_id not in player.get('friend_requests', []):
            return jsonify({'error': 'no_request'})
        player['friend_requests'].remove(from_id)
        if from_id not in player['friends']:
            player.setdefault('friends', []).append(from_id)
        other = players.get(from_id)
        if other and player['game_id'] not in other.get('friends', []):
            other.setdefault('friends', []).append(player['game_id'])
        notify_player(from_id, {'type': 'friends_update'})
        notify_player(player['game_id'], {'type': 'friends_update'})
        return jsonify({'ok': True})


@app.route('/api/friends/decline', methods=['POST', 'OPTIONS'])
def friends_decline():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        from_id = data.get('from_id')
        if from_id in player.get('friend_requests', []):
            player['friend_requests'].remove(from_id)
        return jsonify({'ok': True})


@app.route('/api/friends/list', methods=['POST', 'OPTIONS'])
def friends_list():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        friends = []
        for fid in player.get('friends', []):
            f = players.get(fid)
            if f:
                friends.append({
                    'game_id': fid,
                    'name': f['name'],
                    'region': f.get('region', 'Не указан'),
                    'online': any(
                        pl['game_id'] == fid for lob in lobbies.values()
                        for pl in [lob['host']] + (lob.get('guests') or [])
                    )
                })
        requests = []
        for rid in player.get('friend_requests', []):
            r = players.get(rid)
            if r:
                requests.append({'game_id': rid, 'name': r['name']})
        return jsonify({'friends': friends, 'requests': requests})


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
            result.append({
                'game_id': p['game_id'],
                'name': p['name'],
                'telegram_id': p.get('telegram_id', ''),
                'balance': p.get('balance', 0),
                'pending_bonus': round(p.get('pending_bonus', 0), 2),
                'region': p.get('region', 'Не указан'),
                'last_seen': p.get('last_seen', 0),
                'online': any(
                    pl['game_id'] == pid for lob in lobbies.values()
                    for pl in [lob['host']] + (lob.get('guests') or [])
                )
            })
        result.sort(key=lambda x: -x['last_seen'])
        return jsonify({
            'players': result,
            'tech_break': global_settings['tech_break'],
            'tech_break_message': global_settings['tech_break_message']
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
        notify_player(pid, {'type': 'admin_balance_update', 'balance': p['balance']})
        return jsonify({'ok': True, 'balance': p['balance']})


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
    for pid in players.keys():
        notify_player(pid, {
            'type': 'tech_break_update',
            'tech_break': enabled,
            'message': global_settings['tech_break_message']
        })
    return jsonify({'ok': True, 'tech_break': enabled})


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
#  МАГАЗИН
# ============================================================
@app.route('/api/shop/buy', methods=['POST', 'OPTIONS'])
def shop_buy():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    coins = int(data.get('coins', 0))
    stars = int(data.get('stars', 0))
    guest_id = data.get('guest_id')
    if coins <= 0 or stars <= 0:
        return jsonify({'error': 'bad_request'})
    if not BOT_TOKEN:
        return jsonify({'error': 'payment_unavailable', 'reason': 'BOT_TOKEN не настроен'})
    try:
        import urllib.request
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink'
        payload = json.dumps({
            'title': f'{coins} монет',
            'description': f'Покупка {coins} монет',
            'payload': f'coins:{coins}:guest:{guest_id}',
            'currency': 'XTR',
            'prices': [{'label': f'{coins} монет', 'amount': stars}]
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        if not result.get('ok'):
            return jsonify({'error': 'telegram_error', 'details': result})
        return jsonify({'invoice_link': result['result']})
    except Exception as e:
        return jsonify({'error': 'payment_unavailable', 'reason': str(e)})


@app.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
    data = request.get_json() or {}
    if 'message' in data and 'successful_payment' in data['message']:
        payment = data['message']['successful_payment']
        payload = payment.get('invoice_payload', '')
        try:
            parts = payload.split(':')
            coins = int(parts[1])
            guest_id = parts[3]
            with lock:
                player = find_player(guest_id=guest_id)
                if player:
                    player['balance'] = round(player.get('balance', 0) + coins, 2)
                    notify_player(player['game_id'], {'type': 'admin_balance_update', 'balance': player['balance']})
        except Exception as e:
            print('webhook error:', e)
    return jsonify({'ok': True})


# ============================================================
#  БОНУС
# ============================================================
@app.route('/api/bonus/state', methods=['POST', 'OPTIONS'])
def bonus_state():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        _accrue_bonus(player)
        return jsonify({
            'pending_bonus': round(player.get('pending_bonus', 0), 2),
            'balance': player.get('balance', 0)
        })


@app.route('/api/bonus/claim', methods=['POST', 'OPTIONS'])
def bonus_claim():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(guest_id=data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        _accrue_bonus(player)
        pb = player.get('pending_bonus', 0)
        if pb < MIN_WITHDRAW:
            return jsonify({'error': f'Минимум {MIN_WITHDRAW} монет', 'pending_bonus': round(pb, 2)})
        player['balance'] = round(player.get('balance', 0) + pb, 2)
        player['pending_bonus'] = 0.0
        notify_player(player['game_id'], {'type': 'admin_balance_update', 'balance': player['balance']})
        return jsonify({'ok': True, 'claimed': pb, 'balance': player['balance']})


# ============================================================
#  ЗАПУСК
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
