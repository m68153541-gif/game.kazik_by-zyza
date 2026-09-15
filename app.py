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
#  ХРАНИЛИЩЕ
# ============================================================
players = {}
guests = {}
lobbies = {}
lobby_sockets = {}
lock = threading.Lock()


def gen_id(n=6, digits_only=True):
    chars = string.digits if digits_only else string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=n))


def now():
    return int(time.time())


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
        if guest_id and guest_id in guests:
            pid = guests[guest_id]
            player = players.get(pid)
            if player:
                player['name'] = name
                player['last_seen'] = now()
                return jsonify({'player': player, 'guest_id': guest_id})

        pid = gen_id(6)
        while pid in players:
            pid = gen_id(6)

        player = {'game_id': pid, 'name': name, 'last_seen': now()}
        players[pid] = player
        if guest_id:
            guests[guest_id] = pid

    return jsonify({'player': player, 'guest_id': guest_id})


# ============================================================
#  ЛОББИ
# ============================================================
@app.route('/api/lobby/create', methods=['POST', 'OPTIONS'])
def create_lobby():
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json() or {}
    guest_id = data.get('guest_id')

    with lock:
        pid = guests.get(guest_id)
        player = players.get(pid) if pid else None
        if not player:
            return jsonify({'error': 'not_registered'})

        for lid in list(lobbies.keys()):
            l = lobbies[lid]
            if l['host']['game_id'] == player['game_id'] or (l['guest'] and l['guest']['game_id'] == player['game_id']):
                del lobbies[lid]

        lobby_id = gen_id(6)
        while lobby_id in lobbies:
            lobby_id = gen_id(6)

        lobby = {
            'lobby_id': lobby_id,
            'host': dict(player),
            'guest': None,
            'game_type': data.get('game_type', 'rps'),
            'created': now(),
            'game_state': None
        }
        lobbies[lobby_id] = lobby

    return jsonify({'lobby_id': lobby_id, 'host': player})


@app.route('/api/lobby/join', methods=['POST', 'OPTIONS'])
def join_lobby():
    if request.method == 'OPTIONS':
        return '', 204

    lobby_id = (request.args.get('lobby_id') or '').strip()
    data = request.get_json() or {}
    guest_id = data.get('guest_id')

    with lock:
        pid = guests.get(guest_id)
        player = players.get(pid) if pid else None
        if not player:
            return jsonify({'error': 'not_registered'})

        if lobby_id not in lobbies:
            return jsonify({'error': 'not_found'})

        lobby = lobbies[lobby_id]

        if lobby['host']['game_id'] == player['game_id']:
            return jsonify({'error': 'own_lobby'})

        if lobby['guest'] is not None:
            return jsonify({'error': 'full'})

        lobby['guest'] = dict(player)

        notify_lobby(lobby_id, {
            'type': 'players',
            'players': [
                {'id': lobby['host']['game_id'], 'name': lobby['host']['name']},
                {'id': player['game_id'], 'name': player['name']}
            ]
        })

        result = {
            'lobby_id': lobby_id,
            'host': lobby['host'],
            'guest': lobby['guest']
        }

    return jsonify(result)


@app.route('/api/lobby/leave', methods=['POST', 'OPTIONS'])
def leave_lobby():
    if request.method == 'OPTIONS':
        return '', 204

    lobby_id = (request.args.get('lobby_id') or '').strip()
    data = request.get_json() or {}
    guest_id = data.get('guest_id')

    with lock:
        pid = guests.get(guest_id)
        player = players.get(pid) if pid else None
        if not player or lobby_id not in lobbies:
            return jsonify({'ok': True})

        lobby = lobbies[lobby_id]

        if lobby['guest'] and lobby['guest']['game_id'] == player['game_id']:
            lobby['guest'] = None
            notify_lobby(lobby_id, {'type': 'system', 'text': f"{player['name']} покинул лобби"})
        elif lobby['host']['game_id'] == player['game_id']:
            notify_lobby(lobby_id, {'type': 'system', 'text': 'Хост закрыл лобби'})
            del lobbies[lobby_id]

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
        'guest': l['guest'],
        'game_type': l['game_type']
    })


# ============================================================
#  ИГРОВАЯ ЛОГИКА
# ============================================================
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
        pid = guests.get(guest_id)
        player = players.get(pid) if pid else None
        if not player:
            return jsonify({'error': 'not_registered'})

        lobby = lobbies[lobby_id]
        if lobby['host']['game_id'] != player['game_id']:
            return jsonify({'error': 'not_host'})

        if not lobby['guest']:
            return jsonify({'error': 'no_guest'})

        game_state = {
            'type': game_type,
            'phase': 'betting',
            'host_bet': 0,
            'guest_bet': 0,
            'host_ready': False,
            'guest_ready': False,
        }

        if game_type == 'lucky20':
            game_state['win_idx'] = random.randint(0, 19)
            game_state['turn'] = 'host'
            game_state['opened'] = []
            game_state['tries_left'] = 3
        elif game_type == 'horserace':
            r = random.random()
            acc = 0
            weights = [0.30, 0.25, 0.20, 0.13, 0.08, 0.04]
            winner = 0
            for i, w in enumerate(weights):
                acc += w
                if r < acc:
                    winner = i
                    break
            game_state['winner_horse'] = winner
            game_state['host_pick'] = None
            game_state['guest_pick'] = None

        lobby['game_state'] = game_state

        notify_lobby(lobby_id, {
            'type': 'game_init',
            'game_state': game_state
        })

    return jsonify({'ok': True, 'game_state': game_state})


