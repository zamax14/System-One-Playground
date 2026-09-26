"""Mapa dirigido, reglas de la simulación y el paso de decisión del modelo."""
from collections import deque
from dataclasses import dataclass, field
import math
import random
import time

COLS, ROWS = 6, 5
DIRECTIONS = {"norte": (0, -1), "sur": (0, 1), "oeste": (-1, 0), "este": (1, 0)}
ACTIONS = {**{k: k.capitalize() for k in DIRECTIONS}, "esperar": "Esperar / ALTO",
           "recoger": "Recoger pasajero", "entregar": "Finalizar viaje"}
STREETS = ["Paseo Norte", "Av. del Mercado", "Calle Jardín", "Av. Central", "Paseo Sur"]
HORIZONTAL = {1: "este", 3: "oeste"}
VERTICAL = {2: "sur", 4: "norte"}
LIGHTS = {(2, 1), (3, 3), (4, 2)}
STOPS = {(1, 0), (3, 1), (1, 3)}
QUESTION = {"accion": {"type": "choice",
    "instructions": "Conduce al objetivo. Respeta habilitada, sentidos, ALTO y semáforos. Recoge antes de entregar. Espera solo si debes ceder paso. Usa el historial para evitar ciclos.",
    "criteria": dict(ACTIONS)}}
# Lo que el navegador necesita para dibujar la ciudad; no cambia durante el viaje.
MAP = {"cols": COLS, "rows": ROWS, "actions": ACTIONS, "streets": STREETS,
       "one_way_rows": HORIZONTAL, "one_way_cols": VERTICAL,
       "lights": sorted(LIGHTS), "stops": sorted(STOPS)}


def random_scenario(rng=random):
    """Taxi, pasajero y destino en cruces distintos. El mapa está conectado, así que siempre hay ruta."""
    car, passenger, destination = rng.sample([(x, y) for x in range(COLS) for y in range(ROWS)], 3)
    return {"car": car, "passenger": passenger, "destination": destination, "heading": next(iter(legal_moves(car)))}


def validate_answer(answer):
    probabilities = answer["probabilities"]
    if set(probabilities) != set(ACTIONS):
        raise ValueError("Distribución incompleta de acciones")
    if any(not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values()):
        raise ValueError("Probabilidades inválidas")
    if abs(sum(probabilities.values()) - 1) > .02:
        raise ValueError("La distribución no suma 1")
    if answer["choice"] not in ACTIONS:
        raise ValueError("Acción desconocida")
    confidence = answer["confidence"]
    if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Confianza inválida")
    return answer


def drive(trip, predict):
    """Una decisión: estado → modelo → protección. Si falla, el viaje no cambia."""
    state = trip.snapshot()
    started = time.perf_counter()
    answer = validate_answer(predict(state, QUESTION)["answers"]["accion"])
    return trip.apply(answer["choice"], answer["probabilities"], answer["confidence"],
                      time.perf_counter() - started, state)


def legal_moves(node):
    moves = {}
    for action, (dx, dy) in DIRECTIONS.items():
        neighbor = (node[0] + dx, node[1] + dy)
        if not (0 <= neighbor[0] < COLS and 0 <= neighbor[1] < ROWS):
            continue
        allowed = HORIZONTAL.get(node[1]) if dx else VERTICAL.get(node[0])
        if allowed is None or allowed == action:
            moves[action] = neighbor
    return moves


def route(start, target):
    queue, seen = deque([[start]]), {start}
    while queue:
        path = queue.popleft()
        if path[-1] == target:
            return path
        for node in legal_moves(path[-1]).values():
            if node not in seen:
                seen.add(node)
                queue.append(path + [node])
    raise ValueError("Destino inaccesible")


