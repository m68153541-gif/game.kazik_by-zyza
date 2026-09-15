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
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')  # опционально

# ============================================================
#  ХРАНИЛИЩА
# ============================================================
players = {}          # {player_id: {'game_id','name','last_seen','balance','pending_bonus','last_bonus_ts'}}
guests = {}           # {guest_id: player_id}
lobbies = {}          # {lobby_id: {...}}
lobby_sockets = {}    # {lobby_id: [ws, ws, ...]}
admin_sessions = set()  # {admin_token}
lock = threading.Lock()

# Глобальные настройки
global_settings = {
    'tech_break': False,
    'tech_break_message': '🔧 Технический перерыв\n\nСкоро вернёмся!\n\nСвежие новости:\n• Добавлен онлайн Blackjack\n• Добавлена игра Plinko\n• Фикс краша — теперь ракета падает где угодно\n• Почасовой бонус 0.2 монеты'
}


def gen_id(n=6, digits_only=True):
    chars = string.digits if digits_only else string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=n))


def now():
    return int(time.time())


def find_player(guest_id):
    pid = guests.get(guest_id)
    if not pid:
        return None
    return players.get(pid)


def hourly_bonus_loop():
    """Каждый час начисляет всем по 0.2 монеты в pending_bonus."""
    while True:
        time.sleep(HOUR_SECONDS)
        try:
            with lock:
                t = now()
                for pid, p in players.items():
                    if t - p.get('last_bonus_ts', 0) >= HOUR_SECONDS - 5:
                        p['pending_bonus'] = round(p.get('pending_bonus', 0) + HOUR_BONUS, 2)
                        p['last_bonus_ts'] = t
        except Exception as e:
            print('bonus loop error:', e)


# Стартуем фоновый поток сразу
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


# ============================================================
#  HEALTH / GLOBAL
# ============================================================
@app.route('/health')
def health():
    return jsonify({'ok': True, 'players': len(players), 'lobbies': len(lobbies)})


@app.route('/api/global/status')
def global_status():
    return jsonify({
        'tech_break': global_settings['tech_break'],
        'message': global_settings['tech_break_message']
    })


# ============================================================
#  РЕГИСТРАЦИЯ
# ============================================================
@app.route('/api/register', methods=['POST', 'OPTIONS'])
def register():
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()[:20]
    guest_id = data.get('guest_id')

    if len(name) < 2:
        return jsonify({'error': 'Имя минимум 2 символа'})

    with lock:
        player = find_player(guest_id) if guest_id else None
        if player:
            player['name'] = name
            player['last_seen'] = now()
            # Обновим pending_bonus по прошедшим часам
            _accrue_bonus(player)
            return jsonify({'player': _pub(player), 'guest_id': guest_id})

        pid = gen_id(6)
        while pid in players:
            pid = gen_id(6)

        player = {
            'game_id': pid,
            'name': name,
            'last_seen': now(),
            'balance': 5000.0,
            'pending_bonus': 0.0,
            'last_bonus_ts': now()
        }
        players[pid] = player
        if guest_id:
            guests[guest_id] = pid

    return jsonify({'player': _pub(player), 'guest_id': guest_id})