@app.route('/api/lobby/game/bet', methods=['POST', 'OPTIONS'])
def game_bet():
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json() or {}
    lobby_id = data.get('lobby_id')
    guest_id = data.get('guest_id')
    bet = int(data.get('bet', 0))

    if lobby_id not in lobbies:
        return jsonify({'error': 'not_found'})

    with lock:
        pid = guests.get(guest_id)
        player = players.get(pid) if pid else None
        if not player:
            return jsonify({'error': 'not_registered'})

        lobby = lobbies[lobby_id]
        gs = lobby.get('game_state')
        if not gs:
            return jsonify({'error': 'no_game'})

        is_host = lobby['host']['game_id'] == player['game_id']
        if is_host:
            gs['host_bet'] = bet
            gs['host_ready'] = True
        else:
            gs['guest_bet'] = bet
            gs['guest_ready'] = True

        if gs['host_ready'] and gs['guest_ready']:
            gs['phase'] = 'playing'
            notify_lobby(lobby_id, {
                'type': 'game_start_real',
                'game_state': gs
            })
        else:
            notify_lobby(lobby_id, {
                'type': 'bet_update',
                'host_ready': gs['host_ready'],
                'guest_ready': gs['guest_ready'],
                'host_bet': gs['host_bet'],
                'guest_bet': gs['guest_bet']
            })

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
        pid = guests.get(guest_id)
        player = players.get(pid) if pid else None
        if not player:
            return jsonify({'error': 'not_registered'})

        lobby = lobbies[lobby_id]
        gs = lobby.get('game_state')
        if not gs or gs['phase'] != 'playing':
            return jsonify({'error': 'not_playing'})

        is_host = lobby['host']['game_id'] == player['game_id']

        if gs['type'] == 'lucky20':
            current_turn = gs.get('turn')
            if (is_host and current_turn != 'host') or (not is_host and current_turn != 'guest'):
                return jsonify({'error': 'not_your_turn'})

            idx = int(move.get('idx', -1))
            if idx < 0 or idx > 19 or idx in gs['opened']:
                return jsonify({'error': 'bad_move'})

            gs['opened'].append(idx)

            if idx == gs['win_idx']:
                gs['phase'] = 'done'
                gs['winner'] = 'host' if is_host else 'guest'
            else:
                gs['tries_left'] -= 1
                if gs['tries_left'] <= 0:
                    gs['phase'] = 'done'
                    gs['winner'] = 'guest' if is_host else 'host'
                else:
                    gs['turn'] = 'guest' if is_host else 'host'

        elif gs['type'] == 'horserace':
            horse = int(move.get('horse', -1))
            if horse < 0 or horse > 5:
                return jsonify({'error': 'bad_move'})
            if is_host:
                gs['host_pick'] = horse
            else:
                gs['guest_pick'] = horse

            if gs['host_pick'] is not None and gs['guest_pick'] is not None:
                gs['phase'] = 'done'
                win_horse = gs['winner_horse']
                host_wins = gs['host_pick'] == win_horse
                guest_wins = gs['guest_pick'] == win_horse
                if host_wins and not guest_wins:
                    gs['winner'] = 'host'
                elif guest_wins and not host_wins:
                    gs['winner'] = 'guest'
                elif host_wins and guest_wins:
                    gs['winner'] = 'both'
                else:
                    gs['winner'] = 'none'

        notify_lobby(lobby_id, {
            'type': 'game_update',
            'game_state': gs
        })

    return jsonify({'ok': True, 'game_state': gs})


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

        game_type = gs['type']
        gs['phase'] = 'betting'
        gs['host_bet'] = 0
        gs['guest_bet'] = 0
        gs['host_ready'] = False
        gs['guest_ready'] = False
        gs.pop('winner', None)

        if game_type == 'lucky20':
            gs['win_idx'] = random.randint(0, 19)
            gs['turn'] = 'host'
            gs['opened'] = []
            gs['tries_left'] = 3
        elif game_type == 'horserace':
            r = random.random()
            acc = 0
            weights = [0.30, 0.25, 0.20, 0.13, 0.08, 0.04]
            winner = 0
            for i, w in enumerate(weights):
                acc += w
                if r < acc:
                    winner = i
                    break
            gs['winner_horse'] = winner
            gs['host_pick'] = None
            gs['guest_pick'] = None

        notify_lobby(lobby_id, {
            'type': 'game_reset',
            'game_state': gs
        })

    return jsonify({'ok': True, 'game_state': gs})


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
                    plist = [{'id': lobby['host']['game_id'], 'name': lobby['host']['name']}]
                    if lobby['guest']:
                        plist.append({'id': lobby['guest']['game_id'], 'name': lobby['guest']['name']})
                    notify_lobby(lobby_id, {'type': 'players', 'players': plist})

            elif action == 'chat':
                notify_lobby(lobby_id, {
                    'type': 'chat',
                    'text': msg.get('text', ''),
                    'name': player_name
                })

            elif action == 'game_start':
                notify_lobby(lobby_id, {'type': 'game_start', 'game_type': msg.get('game_type', 'rps')})

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


@app.route('/health')
def health():
    return jsonify({'ok': True, 'players': len(players), 'lobbies': len(lobbies)})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
