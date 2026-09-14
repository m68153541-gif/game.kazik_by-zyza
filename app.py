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
@app.route('/api/register', methods=['POST'])
def register():
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
@app.route('/api/lobby/create', methods=['POST'])
def create_lobby():
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
            'created': now()
        }
        lobbies[lobby_id] = lobby

    return jsonify({'lobby_id': lobby_id, 'host': player})


@app.route('/api/lobby/join', methods=['POST'])
def join_lobby():
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


@app.route('/api/lobby/leave', methods=['POST'])
def leave_lobby():
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
#  ИГРОВЫЕ ДЕЙСТВИЯ (ходы, ставки, кубики и т.д.)
# ============================================================
@app.route('/api/lobby/action', methods=['POST'])
def lobby_action():
    data = request.get_json() or {}
    lobby_id = data.get('lobby_id', '')
    guest_id = data.get('guest_id')
    action = data.get('action')
    payload = data.get('payload', {})

    if lobby_id not in lobbies:
        return jsonify({'error': 'not_found'})

    with lock:
        pid = guests.get(guest_id)
        player = players.get(pid) if pid else None
        if not player:
            return jsonify({'error': 'not_registered'})

    notify_lobby(lobby_id, {
        'type': 'action',
        'action': action,
        'payload': payload,
        'from': {'id': player['game_id'], 'name': player['name']}
    })
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
