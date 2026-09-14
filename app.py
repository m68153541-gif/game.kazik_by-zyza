# ============================================================
#  ИГРОВАЯ ЛОГИКА — состояние хранится в лобби
# ============================================================

@app.route('/api/lobby/game/init', methods=['POST', 'OPTIONS'])
def game_init():
    """Инициализация игры в лобби. Вызывается хостом."""
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

        # Инициализация состояния игры
        game_state = {
            'type': game_type,
            'phase': 'betting',  # betting → playing → done
            'host_bet': 0,
            'guest_bet': 0,
            'host_ready': False,
            'guest_ready': False,
        }

        if game_type == 'lucky20':
            # Выбираем выигрышную ячейку (0..19)
            game_state['win_idx'] = random.randint(0, 19)
            game_state['turn'] = 'host'  # кто ходит
            game_state['opened'] = []    # какие ячейки открыты
            game_state['tries_left'] = 3
        elif game_type == 'horserace':
            # Случайный победитель по весам
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

        # Отправляем обоим через WebSocket
        notify_lobby(lobby_id, {
            'type': 'game_init',
            'game_state': game_state
        })

    return jsonify({'ok': True, 'game_state': game_state})


@app.route('/api/lobby/game/bet', methods=['POST', 'OPTIONS'])
def game_bet():
    """Игрок подтверждает ставку."""
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

        # Если оба готовы — начинаем
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
    """Ход игрока (открытие ячейки в lucky20)."""
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
        current_turn = gs.get('turn')
        if (is_host and current_turn != 'host') or (not is_host and current_turn != 'guest'):
            return jsonify({'error': 'not_your_turn'})

        if gs['type'] == 'lucky20':
            idx = int(move.get('idx', -1))
            if idx < 0 or idx > 19 or idx in gs['opened']:
                return jsonify({'error': 'bad_move'})

            gs['opened'].append(idx)

            if idx == gs['win_idx']:
                # Победил тот, кто открыл
                gs['phase'] = 'done'
                gs['winner'] = 'host' if is_host else 'guest'
            else:
                gs['tries_left'] -= 1
                if gs['tries_left'] <= 0:
                    gs['phase'] = 'done'
                    # Победил соперник (тот, кто НЕ ходил последним)
                    gs['winner'] = 'guest' if is_host else 'host'
                else:
                    gs['turn'] = 'guest' if is_host else 'host'

        elif gs['type'] == 'horserace':
            # Ход в скачках — просто выбор коня
            horse = int(move.get('horse', -1))
            if horse < 0 or horse > 5:
                return jsonify({'error': 'bad_move'})
            if is_host:
                gs['host_pick'] = horse
            else:
                gs['guest_pick'] = horse

            if gs['host_pick'] is not None and gs['guest_pick'] is not None:
                # Оба выбрали — считаем результат
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
    """Сброс игры к фазе ставок для новой партии."""
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
