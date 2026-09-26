"""Modelos por HTTP con el contrato predict(state, questions): Jev y GPT vía OpenRouter.

`normalize` deja cada respuesta con el formato común de preguntas tipadas.
"""
import json
import math
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from fastload import secret

OPENROUTER = "https://openrouter.ai/api/v1"
NO_KEY = "Falta la llave de OpenRouter: define OPENROUTER_API_KEY o crea el archivo «openrouter»"


def post(url, body, key=None, timeout=180):
    """POST JSON; un reintento si el servidor falla (5xx), los 4xx se muestran tal cual."""
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    data = json.dumps(body, ensure_ascii=False).encode()
    for attempt in range(2):
        try:
            with urlopen(Request(url, data=data, headers=headers), timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code < 500 or attempt:
                try:
                    detail = json.load(exc)["error"]["message"]
                except Exception:
                    detail = exc.reason
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
            time.sleep(1)


def _probability(value, what):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{what} fuera de 0–1: {value}")
    return value


def normalize(answers, questions):
    """Respuestas de cualquier modelo → formato común (choice, score, noul, probabilities, confidence)."""
    out = {}
    for qid, q in questions.items():
        a = answers.get(qid)
        if not isinstance(a, dict):
            raise ValueError(f"El modelo no respondió «{qid}»")
        if q["type"] == "noul":
            p = _probability(a["noul"] if "noul" in a else a["probability"], qid)
            out[qid] = {"type": "noul", "noul": p, "confidence": round(max(p, 1 - p), 4)}
            continue
        keys = list(q["criteria"]) if q["type"] == "choice" else [str(i) for i in range(len(q["criteria"]))]
        given = {str(k): v for k, v in (a.get("probabilities") or {}).items()}
        probs = {k: max(0.0, float(given.get(k, 0))) for k in keys}
        stated = str(a.get("choice" if q["type"] == "choice" else "level"))
        if sum(probs.values()) <= 0:  # Sin distribución: toda la masa en lo que dijo.
            if stated not in keys:
                raise ValueError(f"«{qid}» sin probabilidades ni respuesta válida")
            probs = {k: float(k == stated) for k in keys}
        total = sum(probs.values())
        probs = {k: round(v / total, 4) for k, v in probs.items()}
        if q["type"] == "choice":
            pick = stated if stated in keys else max(probs, key=probs.get)
            out[qid] = {"type": "choice", "choice": pick, "probabilities": probs,
                        "confidence": round(float(a.get("confidence", probs[pick])), 4)}
        else:
            expected = sum(i * p for i, p in enumerate(probs.values()))
            score = float(a["score"]) if isinstance(a.get("score"), (int, float)) else expected
            out[qid] = {"type": "score", "score": round(score, 4), "probabilities": probs,
                        "legend": {str(i): c for i, c in enumerate(q["criteria"])},
                        "confidence": round(float(a.get("confidence", max(probs.values()))), 4)}
    return out


class OpenRouterModel:
    """Base de los modelos de pago: sin carga, con la cuenta de llamadas, tokens y costo."""
    device = "api"
    parallel = 8  # El Atlas lanza hasta 8 países a la vez: 176 llamadas en serie tardan minutos.
    calibrated = True

    def __init__(self):
        self.key = secret("OPENROUTER_API_KEY", "openrouter")
        self.status, self.error = ("ready", None) if self.key else ("error", NO_KEY)
        self.calls, self.input_tokens, self.cost = 0, 0, 0.0
        self.lock = threading.Lock()

    def load(self):
        if not self.key:
            raise RuntimeError(NO_KEY)

    def release(self):
        pass

    def count(self, usage):
        usage = usage or {}
        with self.lock:
            self.calls += 1
            self.input_tokens += usage.get("input_tokens") or usage.get("prompt_tokens") or 0
            self.cost += float(usage.get("cost") or 0)

    def usage(self):
        return {"calls": self.calls, "input_tokens": self.input_tokens, "cost_usd": round(self.cost, 6)}


class JevModel(OpenRouterModel):
    """Jev habla System One: OpenRouter lo sirve en /v1/systemone."""
    name = "Jev 1.13"
    checkpoint = "typesafe/jev-1.13"

    def predict(self, state, questions):
        self.load()
        body = post(f"{OPENROUTER}/systemone", {"model": self.checkpoint, "state": state, "questions": questions}, self.key)
        self.count(body.get("usage"))
        return {"model": body.get("model", self.checkpoint), "answers": normalize(body.get("answers") or {}, questions),
                "usage": body.get("usage")}


SYSTEM = """You answer typed decision questions about the `state` you receive. Read the whole state before answering.
- choice: pick exactly one option key and give a probability for every option.
- score: pick the level index on the ordered scale (0 is the first level) and give a probability for every level.
- noul: give the probability, from 0 to 1, that the answer is yes.
Each set of probabilities must add up to 1 and reflect your real uncertainty: go near 1 only when the state leaves no doubt."""


def schema(questions):
    """JSON Schema estricto con una propiedad por pregunta: el modelo no puede salirse de las opciones."""
    def strict(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    props = {}
    for qid, q in questions.items():
        if q["type"] == "noul":
            props[qid] = strict({"probability": {"type": "number"}})
            continue
        keys = list(q["criteria"]) if q["type"] == "choice" else [str(i) for i in range(len(q["criteria"]))]
        pick = "choice" if q["type"] == "choice" else "level"
        props[qid] = strict({pick: {"type": "string", "enum": keys},
                             "probabilities": strict({k: {"type": "number"} for k in keys})})
    return strict(props)


class ChatModel(OpenRouterModel):
    """Un LLM de chat con salida estructurada. Sin logprobs en OpenRouter: la confianza es autodeclarada."""
    calibrated = False

    def __init__(self, model, name, effort="none"):  # Medido: «none» ~1,7 s por ticket, «minimal» ~3,1 s.
        super().__init__()
        self.checkpoint, self.name, self.effort = model, name, effort

    def predict(self, state, questions):
        self.load()
        body = post(f"{OPENROUTER}/chat/completions", {
            "model": self.checkpoint,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps({"state": state, "questions": questions}, ensure_ascii=False)}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "decisions", "strict": True, "schema": schema(questions)}},
            "reasoning": {"effort": self.effort},
            "usage": {"include": True},
        }, self.key)
        self.count(body.get("usage"))
        try:
            answers = json.loads(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise ValueError(f"{self.name} no devolvió JSON válido") from None
        return {"model": body.get("model", self.checkpoint), "answers": normalize(answers, questions), "usage": body.get("usage")}
