from __future__ import annotations

import random
import secrets
import string
import threading
from dataclasses import dataclass, field
from typing import Any

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room


app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(24)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

BOARD_MIN = -10
BOARD_MAX = 10
ROUNDS_PER_PLAYER = 5
MAX_PLAYERS = 4
MIN_PLAYERS = 3
BOMB_COUNT = 4
BOMB_RADIUS = 2
TEST_CODE = "TEST01"
PLAYER_COLORS = ["#ff5d73", "#36c5f0", "#ffbd2e", "#8b6cff"]

FUNCTION_CARDS = [
    (4.0, "y = 4x²"),
    (3.0, "y = 3x²"),
    (2.0, "y = 2x²"),
    (1.0, "y = x²"),
    (0.5, "y = ½x²"),
    (1 / 3, "y = ⅓x²"),
    (0.25, "y = ¼x²"),
    (-0.25, "y = -¼x²"),
    (-1 / 3, "y = -⅓x²"),
    (-0.5, "y = -½x²"),
    (-1.0, "y = -x²"),
    (-2.0, "y = -2x²"),
    (-3.0, "y = -3x²"),
    (-4.0, "y = -4x²"),
]
MOVE_CARDS = list(range(-8, 9))


@dataclass
class Player:
    token: str
    name: str
    color: str
    sid: str | None = None


@dataclass
class GameRoom:
    code: str
    host_token: str
    players: list[Player] = field(default_factory=list)
    status: str = "lobby"
    turn_index: int = 0
    turns_played: int = 0
    board: dict[str, str] = field(default_factory=dict)
    last_play: dict[str, Any] | None = None
    order_draws: dict[str, int] = field(default_factory=dict)
    hands: dict[str, dict[str, list[dict[str, Any]]]] = field(default_factory=dict)
    bombs: set[str] = field(default_factory=set)
    decks: dict[str, dict[str, list[dict[str, Any]]]] = field(default_factory=dict)
    test_mode: bool = False


rooms: dict[str, GameRoom] = {}
rooms_lock = threading.RLock()


def clean_name(value: Any) -> str:
    return " ".join(str(value or "").strip().split())[:12]


def make_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if code not in rooms:
            return code


def find_player(room: GameRoom, token: str) -> Player | None:
    return next((player for player in room.players if player.token == token), None)


def format_shift(axis: str, value: int) -> str:
    sign = "+" if value >= 0 else ""
    return f"{axis}축 {sign}{value}"


def equation_text(a: float, h: int, k: int) -> str:
    coefficients = {
        4.0: "4",
        3.0: "3",
        2.0: "2",
        1.0: "",
        0.5: "½",
        1 / 3: "⅓",
        0.25: "¼",
        -0.25: "-¼",
        -1 / 3: "-⅓",
        -0.5: "-½",
        -1.0: "-",
        -2.0: "-2",
        -3.0: "-3",
        -4.0: "-4",
    }
    if h == 0:
        inner = "x"
    elif h > 0:
        inner = f"x - {h}"
    else:
        inner = f"x + {abs(h)}"
    vertical = "" if k == 0 else f" {'+' if k > 0 else '-'} {abs(k)}"
    return f"y = {coefficients[a]}({inner})²{vertical}"


def occupied_cells(a: float, h: int, k: int) -> list[str]:
    """Return every unit cell touched by y=a(x-h)^2+k.

    A curve touches a cell when its y-range over that cell's closed x interval
    overlaps the cell's closed y interval. Closed bounds intentionally count a
    graph running exactly along a grid edge as touching both neighboring cells.
    """
    touched: set[str] = set()
    for x in range(BOARD_MIN, BOARD_MAX):
        candidates = [a * (x - h) ** 2 + k, a * (x + 1 - h) ** 2 + k]
        if x <= h <= x + 1:
            candidates.append(float(k))
        curve_low, curve_high = min(candidates), max(candidates)
        for y in range(BOARD_MIN, BOARD_MAX):
            if curve_high >= y and curve_low <= y + 1:
                touched.add(f"{x},{y}")
    return sorted(touched)


def make_card(value: float | int, label: str) -> dict[str, Any]:
    return {"id": secrets.token_hex(5), "value": value, "label": label}


def empty_hand() -> dict[str, list[dict[str, Any]]]:
    return {"function": [], "x": [], "y": []}