@dataclass
class Trip:
    car: tuple = (0, 0)
    passenger: tuple = (4, 1)
    destination: tuple = (1, 4)
    onboard: bool = False
    done: bool = False
    tick: int = 0
    stopped: bool = False
    heading: str = "este"
    history: list = field(default_factory=list)

    @property
    def target(self):
        return self.destination if self.onboard else self.passenger

    def green(self, node, action):
        # El tiempo de simulación no avanza mientras el modelo calcula.
        horizontal_green = (self.tick + node[0] + node[1]) % 4 < 2
        return horizontal_green == (action in ("este", "oeste"))

    def options(self):
        moves = legal_moves(self.car)
        distance = len(route(self.car, self.target)) - 1
        options = {}
        for action, (dx, dy) in DIRECTIONS.items():
            node = self.car[0] + dx, self.car[1] + dy
            reason = ""
            if action not in moves:
                reason = "Sentido prohibido" if 0 <= node[0] < COLS and 0 <= node[1] < ROWS else "Sin calle"
            elif self.car == self.target:
                reason = "Atender al pasajero primero"
            elif self.car in STOPS and not self.stopped:
                reason = "ALTO pendiente"
            elif self.car in LIGHTS and not self.green(self.car, action):
                reason = "Semáforo rojo"
            elif len(route(node, self.target)) - 1 >= distance:
                reason = "Protección contra desvíos / ciclos"
            options[action] = {"habilitada": not reason, "motivo": reason or "Ruta hacia objetivo",
                               "hasta": node, "distancia": len(route(node, self.target)) - 1 if action in moves else None}
        can_move = any(v["habilitada"] for v in options.values())
        options["esperar"] = {"habilitada": not can_move and self.car != self.target,
                              "motivo": "Ceder paso / cumplir ALTO" if not can_move else "Hay paso libre"}
        options["recoger"] = {"habilitada": self.car == self.passenger and not self.onboard,
                              "motivo": "Pasajero en este cruce" if self.car == self.passenger and not self.onboard else "Pasajero no disponible aquí"}
        options["entregar"] = {"habilitada": self.car == self.destination and self.onboard,
                               "motivo": "Destino alcanzado" if self.car == self.destination and self.onboard else "Falta llegar con pasajero"}
        return options

    def snapshot(self):
        return {"coordenadas": "x aumenta al este; y aumenta al sur", "posicion": self.car,
                "rumbo": self.heading, "pasajero": self.passenger, "destino": self.destination,
                "a_bordo": self.onboard, "objetivo": self.target, "turno": self.tick,
                "senal": "semaforo" if self.car in LIGHTS else "ALTO" if self.car in STOPS else "libre",
                "semaforo_actual": {axis: "verde" if self.green(self.car, action) else "rojo"
                                    for axis, action in (("N/S", "norte"), ("E/O", "este"))} if self.car in LIGHTS else None,
                "alto_cumplido": self.stopped, "opciones": self.options(),
                "mapa": {"tamano": [COLS, ROWS], "filas_un_sentido": HORIZONTAL,
                         "columnas_un_sentido": VERTICAL, "resto": "doble sentido",
                         "semaforos": sorted(LIGHTS), "stops": sorted(STOPS)},
                "historial": [{"desde": h["from"], "hasta": h["to"], "elegida": h["winner"],
                               "ejecutada": h["executed"]} for h in self.history[-6:]]}

    def view(self):
        """Todo lo que la interfaz dibuja, en tipos que JSON entiende."""
        return {"car": self.car, "heading": self.heading, "passenger": self.passenger,
                "destination": self.destination, "onboard": self.onboard, "done": self.done,
                "tick": self.tick, "stopped": self.stopped, "target": self.target,
                "route": route(self.car, self.target), "options": self.options(),
                "lights": [{"node": node, "ew": self.green(node, "este")} for node in sorted(LIGHTS)],
                "next_state": self.snapshot(), "history": self.history}

    def apply(self, winner, probabilities, confidence, elapsed, state):
        if self.done:
            raise ValueError("Viaje terminado")
        options = self.options()
        if winner not in ACTIONS:
            raise ValueError("Acción desconocida")
        executed = winner if options[winner]["habilitada"] else next(k for k, v in options.items() if v["habilitada"])
        origin = self.car
        if executed in DIRECTIONS:
            self.car = legal_moves(self.car)[executed]
            self.heading, self.stopped = executed, False
        elif executed == "esperar":
            self.stopped = True
        elif executed == "recoger":
            self.onboard = True
        else:
            self.done = True
        self.tick += 1
        record = {"from": origin, "to": self.car, "winner": winner, "executed": executed,
                  "probabilities": dict(probabilities), "confidence": confidence, "elapsed": elapsed,
                  "state": state, "options": options, "step": self.tick}
        self.history.append(record)
        return record
