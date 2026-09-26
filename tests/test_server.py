"""API del servidor con un modelo falso."""
import json
import threading
from collections import defaultdict
import unittest
import urllib.error
import urllib.parse
import urllib.request

from city import ACTIONS
from server import App, build_apps, serve


class FakeModel:
    def __init__(self):
        self.fail = False

    def predict(self, state, questions):
        if self.fail:
            raise RuntimeError("modelo caído")
        answers = {}
        for key, q in questions.items():
            if q["type"] == "noul":
                answers[key] = {"noul": .5}
            elif q["type"] == "score":
                answers[key] = {"score": 1.0, "confidence": .5, "probabilities": {str(i): .25 for i in range(len(q["criteria"]))}}
            else:
                keys = list(q["criteria"])
                choice = "este" if "este" in keys else keys[0]
                answers[key] = {"choice": choice, "confidence": .7, "probabilities": {k: 1 / len(keys) for k in keys}}
        return {"answers": answers}


class ServerChecks(unittest.TestCase):
    def test_remote_only_has_jev_and_luna_without_laya(self):
        apps = build_apps(remote_only=True)
        self.assertEqual(list(apps), ["jev", "gpt-luna"])

    @classmethod
    def setUpClass(cls):
        cls.model = FakeModel()
        cls.server = serve(App(cls.model, prior=defaultdict(float)), port=0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, method="GET"):
        request = urllib.request.Request(self.base + path, method=method)
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.headers["Content-Type"], response.read()

    def events(self, query=None, path=None):
        found = []
        url = self.base + (path or "/api/atlas/query?q=" + urllib.parse.quote(query))
        with urllib.request.urlopen(url, timeout=20) as r:
            kind = None
            for raw in r:
                line = raw.decode().rstrip("\n")
                if line.startswith("event: "):
                    kind = line[7:]
                elif line.startswith("data: "):
                    found.append((kind, json.loads(line[6:])))
                    if kind in ("done", "failed"):
                        return found
        return found

    def test_pages_and_static_files(self):
        status, kind, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", kind)
        for page in ("/atlas", "/city", "/courses", "/tools", "/style.css", "/lib.js"):
            self.assertEqual(self.get(page)[0], 200, page)

    def test_files_outside_web_are_not_served(self):
        for path in ("/../server.py", "/%2e%2e/server.py", "//etc/passwd", "/nada.html"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.get(path)
            self.assertEqual(error.exception.code, 404, path)

    def test_atlas_streams_every_country(self):
        countries = json.loads(self.get("/api/atlas/countries")[2])
        mexico = next(c for c in countries if c["id"] == "MEX")
        self.assertIn("muy picante", mexico["texto"])
        events = self.events("Comida picante")
        kinds = [kind for kind, _ in events]
        self.assertEqual(set(kinds[:-1]), {"batch"})
        self.assertEqual(kinds[-1], "done")
        scored = {code for kind, data in events if kind == "batch" for code in data}
        self.assertEqual(scored, {c["id"] for c in countries})

    def test_atlas_rejects_empty_or_long_queries(self):
        for query in ("   ", "x" * 501):
            self.assertEqual([kind for kind, _ in self.events(query)], ["failed"])

    def test_city_steps_resets_and_survives_model_errors(self):
        self.get("/api/city/reset", "POST")
        city = json.loads(self.get("/api/city")[2])
        self.assertEqual(city["map"]["cols"], 6)
        self.assertEqual(city["view"]["tick"], 0)
        step = json.loads(self.get("/api/city/step", "POST")[2])
        self.assertEqual(step["view"]["tick"], 1)
        self.assertEqual(step["record"]["winner"], "este")
        self.model.fail = True
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.get("/api/city/step", "POST")
            self.assertEqual(error.exception.code, 500)
            self.assertIn("modelo caído", json.loads(error.exception.read())["error"])
        finally:
            self.model.fail = False
        self.assertEqual(json.loads(self.get("/api/city")[2])["view"]["tick"], 1)  # No se movió.
        self.assertEqual(json.loads(self.get("/api/city/reset", "POST")[2])["view"]["tick"], 0)

    def test_shuffle_changes_the_trip_and_reset_repeats_it(self):
        shuffled = json.loads(self.get("/api/city/shuffle", "POST")[2])["view"]
        places = (shuffled["car"], shuffled["passenger"], shuffled["destination"])
        self.assertEqual(len({tuple(p) for p in places}), 3)
        self.get("/api/city/step", "POST")
        again = json.loads(self.get("/api/city/reset", "POST")[2])["view"]
        self.assertEqual((again["car"], again["passenger"], again["destination"], again["tick"]), (*places, 0))


    def test_courses_builds_a_roadmap_until_it_is_done(self):
        catalog = json.loads(self.get("/api/courses")[2])
        self.assertTrue(catalog["cursos"] and catalog["objetivos"] and catalog["perfiles"])
        view = json.loads(self.get("/api/courses/reset?objetivo=data-science&perfil=ana", "POST")[2])["view"]
        self.assertEqual((view["objetivo"], view["perfil"], view["ruta"]), ("data-science", "ana", []))
        steps = 0
        while not view["done"]:
            payload = json.loads(self.get("/api/courses/step", "POST")[2])
            record, view = payload["record"], payload["view"]
            steps += 1
            self.assertIn(record["curso"], [c["id"] for c in record["candidatos"]])
            self.assertEqual(record["paso"], steps)
        self.assertEqual((len(view["ruta"]), len(view["history"])), (steps, steps))
        for path in ("/api/courses/step", "/api/courses/reset?objetivo=no-existe"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.get(path, "POST")
            self.assertEqual(error.exception.code, 409, path)  # Ruta terminada / objetivo desconocido.

    def test_tool_router_traces_a_route_for_a_prompt(self):
        box = json.loads(self.get("/api/tools")[2])
        self.assertEqual(len(box["herramientas"]), 20)
        self.assertTrue(all("referencia" not in e for e in box["ejemplos"]))  # La ruta esperada no llega a la página.
        empty = json.loads(self.get("/api/tools/reset", "POST")[2])["view"]
        self.assertEqual((empty["done"], empty["llamadas"]), (True, []))  # Sin petición no hay ruta.
        prompt = urllib.parse.quote("Agenda una reunión con Nordia")
        view = json.loads(self.get(f"/api/tools/reset?q={prompt}", "POST")[2])["view"]
        self.assertEqual((view["peticion"], view["done"]), ("Agenda una reunión con Nordia", False))
        turns = 0
        while not view["done"]:
            payload = json.loads(self.get("/api/tools/step", "POST")[2])
            record, view = payload["record"], payload["view"]
            turns += 1
            self.assertEqual(record["vuelta"], turns)
        self.assertTrue(view["llamadas"])
        self.assertEqual([c["id"] for c in view["llamadas"]], [c["id"] for r in view["history"] for c in r["llamadas"]])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get("/api/tools/step", "POST")
        self.assertEqual(error.exception.code, 409)

    def test_help_desk_assigns_every_ticket_once(self):
        self.get("/api/tickets/reset", "POST")
        desk = json.loads(self.get("/api/tickets")[2])
        self.assertEqual(len(desk["tickets"]), 20)
        self.assertTrue(all("referencia" not in t for t in desk["tickets"]))  # Las referencias van por separado.
        self.assertEqual(len(desk["referencias"]), 20)
        self.assertEqual(desk["referencias"]["T-1001"],
                         {"categoria": "hardware", "prioridad": "alta", "experto": "lucia"})
        self.assertEqual(len(desk["expertos"]), 6)
        self.assertTrue(all(e["atiende"] and e["deriva"] for e in desk["expertos"].values()))
        self.assertEqual(desk["asignados"], {})
        events = self.events(path="/api/tickets/assign")
        results = [data for kind, data in events if kind == "ticket"]
        self.assertEqual([r["id"] for r in results], [t["id"] for t in desk["tickets"]])
        self.assertEqual(events[-1], ("done", 20))
        first = results[0]
        self.assertEqual(first["experto"], desk["categorias"][first["categoria"]["choice"]]["experto"])
        self.assertEqual((first["confianza"], first["semaforo"]), (70.0, "amarillo"))
        self.assertEqual(self.events(path="/api/tickets/assign"), [("done", 20)])  # Nada pendiente.
        self.assertEqual(json.loads(self.get("/api/tickets/reset", "POST")[2])["asignados"], {})

    def test_benchmark_streams_every_ticket_and_a_summary(self):
        events = self.events(path="/api/benchmark/stream?models=laya")
        kinds = [kind for kind, _ in events]
        self.assertEqual(kinds[0], "start")
        self.assertEqual(events[0][1]["suite"], "tickets-v2")
        self.assertEqual(kinds.count("row"), 20)
        self.assertEqual(events[-1], ("done", 1))
        summary = next(data for kind, data in events if kind == "summary")
        self.assertEqual((summary["category_total"], summary["priority_total"], summary["blocking_total"]), (19, 20, 20))
        self.assertEqual(summary["rows"][0]["expected_category"], "hardware")
        self.assertEqual(sum(band["total"] for band in summary["lights"].values()), 19)
        self.assertLessEqual(summary["p50_latency_ms"], summary["p95_latency_ms"])

    def test_benchmark_rejects_api_model_to_preserve_saved_run(self):
        self.model.device = "api"
        try:
            events = self.events(path="/api/benchmark/stream?models=laya")
            self.assertEqual([kind for kind, _ in events], ["failed"])
        finally:
            del self.model.device

    def test_model_cookie_selects_an_independent_app(self):
        models = {"laya": App(FakeModel(), prior=defaultdict(float)),
                  "otro": App(FakeModel(), prior=defaultdict(float))}
        models["laya"].model.device, released = "cuda", []
        models["laya"].model.release = lambda: released.append("laya")
        server = serve(models, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            request = urllib.request.Request(base + "/api/model?name=otro", method="POST")
            with urllib.request.urlopen(request) as response:
                cookie = response.headers["Set-Cookie"].split(";", 1)[0]
            request = urllib.request.Request(base + "/api/status", headers={"Cookie": cookie})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(json.load(response)["selected"], "otro")
            request = urllib.request.Request(base + "/api/city/step", method="POST", headers={"Cookie": cookie})
            urllib.request.urlopen(request).close()
            self.assertEqual(released, ["laya"])
            self.assertEqual(models["otro"].trip.view()["tick"], 1)
            self.assertEqual(models["laya"].trip.view()["tick"], 0)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