def build_deck() -> dict[str, list[dict[str, Any]]]:
    functions = list(FUNCTION_CARDS)
    x_moves = list(MOVE_CARDS)
    y_moves = list(MOVE_CARDS)
    random.shuffle(functions)
    random.shuffle(x_moves)
    random.shuffle(y_moves)
    return {
        "function": [make_card(value, label) for value, label in functions],
        "x": [make_card(value, format_shift("x", value)) for value in x_moves],
        "y": [make_card(value, format_shift("y", value)) for value in y_moves],
    }


def private_hand(room: GameRoom, token: str) -> dict[str, Any]:
    return {"cards": room.hands.get(token, empty_hand())}


def begin_card_draw_phase(room: GameRoom) -> None:
    room.turn_index = 0
    room.turns_played = 0
    room.board.clear()
    room.last_play = None
    room.bombs = place_bombs()
    room.hands = {player.token: empty_hand() for player in room.players}
    room.decks = {player.token: build_deck() for player in room.players}
    room.status = "dealing"


def all_hands_ready(room: GameRoom) -> bool:
    return all(
        len(room.hands.get(player.token, {}).get(category, [])) == ROUNDS_PER_PLAYER
        for player in room.players
        for category in ("function", "x", "y")
    )


def place_bombs() -> set[str]:
    cells = [f"{x},{y}" for x in range(BOARD_MIN, BOARD_MAX) for y in range(BOARD_MIN, BOARD_MAX)]
    return set(random.sample(cells, BOMB_COUNT))


def explode_bombs(room: GameRoom, triggered: list[str]) -> int:
    blast_cells: set[str] = set()
    for bomb in triggered:
        bomb_x, bomb_y = map(int, bomb.split(","))
        for x in range(max(BOARD_MIN, bomb_x - BOMB_RADIUS), min(BOARD_MAX, bomb_x + BOMB_RADIUS + 1)):
            for y in range(max(BOARD_MIN, bomb_y - BOMB_RADIUS), min(BOARD_MAX, bomb_y + BOMB_RADIUS + 1)):
                blast_cells.add(f"{x},{y}")
    deleted = sum(1 for cell in blast_cells if cell in room.board)
    for cell in blast_cells:
        room.board.pop(cell, None)
    room.bombs.difference_update(triggered)
    return deleted


def scores(room: GameRoom) -> dict[str, int]:
    result = {player.token: 0 for player in room.players}
    for owner in room.board.values():
        if owner in result:
            result[owner] += 1
    return result


