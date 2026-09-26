"""Reglas de City sin GPU ni descargas."""
import unittest
import random
from pondera.demos.city import ACTIONS, COLS, ROWS, DIRECTIONS, LIGHTS, Trip, drive, legal_moves, random_scenario, route, validate_answer


class GameChecks(unittest.TestCase):
    def test_streets_and_connectivity(self):
        self.assertNotIn("oeste", legal_moves((3, 1)))
        self.assertNotIn("este", legal_moves((3, 3)))
        self.assertNotIn("norte", legal_moves((2, 2)))
        self.assertNotIn("sur", legal_moves((4, 2)))
        nodes = [(x,y) for x in range(COLS) for y in range(ROWS)]
        for a in nodes:
            for b in nodes:
                path = route(a,b)
                self.assertEqual(path[-1], b)
                for start,end in zip(path,path[1:]):
                    self.assertIn(end, legal_moves(start).values())

    def test_stop_and_lights(self):
        trip=Trip(car=(1,0))
        self.assertEqual([k for k,v in trip.options().items() if v["habilitada"]], ["esperar"])
        self.assertEqual(trip.apply("este", {}, .5, 0, trip.snapshot())["executed"], "esperar")
        self.assertTrue(trip.stopped)
        self.assertTrue(trip.options()["este"]["habilitada"])
        for node in LIGHTS:
            for tick in range(4):
                trip=Trip(car=node,tick=tick)
                self.assertNotEqual(trip.green(node,"norte"),trip.green(node,"este"))
                for action in DIRECTIONS:
                    if not trip.green(node,action):
                        self.assertFalse(trip.options()[action]["habilitada"])

    def test_adversarial_driver_finishes(self):
        for repeated in ACTIONS:
            trip=Trip()
            for _ in range(80):
                state=trip.snapshot()
                probabilities={k:float(k==repeated) for k in ACTIONS}
                record=trip.apply(repeated,probabilities,.4,.1,state)
                self.assertTrue(record["options"][record["executed"]]["habilitada"])
                self.assertEqual(record["probabilities"],probabilities)
                if trip.done: break
            self.assertTrue(trip.done,repeated)
            self.assertTrue(trip.onboard)
            self.assertEqual(trip.car,trip.destination)
            executed=[h["executed"] for h in trip.history]
            self.assertLess(executed.index("recoger"),executed.index("entregar"))
            self.assertLessEqual(len(trip.snapshot()["historial"]),6)

    def test_drive_moves_only_on_valid_answers(self):
        trip = Trip()
        good = lambda state, q: {"answers": {"accion": {"choice": "este", "confidence": .5,
                                 "probabilities": {k: 1 / len(ACTIONS) for k in ACTIONS}}}}
        record = drive(trip, good)
        self.assertEqual((record["step"], trip.car), (1, (1, 0)))
        broken = lambda state, q: {"answers": {"accion": {"choice": "este", "confidence": .5, "probabilities": {}}}}
        with self.assertRaises(ValueError):
            drive(trip, broken)
        self.assertEqual((trip.tick, trip.car), (1, (1, 0)))  # Una respuesta inválida no mueve el coche.

    def test_view_is_json_ready(self):
        import json
        view = json.loads(json.dumps(Trip().view()))
        self.assertEqual(view["route"][0], [0, 0])
        self.assertEqual(view["route"][-1], [4, 1])
        self.assertEqual(len(view["lights"]), len(LIGHTS))

    def test_random_scenarios_are_valid_and_finish(self):
        rng = random.Random(7)
        for _ in range(40):
            scenario = random_scenario(rng)
            places = [scenario["car"], scenario["passenger"], scenario["destination"]]
            self.assertEqual(len(set(places)), 3)
            self.assertTrue(all(0 <= x < COLS and 0 <= y < ROWS for x, y in places))
            self.assertIn(scenario["heading"], legal_moves(scenario["car"]))
            # Incluso un conductor que repite siempre lo mismo termina gracias a la protección.
            trip = Trip(**scenario)
            for _ in range(120):
                trip.apply("norte", {k: float(k == "norte") for k in ACTIONS}, .4, .1, trip.snapshot())
                if trip.done:
                    break
            self.assertTrue(trip.done, scenario)

    def test_invalid_probabilities(self):
        answer={"choice":"este","confidence":.4,"probabilities":{k:float(k=="este") for k in ACTIONS}}
        validate_answer(answer)
        for bad in (float("nan"),-1,2):
            answer["probabilities"]["este"]=bad
            with self.assertRaises(ValueError): validate_answer(answer)


if __name__ == "__main__":
    unittest.main()