def _accrue_bonus(player):
    t = now()
    elapsed = t - player.get('last_bonus_ts', t)
    hours = int(elapsed // HOUR_SECONDS)
    if hours > 0:
        player['pending_bonus'] = round(player.get('pending_bonus', 0) + hours * HOUR_BONUS, 2)
        player['last_bonus_ts'] = t


def _pub(player):
    return {
        'game_id': player['game_id'],
        'name': player['name'],
        'balance': player.get('balance', 0),
        'pending_bonus': round(player.get('pending_bonus', 0), 2)
    }


# ============================================================
#  БОНУС
# ============================================================
@app.route('/api/bonus/state', methods=['POST', 'OPTIONS'])
def bonus_state():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(data.get('guest_id'))
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
        player = find_player(data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        _accrue_bonus(player)
        pb = player.get('pending_bonus', 0)
        if pb < MIN_WITHDRAW:
            return jsonify({'error': f'Минимум {MIN_WITHDRAW} монет', 'pending_bonus': round(pb, 2)})
        player['balance'] = round(player.get('balance', 0) + pb, 2)
        player['pending_bonus'] = 0.0
        return jsonify({
            'ok': True,
            'claimed': pb,
            'balance': player['balance']
        })


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
    admin_sessions.add(token)
    return jsonify({'token': token})


def _check_admin(data):
    return data.get('admin_token') in admin_sessions if data.get('admin_token') else False


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
                'balance': p.get('balance', 0),
                'pending_bonus': round(p.get('pending_bonus', 0), 2),
                'last_seen': p.get('last_seen', 0),
                'online': any(
                    pl['game_id'] == pid for lob in lobbies.values()
                    for pl in [lob['host']] + ([lob['guest']] if lob['guest'] else [])
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
    mode = data.get('mode', 'add')  # add | set
    with lock:
        p = players.get(pid)
        if not p:
            return jsonify({'error': 'player_not_found'})
        if mode == 'set':
            p['balance'] = max(0.0, round(amount, 2))
        else:
            p['balance'] = max(0.0, round(p.get('balance', 0) + amount, 2))
        # Уведомляем игрока через WebSocket, если он в лобби
        for lid, lob in lobbies.items():
            for pl in [lob['host']] + ([lob['guest']] if lob['guest'] else []):
                if pl['game_id'] == pid:
                    notify_lobby(lid, {
                        'type': 'admin_balance_update',
                        'balance': p['balance']
                    })
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
        p = find_player(guest_id)
        if not p:
            return jsonify({'error': 'player_not_found'})
        p['balance'] = max(0.0, round(p.get('balance', 0) + amount, 2))
        return jsonify({'ok': True, 'balance': p['balance']})


# ============================================================
#  МАГАЗИН — реальная оплата звёздами
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
        return jsonify({
            'error': 'payment_unavailable',
            'reason': 'BOT_TOKEN не настроен на сервере'
        })

    # Формируем ссылку на invoice через Telegram Bot API
    try:
        import urllib.request
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink'
        payload = json.dumps({
            'title': f'{coins} монет',
            'description': f'Покупка {coins} монет в игре Казик',
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


# ============================================================
#  ЛОББИ
# ============================================================
@app.route('/api/lobby/create', methods=['POST', 'OPTIONS'])
def create_lobby():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    with lock:
        player = find_player(data.get('guest_id'))
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
            'guests': [],       # поддерживаем 2-3 игроков
            'game_type': data.get('game_type', 'rps'),
            'created': now(),
            'game_state': None
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
        player = find_player(data.get('guest_id'))
        if not player:
            return jsonify({'error': 'not_registered'})
        if lobby_id not in lobbies:
            return jsonify({'error': 'not_found'})
        lobby = lobbies[lobby_id]

        # Нельзя дважды
        if lobby['host']['game_id'] == player['game_id']:
            return jsonify({'error': 'own_lobby'})
        if any(g['game_id'] == player['game_id'] for g in lobby['guests']):
            return jsonify({'error': 'already_in'})

        if len(lobby['guests']) >= 2:  # хост + до 2 гостей = макс 3
            return jsonify({'error': 'full'})

        lobby['guests'].append(_pub(player))

        notify_lobby(lobby_id, {
            'type': 'players',
            'players': [lobby['host']] + lobby['guests']
        })

        return jsonify({
            'lobby_id': lobby_id,
            'host': lobby['host'],
            'guests': lobby['guests']
        })


@app.route('/api/lobby/leave', methods=['POST', 'OPTIONS'])
def leave_lobby():
    if request.method == 'OPTIONS':
        return '', 204
    lobby_id = (request.args.get('lobby_id') or '').strip()
    data = request.get_json() or {}
    with lock:
        player = find_player(data.get('guest_id'))
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


@app.route('/api/lobby/state')
def lobby_state():
    lobby_id = (request.args.get('lobby_id') or '').strip()
    if lobby_id not in lobbies:
        return jsonify({'error': 'not_found'})
    l = lobbies[lobby_id]
    return jsonify({
        'lobby_id': lobby_id,
        'host': l['host'],
        'guests': l['guests'],
        'game_type': l['game_type']
    })


# ============================================================
#  ИГРОВАЯ ЛОГИКА
# ============================================================
def make_initial_state(game_type):
    gs = {
        'type': game_type,
        'phase': 'playing',
    }
    if game_type == 'lucky20':
        gs['win_idx'] = random.randint(0, 19)
        gs['turn'] = 'host'
        gs['opened'] = []
    elif game_type == 'horserace':
        r = random.random(); acc = 0
        weights = [0.30, 0.25, 0.20, 0.13, 0.08, 0.04]
        winner = 0
        for i, w in enumerate(weights):
            acc += w
            if r < acc:
                winner = i; break
        gs['winner_horse'] = winner
        gs['picks'] = {}  # {player_id: horse_index}
    elif game_type == 'dice':
        gs['rolls'] = {}  # {player_id: [d1,d2]}
    elif game_type == 'blackjack':
        gs['deck'] = _make_deck()
        gs['dealer'] = []
        gs['hands'] = {}   # {player_id: [cards]}
        gs['state'] = {}   # {player_id: 'playing'|'stand'|'bust'}
        gs['turn_order'] = []
        gs['turn_idx'] = 0
        gs['phase'] = 'dealing'
        gs['started'] = False
    return gs


def _make_deck():
    suits = ['♠','♥','♦','♣']
    ranks = ['A','2','3','4','5','6','7','8','9','10','J','Q','K']
    d = [{'s': s, 'r': r} for s in suits for r in ranks]
    random.shuffle(d)
    return d


def _card_val(c):
    if c['r'] == 'A': return 11
    if c['r'] in ('J','Q','K','10'): return 10
    return int(c['r'])


def _hand_score(hand):
    s = sum(_card_val(c) for c in hand)
    aces = sum(1 for c in hand if c['r'] == 'A')
    while s > 21 and aces > 0:
        s -= 10; aces -= 1
    return s


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
        player = find_player(guest_id)
        if not player:
            return jsonify({'error': 'not_registered'})
        lobby = lobbies[lobby_id]
        if lobby['host']['game_id'] != player['game_id']:
            return jsonify({'error': 'not_host'})
        if not lobby['guests']:
            return jsonify({'error': 'no_guest'})
        gs = make_initial_state(game_type)
        lobby['game_state'] = gs

        # Для блэкджека — сразу раздать карты
        if game_type == 'blackjack':
            _bj_start(lobby, gs)

        notify_lobby(lobby_id, {'type': 'game_init', 'game_state': _sanitize_bj(gs, player['game_id'], 'init')})
        return jsonify({'ok': True})


def _bj_start(lobby, gs):
    """Раздаёт карты: 2 хосту, 2 каждому гостю, 2 дилеру."""
    order = [lobby['host']] + lobby['guests']
    gs['turn_order'] = [p['game_id'] for p in order]
    gs['turn_idx'] = 0
    for p in order:
        gs['hands'][p['game_id']] = [gs['deck'].pop(), gs['deck'].pop()]
        gs['state'][p['game_id']] = 'playing'
    gs['dealer'] = [gs['deck'].pop(), gs['deck'].pop()]
    gs['started'] = True
    gs['phase'] = 'player_turns'


def _sanitize_bj(gs, for_player_id, stage):
    """В онлайне игрок видит только свой счёт. В конце — всех."""
    if gs.get('type') != 'blackjack':
        return gs
    out = dict(gs)
    out['deck'] = []  # не отдаём колоду
    if stage == 'init' or gs.get('phase') == 'player_turns':
        # Скрываем руки других игроков и дилера
        out['hands'] = {pid: (h if pid == for_player_id else ['?','?']) for pid, h in gs['hands'].items()}
        out['dealer'] = [gs['dealer'][0], '?'] if gs.get('dealer') else []
    else:
        out['hands'] = gs['hands']
        out['dealer'] = gs['dealer']
    return out


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
        player = find_player(guest_id)
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

        elif gs['type'] == 'horserace':
            horse = int(move.get('horse', -1))
            if horse < 0 or horse > 5:
                return jsonify({'error': 'bad_move'})
            gs['picks'][pid] = horse
            # все выбрали?
            if len(gs['picks']) == 1 + len(lobby['guests']):
                gs['phase'] = 'done'
                win = gs['winner_horse']
                winners = [p for p, h in gs['picks'].items() if h == win]
                gs['winners'] = winners

        elif gs['type'] == 'dice':
            dice = move.get('dice', [0, 0])
            if not isinstance(dice, list) or len(dice) != 2:
                return jsonify({'error': 'bad_move'})
            gs['rolls'][pid] = dice
            if len(gs['rolls']) == 1 + len(lobby['guests']):
                gs['phase'] = 'done'
                best = -1; winners = []
                for p, d in gs['rolls'].items():
                    s = sum(d)
                    if s > best:
                        best = s; winners = [p]
                    elif s == best:
                        winners.append(p)
                gs['winners'] = winners
                gs['best'] = best

        elif gs['type'] == 'blackjack':
            if gs.get('phase') != 'player_turns':
                return jsonify({'error': 'not_your_turn'})
            # Чей ход?
            order = gs['turn_order']
            if gs['turn_idx'] >= len(order) or order[gs['turn_idx']] != pid:
                return jsonify({'error': 'not_your_turn'})
            action = move.get('action')
            hand = gs['hands'][pid]
            if action == 'hit':
                hand.append(gs['deck'].pop())
                if _hand_score(hand) > 21:
                    gs['state'][pid] = 'bust'
                    _bj_next_turn(lobby, gs)
            elif action == 'stand':
                gs['state'][pid] = 'stand'
                _bj_next_turn(lobby, gs)

        notify_lobby(lobby_id, {
            'type': 'game_update',
            'game_state': _sanitize_bj(gs, pid, 'update')
        })
        return jsonify({'ok': True})


def _bj_next_turn(lobby, gs):
    gs['turn_idx'] += 1
    order = gs['turn_order']
    while gs['turn_idx'] < len(order) and gs['state'].get(order[gs['turn_idx']]) != 'playing':
        gs['turn_idx'] += 1
    if gs['turn_idx'] >= len(order):
        # Дилер добирает
        while _hand_score(gs['dealer']) < 17:
            gs['dealer'].append(gs['deck'].pop())
        gs['phase'] = 'done'
        d_score = _hand_score(gs['dealer'])
        winners = []
        for pid, hand in gs['hands'].items():
            s = _hand_score(hand)
            if gs['state'].get(pid) == 'bust':
                continue
            if s > 21:
                continue
            if d_score > 21 or s > d_score:
                winners.append(pid)
        gs['winners'] = winners
        gs['dealer_score'] = d_score


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
        if gs['type'] == 'blackjack':
            _bj_start(lobby, new_gs)
        lobby['game_state'] = new_gs
        notify_lobby(lobby_id, {'type': 'game_reset', 'game_state': new_gs})
    return jsonify({'ok': True})


# ============================================================
#  WEBSOCKET
# ============================================================
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
        print(f'WS error: {e}')
    finally:
        try:
            lobby_sockets[lobby_id].remove(ws)
            notify_lobby(lobby_id, {'type': 'system', 'text': f"{player_name} отключился"})
        except Exception:
            pass


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
