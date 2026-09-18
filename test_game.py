import unittest

from app import FUNCTION_CARDS, app, equation_text, occupied_cells, rooms, socketio


class OccupancyTests(unittest.TestCase):
    def test_all_fourteen_function_cards_are_available(self):
        self.assertEqual(len(FUNCTION_CARDS), 14)
        self.assertEqual(
            {coefficient for coefficient, _ in FUNCTION_CARDS},
            {4.0, 3.0, 2.0, 1.0, 0.5, 1 / 3, 0.25, -0.25, -1 / 3, -0.5, -1.0, -2.0, -3.0, -4.0},
        )

    def test_new_fraction_equation_is_formatted(self):
        self.assertEqual(equation_text(1 / 3, 2, -4), "y = ⅓(x - 2)² - 4")

    def test_vertex_cells_are_occupied(self):
        cells = occupied_cells(1.0, -5, 8)
        self.assertIn("-5,8", cells)
        self.assertIn("-6,8", cells)

    def test_outside_curve_does_not_fill_board(self):
        cells = occupied_cells(2.0, 0, 8)
        self.assertLess(len(cells), 80)
        self.assertGreater(len(cells), 0)

    def test_downward_parabola(self):
        cells = occupied_cells(-1.0, 0, 0)
        self.assertIn("0,-1", cells)
        self.assertIn("-1,-1", cells)


class OrderFlowTests(unittest.TestCase):
    def setUp(self):
        rooms.clear()
        self.clients = [socketio.test_client(app) for _ in range(3)]

    def tearDown(self):
        for client in self.clients:
            client.disconnect()
        rooms.clear()

    def test_every_player_draws_unique_number_and_order_is_sorted(self):
        self.clients[0].emit("create_room", {"name": "가"})
        joined = next(event for event in self.clients[0].get_received() if event["name"] == "joined")["args"][0]
        code = joined["state"]["code"]
        tokens = [joined["token"]]
        for client, name in zip(self.clients[1:], ["나", "다"]):
            client.emit("join_room", {"code": code, "name": name})
            result = next(event for event in client.get_received() if event["name"] == "joined")["args"][0]
            tokens.append(result["token"])

        self.clients[0].emit("begin_ordering", {"code": code, "token": tokens[0]})
        for client, token in zip(self.clients, tokens):
            client.emit("draw_order", {"code": code, "token": token})

        room = rooms[code]
        numbers = [room.order_draws[player.token] for player in room.players]
        self.assertEqual(len(set(numbers)), 3)
        self.assertEqual(numbers, sorted(numbers, reverse=True))

        self.clients[0].emit("start_game", {"code": code, "token": tokens[0]})
        self.assertEqual(room.status, "dealing")
        self.assertEqual(len(room.bombs), 4)
        for hand in room.hands.values():
            self.assertEqual([len(hand[category]) for category in ("function", "x", "y")], [0, 0, 0])

        for client, token in zip(self.clients, tokens):
            for category in ("function", "x", "y"):
                client.emit("draw_from_deck", {"code": code, "token": token, "category": category})
        self.assertEqual(room.status, "playing")
        for hand in room.hands.values():
            self.assertEqual([len(hand[category]) for category in ("function", "x", "y")], [5, 5, 5])

        current = room.players[room.turn_index]
        hand = room.hands[current.token]
        function_card, x_card, y_card = hand["function"][0], hand["x"][0], hand["y"][0]
        path = occupied_cells(float(function_card["value"]), int(x_card["value"]), int(y_card["value"]))
        room.bombs = {path[0]}
        room.board[path[0]] = tokens[0]
        current_client = self.clients[tokens.index(current.token)]
        current_client.emit(
            "play_cards",
            {
                "code": code,
                "token": current.token,
                "functionId": function_card["id"],
                "xId": x_card["id"],
                "yId": y_card["id"],
            },
        )
        self.assertEqual(room.turns_played, 1)
        self.assertEqual(len(room.hands[current.token]["function"]), 4)
        self.assertEqual(len(room.last_play["bombs"]), 1)
        self.assertGreater(room.last_play["deleted"], 0)
        self.assertNotIn(path[0], room.board)

    def test_test_code_starts_single_player_card_draw(self):
        client = socketio.test_client(app)
        try:
            client.emit("join_room", {"code": "TEST01", "name": "테스터"})
            joined = next(event for event in client.get_received() if event["name"] == "joined")["args"][0]
            state = joined["state"]
            token = joined["token"]
            self.assertTrue(state["testMode"])
            self.assertEqual(state["status"], "dealing")
            self.assertEqual(len(state["players"]), 1)
            self.assertEqual(state["totalTurns"], 5)

            for category in ("function", "x", "y"):
                client.emit("draw_from_deck", {"code": state["code"], "token": token, "category": category})
            self.assertEqual(rooms[state["code"]].status, "playing")
        finally:
            client.disconnect()


if __name__ == "__main__":
    unittest.main()