def public_state(room: GameRoom) -> dict[str, Any]:
    score_map = scores(room)
    total_turns = len(room.players) * ROUNDS_PER_PLAYER
    winner_tokens: list[str] = []
    if room.status == "finished" and score_map:
        best = max(score_map.values())
        winner_tokens = [token for token, score in score_map.items() if score == best]
    return {
        "code": room.code,
        "status": room.status,
        "hostToken": room.host_token,
        "players": [
            {
                "token": player.token,
                "name": player.name,
                "color": player.color,
                "connected": player.sid is not None,
                "score": score_map[player.token],
                "orderNumber": room.order_draws.get(player.token),
                "cardsRemaining": len(room.hands.get(player.token, {}).get("function", [])),
                "cardsDrawn": sum(len(cards) for cards in room.hands.get(player.token, {}).values()),
            }
            for player in room.players
        ],
        "turnToken": room.players[room.turn_index].token if room.status == "playing" else None,
        "turnsPlayed": room.turns_played,
        "totalTurns": total_turns,
        "round": min(ROUNDS_PER_PLAYER, room.turns_played // max(1, len(room.players)) + 1),
        "board": room.board,
        "lastPlay": room.last_play,
        "winnerTokens": winner_tokens,
        "orderReady": len(room.order_draws) == len(room.players) and len(room.players) >= MIN_PLAYERS,
        "testMode": room.test_mode,
        "settings": {
            "boardMin": BOARD_MIN,
            "boardMax": BOARD_MAX,
            "rounds": ROUNDS_PER_PLAYER,
            "bombCount": BOMB_COUNT,
            "bombRadius": BOMB_RADIUS,
        },
    }


def error(message: str) -> None:
    emit("game_error", {"message": message})


@app.get("/")
def index():
    return render_template("index.html")


@socketio.on("create_room")
def create_room(data: dict[str, Any]):
    name = clean_name(data.get("name"))
    if not name:
        return error("닉네임을 입력해 주세요.")
    with rooms_lock:
        code = make_code()
        token = secrets.token_urlsafe(18)
        player = Player(token=token, name=name, color=PLAYER_COLORS[0], sid=request.sid)
        room = GameRoom(code=code, host_token=token, players=[player])
        rooms[code] = room
        join_room(code)
        emit("joined", {"token": token, "state": public_state(room)})


@socketio.on("join_room")
def join_game(data: dict[str, Any]):
    code = str(data.get("code") or "").strip().upper()
    name = clean_name(data.get("name"))
    reconnect_token = str(data.get("token") or "")
    with rooms_lock:
        if code == TEST_CODE:
            if not name:
                return error("테스트 모드에서도 닉네임을 입력해 주세요.")
            room_code = make_code()
            token = secrets.token_urlsafe(18)
            player = Player(token=token, name=name, color=PLAYER_COLORS[0], sid=request.sid)
            room = GameRoom(code=room_code, host_token=token, players=[player], test_mode=True)
            room.order_draws[token] = 100
            begin_card_draw_phase(room)
            rooms[room_code] = room
            join_room(room_code)
            emit("joined", {"token": token, "state": public_state(room)})
            emit("hand", private_hand(room, token))
            return
        room = rooms.get(code)
        if not room:
            return error("존재하지 않는 초대 코드입니다.")

        returning = find_player(room, reconnect_token) if reconnect_token else None
        if returning:
            returning.sid = request.sid
            join_room(code)
            emit("joined", {"token": returning.token, "state": public_state(room)})
            if room.status in ("dealing", "playing", "finished"):
                emit("hand", private_hand(room, returning.token))
            socketio.emit("state", public_state(room), to=code)
            return

        if room.status != "lobby":
            return error("이미 순서 정하기가 시작된 방입니다.")
        if len(room.players) >= MAX_PLAYERS:
            return error("이 방은 이미 4명으로 가득 찼습니다.")
        if not name:
            return error("닉네임을 입력해 주세요.")
        if any(player.name.casefold() == name.casefold() for player in room.players):
            return error("같은 닉네임을 사용 중인 플레이어가 있습니다.")

        token = secrets.token_urlsafe(18)
        room.players.append(Player(token=token, name=name, color=PLAYER_COLORS[len(room.players)], sid=request.sid))
        join_room(code)
        emit("joined", {"token": token, "state": public_state(room)})
        socketio.emit("state", public_state(room), to=code)


@socketio.on("begin_ordering")
def begin_ordering(data: dict[str, Any]):
    code = str(data.get("code") or "").upper()
    token = str(data.get("token") or "")
    with rooms_lock:
        room = rooms.get(code)
        if not room or token != room.host_token:
            return error("방장만 순서 정하기를 시작할 수 있습니다.")
        if room.status != "lobby":
            return error("이미 순서 정하기가 시작되었습니다.")
        if len(room.players) < MIN_PLAYERS:
            return error("순서를 정하려면 최소 3명이 필요합니다.")
        room.status = "ordering"
        room.order_draws.clear()
        socketio.emit("state", public_state(room), to=code)


@socketio.on("draw_order")
def draw_order(data: dict[str, Any]):
    code = str(data.get("code") or "").upper()
    token = str(data.get("token") or "")
    with rooms_lock:
        room = rooms.get(code)
        if not room or room.status != "ordering":
            return error("현재는 순서를 뽑을 수 없습니다.")
        if not find_player(room, token):
            return error("이 방의 플레이어가 아닙니다.")
        if token in room.order_draws:
            return error("순서 숫자는 한 번만 뽑을 수 있습니다.")
        available = [number for number in range(1, 101) if number not in room.order_draws.values()]
        room.order_draws[token] = secrets.choice(available)
        if len(room.order_draws) == len(room.players):
            room.players.sort(key=lambda player: room.order_draws[player.token], reverse=True)
        socketio.emit("state", public_state(room), to=code)


@socketio.on("start_game")
def start_game(data: dict[str, Any]):
    code = str(data.get("code") or "").upper()
    token = str(data.get("token") or "")
    with rooms_lock:
        room = rooms.get(code)
        if not room or token != room.host_token:
            return error("방장만 게임을 시작할 수 있습니다.")
        if room.status != "ordering":
            return error("먼저 플레이 순서를 정해야 합니다.")
        if len(room.order_draws) != len(room.players):
            return error("모든 플레이어가 순서 숫자를 뽑아야 합니다.")
        begin_card_draw_phase(room)
        socketio.emit("state", public_state(room), to=code)
        for player in room.players:
            if player.sid:
                socketio.emit("hand", private_hand(room, player.token), to=player.sid)


@socketio.on("draw_from_deck")
def draw_from_deck(data: dict[str, Any]):
    code = str(data.get("code") or "").upper()
    token = str(data.get("token") or "")
    category = str(data.get("category") or "")
    with rooms_lock:
        room = rooms.get(code)
        if not room or room.status != "dealing":
            return error("현재는 카드를 뽑는 단계가 아닙니다.")
        if category not in ("function", "x", "y"):
            return error("올바른 카드 더미를 선택해 주세요.")
        hand = room.hands.get(token)
        deck = room.decks.get(token)
        if hand is None or deck is None:
            return error("이 방의 플레이어가 아닙니다.")
        if hand[category]:
            return error("이 카드 묶음은 이미 뽑았습니다.")
        for _ in range(ROUNDS_PER_PLAYER):
            hand[category].append(deck[category].pop())
        emit("hand", private_hand(room, token))
        if all_hands_ready(room):
            room.status = "playing"
        socketio.emit("state", public_state(room), to=code)


@socketio.on("play_cards")
def play_cards(data: dict[str, Any]):
    code = str(data.get("code") or "").upper()
    token = str(data.get("token") or "")
    with rooms_lock:
        room = rooms.get(code)
        if not room or room.status != "playing":
            return error("진행 중인 게임을 찾을 수 없습니다.")
        current = room.players[room.turn_index]
        if current.token != token:
            return error("아직 내 차례가 아닙니다.")
        hand = room.hands.get(token)
        if not hand:
            return error("카드 정보를 찾을 수 없습니다.")
        selected_ids = {
            "function": str(data.get("functionId") or ""),
            "x": str(data.get("xId") or ""),
            "y": str(data.get("yId") or ""),
        }
        selected: dict[str, dict[str, Any]] = {}
        for category, card_id in selected_ids.items():
            card = next((item for item in hand[category] if item["id"] == card_id), None)
            if not card:
                return error("함수·x축·y축 카드를 각각 한 장씩 선택해 주세요.")
            selected[category] = card

        a = float(selected["function"]["value"])
        function_label = selected["function"]["label"]
        x_shift = int(selected["x"]["value"])
        y_shift = int(selected["y"]["value"])
        cells = occupied_cells(a, x_shift, y_shift)
        captured = sum(1 for cell in cells if room.board.get(cell) not in (None, token))
        for cell in cells:
            room.board[cell] = token
        triggered = sorted(bomb for bomb in room.bombs if bomb in cells)
        deleted = explode_bombs(room, triggered)
        for category, card in selected.items():
            hand[category].remove(card)

        room.last_play = {
            "playNumber": room.turns_played + 1,
            "playerToken": token,
            "playerName": current.name,
            "color": current.color,
            "functionCard": function_label,
            "xCard": format_shift("x", x_shift),
            "yCard": format_shift("y", y_shift),
            "a": a,
            "h": x_shift,
            "k": y_shift,
            "equation": equation_text(a, x_shift, y_shift),
            "cells": cells,
            "captured": captured,
            "bombs": [{"x": int(cell.split(",")[0]), "y": int(cell.split(",")[1])} for cell in triggered],
            "deleted": deleted,
        }
        room.turns_played += 1
        if room.turns_played >= len(room.players) * ROUNDS_PER_PLAYER:
            room.status = "finished"
        else:
            room.turn_index = (room.turn_index + 1) % len(room.players)
        socketio.emit("state", public_state(room), to=code)
        if current.sid:
            socketio.emit("hand", private_hand(room, token), to=current.sid)


@socketio.on("disconnect")
def disconnected():
    with rooms_lock:
        changed: list[GameRoom] = []
        for room in rooms.values():
            for player in room.players:
                if player.sid == request.sid:
                    player.sid = None
                    changed.append(room)
        for room in changed:
            socketio.emit("state", public_state(room), to=room.code)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
