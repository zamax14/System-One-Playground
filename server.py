"""Servidor local de Pondera: sirve web/ y pone los modelos detrás de una API pequeña.

    python server.py            # abre http://127.0.0.1:8000
    python server.py --port 9000 --no-browser
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from http.cookies import SimpleCookie
import json
import mimetypes
import queue
import signal
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import benchmark
from atlas import MAX_QUERY, Evaluator, country_state, load_countries
from city import MAP, Trip, drive, random_scenario
import courses
import tickets
import tools

WEB = Path(__file__).resolve().parent / "web"
PAGES = {"/": "index.html", "/atlas": "atlas.html", "/city": "city.html", "/tickets": "tickets.html",
         "/courses": "courses.html", "/tools": "tools.html", "/benchmark": "benchmark.html"}
KEEPALIVE = 15  # s sin eventos antes de un ping; así se detecta una pestaña cerrada.


class App:
    """Estado compartido por todas las peticiones: un modelo, un barrido y un viaje."""

    def __init__(self, model, prior=None):
        self.model = model
        countries = load_countries()
        self.atlas = Evaluator(countries, model, prior)
        # Se serializa una vez: la geometría pesa ~1 MB y no cambia. «texto» es lo que lee el modelo.
        self.countries = json.dumps(
            [{"id": c["id"], "name": c["name"], "texto": country_state(c), "polygons": c["polygons"]} for c in countries],
            ensure_ascii=False, separators=(",", ":")).encode()
        self.assigned, self.assigning = {}, threading.Lock()  # Mesa de ayuda: resultados por ticket.
        self.scenario = {}  # Vacío: el viaje por defecto de Trip.
        self.trip, self.trip_lock = Trip(), threading.Lock()
        self.roadmap, self.roadmap_lock = courses.Roadmap(), threading.Lock()
        self.route, self.route_lock = tools.Route(), threading.Lock()

    def status(self):
        usage = self.model.usage() if hasattr(self.model, "usage") else None
        return {"model": getattr(self.model, "status", "ready"), "error": getattr(self.model, "error", None),
                "device": getattr(self.model, "device", None), "usage": usage}

    def step(self):
        with self.trip_lock:
            if self.trip.done:
                raise LookupError("El viaje terminó; reinícialo para empezar otro.")
            return {"record": drive(self.trip, self.model.predict), "view": self.trip.view()}

    def reset(self):
        """Repite el escenario actual desde el principio."""
        with self.trip_lock:
            self.trip = Trip(**self.scenario)
            return self.city()

    def shuffle(self):
        with self.trip_lock:
            self.scenario = random_scenario()
            self.trip = Trip(**self.scenario)
            return self.city()

    def city(self):
        return {"map": MAP, "view": self.trip.view()}

    def courses(self):
        return {"cursos": [courses.public(c) for c in courses.COURSES], "objetivos": courses.GOALS,
                "perfiles": courses.PROFILES, "habilidades": courses.SKILLS, "view": self.roadmap.view()}

    def course_step(self):
        with self.roadmap_lock:
            return {"record": self.roadmap.step(self.model.predict), "view": self.roadmap.view()}

    def course_reset(self, query):
        """Empieza otra ruta; sin parámetros repite el objetivo y el perfil actuales."""
        with self.roadmap_lock:
            goal = query.get("objetivo", [self.roadmap.goal])[0]
            profile = query.get("perfil", [self.roadmap.profile])[0]
            try:
                self.roadmap = courses.Roadmap(goal, profile)
            except ValueError as exc:
                raise LookupError(str(exc))
            return {"view": self.roadmap.view()}

    def toolbox(self):
        return {"servidores": tools.servers(), "herramientas": tools.catalog(),
                "ejemplos": [tools.public(e) for e in tools.EXAMPLES], "view": self.route.view()}

    def route_step(self):
        with self.route_lock:
            return {"record": self.route.turn(self.model.predict), "view": self.route.view()}

    def route_reset(self, query):
        with self.route_lock:
            try:
                self.route = tools.Route(query.get("q", [""])[0])
            except ValueError as exc:
                raise LookupError(str(exc))
            return {"view": self.route.view()}

    def desk(self):
        return {"tickets": [tickets.public(t) for t in tickets.TICKETS],
                "referencias": {t["id"]: {"categoria": t["referencia"][0], "prioridad": t["referencia"][1],
                                          "experto": t["referencia"][2]} for t in tickets.TICKETS},
                "categorias": {k: {"nombre": name, "experto": owner} for k, (name, owner, _) in tickets.CATEGORIES.items()},
                "prioridades": {k: name for k, (name, _) in tickets.PRIORITIES.items()},
                "expertos": {k: {"nombre": name, "rol": role, **tickets.EXPERT_DETAILS[k]}
                             for k, (name, role) in tickets.EXPERTS.items()},
                "semaforos": tickets.LIGHTS, "asignados": self.assigned}

    def reset_desk(self):
        if not self.assigning.acquire(blocking=False):
            raise LookupError("El modelo está asignando tickets; espera a que termine.")
        try:
            self.assigned.clear()
            return self.desk()
        finally:
            self.assigning.release()


def warm_model(model):
    try:
        model.load()
    except Exception:
        pass  # /api/status comunica el error y cómo resolverlo.


def free_gpu(apps, keep):
    """Libera otros modelos locales antes de cargar uno en la GPU."""
    for key, app in apps.items():
        if key != keep and getattr(app.model, "device", None) == "cuda" and hasattr(app.model, "release"):
            app.model.release()


def describe(apps):
    return {key: {"name": getattr(app.model, "name", key.title()), "remote": getattr(app.model, "device", None) == "api",
                  "calibrated": getattr(app.model, "calibrated", True),
                  "status": getattr(app.model, "status", "ready"), "error": getattr(app.model, "error", None)}
            for key, app in apps.items()}


def handler_for(apps):
    if isinstance(apps, App):
        apps = {"laya": apps}
    benchmarking = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # La consola queda para errores reales.
            pass

        def selected(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except Exception:
                return next(iter(apps))
            key = cookie.get("arbiter_model")
            return key.value if key and key.value in apps else next(iter(apps))

        def current_app(self):
            return apps[self.selected()]

        def send_bytes(self, body, content_type, status=HTTPStatus.OK, headers=()):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            for key, value in headers:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, payload, status=HTTPStatus.OK, headers=()):
            self.send_bytes(json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8", status, headers)

        def do_GET(self):
            url = urlparse(self.path)
            app = self.current_app()
            routes = {"/api/status": lambda: self.send_json({**app.status(), "selected": self.selected(), "models": describe(apps),
                                                              "benchmark": {"suite": benchmark.SUITE, "fingerprint": benchmark.fingerprint()}}),
                      "/api/benchmark/stream": lambda: self.stream_benchmark(parse_qs(url.query).get("models", [""])[0]),
                      "/api/atlas/countries": lambda: self.send_bytes(app.countries, "application/json; charset=utf-8"),
                      "/api/atlas/query": lambda: self.stream_query(parse_qs(url.query).get("q", [""])[0]),
                      "/api/city": lambda: self.send_json(app.city()),
                      "/api/courses": lambda: self.send_json(app.courses()),
                      "/api/tools": lambda: self.send_json(app.toolbox()),
                      "/api/tickets": lambda: self.send_json(app.desk()),
                      "/api/tickets/assign": self.stream_assign}
            if url.path in routes:
                return routes[url.path]()
            self.send_static(PAGES.get(url.path, url.path.lstrip("/")))

        def do_POST(self):
            url = urlparse(self.path)
            if url.path == "/api/model":
                key = parse_qs(url.query).get("name", [""])[0]
                if key not in apps:
                    return self.send_json({"error": "Modelo desconocido"}, HTTPStatus.BAD_REQUEST)
                model = apps[key].model
                if getattr(model, "device", None) != "api":
                    free_gpu(apps, key)
                if hasattr(model, "load") and getattr(model, "status", "ready") in ("idle", "error"):
                    threading.Thread(target=warm_model, args=(model,), daemon=True).start()
                return self.send_json({"selected": key}, headers=(("Set-Cookie", f"arbiter_model={key}; Path=/; SameSite=Lax; HttpOnly"),))
            app = self.current_app()
            actions = {"/api/city/step": app.step, "/api/city/reset": app.reset, "/api/city/shuffle": app.shuffle,
                       "/api/tickets/reset": app.reset_desk, "/api/courses/step": app.course_step,
                       "/api/courses/reset": lambda: app.course_reset(parse_qs(url.query)),
                       "/api/tools/step": app.route_step,
                       "/api/tools/reset": lambda: app.route_reset(parse_qs(url.query))}
            action = actions.get(url.path)
            if action is None:
                return self.send_json({"error": "Ruta desconocida"}, HTTPStatus.NOT_FOUND)
            try:
                self.send_json(action())
            except LookupError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            except Exception as exc:  # Si falla el modelo, el viaje no se mueve y la interfaz lo dice.
                self.send_json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def send_static(self, relative):
            path = (WEB / relative).resolve()
            if not path.is_relative_to(WEB) or not path.is_file():
                return self.send_json({"error": "No encontrado"}, HTTPStatus.NOT_FOUND)
            kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if kind.startswith("text/") or kind.endswith("javascript"):
                kind += "; charset=utf-8"
            self.send_bytes(path.read_bytes(), kind)

        def stream_query(self, query):
            app = self.current_app()
            query = query.strip()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if not query or len(query) > MAX_QUERY:
                # Se responde como evento para que la página muestre el motivo.
                return self.write_event("failed", f"Escribe una idea de 1 a {MAX_QUERY} caracteres.")
            events, cancelled = app.atlas.submit(query)
            try:
                while True:
                    try:
                        kind, data = events.get(timeout=KEEPALIVE)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    self.write_event(kind, data)
                    if kind in ("done", "failed"):
                        return
            except (BrokenPipeError, ConnectionResetError):
                pass  # La pestaña cerró o lanzó otra consulta.
            finally:
                cancelled.set()

        def stream_assign(self):
            """Asigna los tickets pendientes uno a uno y emite cada resultado en cuanto sale."""
            app = self.current_app()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if not app.assigning.acquire(blocking=False):
                return self.write_event("failed", "Ya hay una asignación en curso en otra pestaña.")
            try:
                for ticket in tickets.TICKETS:
                    if ticket["id"] in app.assigned:
                        continue
                    started = time.perf_counter()
                    result = tickets.assign(ticket, app.model.predict)
                    result["segundos"] = round(time.perf_counter() - started, 2)
                    app.assigned[ticket["id"]] = result
                    self.write_event("ticket", result)
                self.write_event("done", len(app.assigned))
            except (BrokenPipeError, ConnectionResetError):
                pass  # La pestaña se cerró: lo asignado hasta aquí se conserva.
            except Exception as exc:
                self.write_event("failed", f"{type(exc).__name__}: {exc}")
            finally:
                app.assigning.release()

        def stream_benchmark(self, requested):
            """Corre los modelos pedidos uno tras otro y emite cada ticket en cuanto sale."""
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            keys = requested.split(",") if requested else [k for k, item in apps.items() if getattr(item.model, "device", None) != "api"]
            if not keys or any(k not in apps or getattr(apps[k].model, "device", None) == "api" for k in keys):
                return self.write_event("failed", "El benchmark por API se carga desde la corrida guardada; aquí solo se mide el modelo local.")
            if not benchmarking.acquire(blocking=False):
                return self.write_event("failed", "Ya hay un benchmark en curso en otra pestaña.")
            try:
                self.write_event("start", {"suite": benchmark.SUITE, "fingerprint": benchmark.fingerprint(),
                                           "created_at": datetime.now(timezone.utc).isoformat(), "models": keys})
                for key in keys:
                    if getattr(apps[key].model, "device", None) != "api":
                        free_gpu(apps, key)
                    for kind, data in benchmark.run({key: apps[key].model}):
                        self.write_event(kind, data)
                self.write_event("done", len(keys))
            except (BrokenPipeError, ConnectionResetError):
                pass  # La pestaña canceló: el generador se abandona y no hay más llamadas.
            finally:
                benchmarking.release()

        def write_event(self, kind, data):
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            self.wfile.write(f"event: {kind}\ndata: {payload}\n\n".encode())
            self.wfile.flush()

    return Handler


def serve(apps, port=8000, host="127.0.0.1"):
    server = ThreadingHTTPServer((host, port), handler_for(apps))
    server.daemon_threads = True
    return server


def warm(app):
    started = time.monotonic()
    try:
        app.atlas.warm()
    except Exception as exc:  # La página también lo muestra en el indicador del modelo.
        print(f"Laya no cargó: {type(exc).__name__}: {exc}", flush=True)
        return
    print(f"Laya lista en {app.model.device.upper()} en {time.monotonic() - started:.1f} s", flush=True)


def build_apps(device="auto", remote_only=False):
    from remote import ChatModel, JevModel
    apps = {}
    if not remote_only:
        from fastload import SharedModel
        apps["laya"] = App(SharedModel(device=device))
    apps["jev"] = App(JevModel(), prior=defaultdict(float))
    apps["gpt-luna"] = App(ChatModel("openai/gpt-5.6-luna", "GPT-5.6 Luna"), prior=defaultdict(float))
    return apps


def main():
    parser = argparse.ArgumentParser(description="Pondera: benchmark de decisiones sobre texto")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    parser.add_argument("--remote-only", action="store_true", help="solo Jev y Luna; no requiere instalar Laya ni PyTorch")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto",
                        help="dónde corre Laya; auto usa la GPU si torch la ve")
    args = parser.parse_args()
    # Solo Laya tiene calibración por país en el Atlas; los demás parten de cero.
    apps = build_apps(args.device, args.remote_only)
    try:
        server = serve(apps, args.port)
    except OSError as exc:
        raise SystemExit(f"No se pudo abrir el puerto {args.port} ({exc.strerror}); prueba con --port 8001")
    # SIGTERM (kill, systemd, cerrar la terminal) sale como Ctrl+C y libera los recursos.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Pondera en {url} (Ctrl+C para salir)", flush=True)
    if "laya" in apps:
        threading.Thread(target=warm, args=(apps["laya"],), daemon=True).start()
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
