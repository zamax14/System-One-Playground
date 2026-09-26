"""Atlas de gastronomía: el modelo puntúa la cocina de cada país por lotes cancelables."""
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import queue
import sys
import threading
import time
from fastload import CHECKPOINT

ASSETS = Path(__file__).resolve().parent / "assets"
BATCH_SIZE = 8
MAX_QUERY = 500
PRIOR_PATH = ASSETS / "gastronomia_prior.json"
QUESTION = "¿Encaja la cocina de este país con lo que se busca: {query}?"
FICHA = ("platos", "ingredientes", "picante", "mar", "carne", "vegetariano", "dulces", "bebidas")
SCALES = {"picante": ("alto", "medio", "bajo"), "mar": ("muy presente", "presente", "poco presente"),
          "vegetariano": ("fácil", "posible", "difícil")}
# Laya dice «sí» a casi todo lo que menciona el tema de la consulta (medido: con «Picante: bajo» en
# todas las fichas, 121 de 176 países salían a 1,00 para «comida picante»). Por eso el texto solo
# nombra un rasgo cuando el país lo tiene de verdad.
SALIENT = {("picante", "alto"): "La comida suele ser muy picante.", ("picante", "medio"): "Algunos platos pican.",
           ("mar", "muy presente"): "El pescado y el marisco son protagonistas.",
           ("vegetariano", "fácil"): "Es fácil comer vegetariano."}
# Consultas variadas para estimar cuánto dice «sí» Laya a cada país sin importar la pregunta.
# No coinciden con las consultas de prueba del README, para no calibrar sobre ellas.
CALIBRATION = ("comida dulce", "sopas y guisos", "comida frita", "pan y cereales", "frutas tropicales", "té",
               "queso y lácteos", "cordero")
DISPLAY_OFFSET = 1.0  # ponytail: desplaza la escala para que lo habitual quede claro en el mapa; ajustable.


def load_fichas():
    fichas = {}
    for line in (ASSETS / "gastronomia.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        fichas[row.pop("id")] = row
    return fichas


def load_countries():
    fichas = load_fichas()
    countries = []
    for feature in json.loads((ASSETS / "world.geojson").read_text())["features"]:
        props, geometry = feature["properties"], feature["geometry"]
        code = props["ADM0_A3"]
        if code == "ATA":
            continue
        if code not in fichas:
            raise ValueError(f"Falta la ficha de {code} en assets/gastronomia.jsonl")
        ficha = dict(fichas[code])
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        countries.append({"id": code, "name": ficha.pop("nombre", None) or props.get("NAME_ES") or props["ADMIN"],
                          "ficha": ficha, "polygons": polygons})
    return sorted(countries, key=lambda c: c["name"])


def country_state(country):
    x = country["ficha"]
    lines = [f"{country['name']}: {x['platos']}.", f"Se cocina con {x['ingredientes']}.",
             x["carne"][0].upper() + x["carne"][1:] + "."]
    lines += [SALIENT[key, x[key]] for key in SCALES if (key, x[key]) in SALIENT]
    lines += [f"De postre, {x['dulces']}.", f"Se bebe {x['bebidas']}."]
    return "\n".join(lines)


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)  # Laya redondea a 4 decimales.
    return math.log(p / (1 - p))


def relative(p, prior):
    """Cuánto más encaja un país que lo habitual en él: sin esto, siempre ganaban los mismos."""
    return 1 / (1 + math.exp(-(logit(p) - prior - DISPLAY_OFFSET)))


def load_prior(countries):
    data = json.loads(PRIOR_PATH.read_text(encoding="utf-8")) if PRIOR_PATH.exists() else {}
    if (data.get("model") != CHECKPOINT or data.get("question") != QUESTION or data.get("queries") != list(CALIBRATION)
            or set(data.get("prior", {})) != {c["id"] for c in countries}):
        raise ValueError("La calibración falta o no coincide con las fichas; ejecuta: python3 atlas.py calibrar")
    return data["prior"]


def calibrate(countries, model):
    prior = {}
    for query in CALIBRATION:
        print(f"  calibrando con «{query}»…", flush=True)
        for country in countries:
            p = extract_scores(model.predict(country_state(country), questions_for([country], query)), [country])
            prior[country["id"]] = prior.get(country["id"], 0) + logit(p[country["id"]]) / len(CALIBRATION)
    PRIOR_PATH.write_text(json.dumps({"model": CHECKPOINT, "question": QUESTION, "queries": list(CALIBRATION),
                                      "prior": {k: round(v, 3) for k, v in sorted(prior.items())}},
                                     ensure_ascii=False, indent=1), encoding="utf-8")


def questions_for(countries, query):
    return {c["id"]: {"type": "noul", "instructions": QUESTION.format(query=query)} for c in countries}


def extract_scores(result, countries):
    scores = {}
    for country in countries:
        value = result["answers"][country["id"]]["noul"]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Puntuación fuera de 0–1")
        scores[country["id"]] = value
    return scores


class Evaluator:
    """Un worker y un barrido a la vez: cada consulta nueva cancela la anterior."""

    def __init__(self, countries, model, prior=None):
        self.countries, self.model = countries, model
        self.prior = prior if prior is not None else load_prior(countries)
        self.requests, self.lock = queue.Queue(), threading.Lock()
        self.cancelled = threading.Event()
        threading.Thread(target=self.run, daemon=True).start()

    def submit(self, query):
        """Devuelve la cola de eventos de esta consulta y su señal de cancelación."""
        with self.lock:
            self.cancelled.set()
            self.cancelled, events = threading.Event(), queue.Queue()
            self.requests.put((query, events, self.cancelled))
            return events, self.cancelled

    def warm(self):
        if hasattr(self.model, "load"):
            self.model.load()

    def run(self):
        while True:
            query, events, cancelled = self.requests.get()
            if cancelled.is_set():
                continue
            started = time.monotonic()
            try:
                self.warm()
                def score(country):
                    raw = extract_scores(self.model.predict(country_state(country), questions_for([country], query)), [country])
                    return country["id"], relative(raw[country["id"]], self.prior[country["id"]])

                # Los modelos por API esperan a la red, no a la GPU: se lanzan varios países a la vez.
                with ThreadPoolExecutor(getattr(self.model, "parallel", 1)) as pool:
                    for start in range(0, len(self.countries), BATCH_SIZE):
                        if cancelled.is_set():
                            break
                        scores = dict(pool.map(score, self.countries[start:start + BATCH_SIZE]))
                        # Se comprueba tras cada lote: nada se publica de una consulta cancelada.
                        if cancelled.is_set():
                            break
                        events.put(("batch", scores))
                    else:
                        events.put(("done", round(time.monotonic() - started, 2)))
            except Exception as exc:
                if not cancelled.is_set():
                    events.put(("failed", f"{type(exc).__name__}: {exc}"))


if __name__ == "__main__" and sys.argv[1:] == ["calibrar"]:
    from fastload import SharedModel
    countries = load_countries()
    calibrate(countries, SharedModel())
    print(f"Guardado {PRIOR_PATH.name} con {len(countries)} países.")
