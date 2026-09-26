"""Mismo conjunto de tickets, preguntas y referencias para cada modelo, emitido evento a evento."""
import hashlib
import json
import statistics
import time

from system_one_playground.demos.tickets import PRIORITIES, QUESTIONS as DESK_QUESTIONS, TICKETS, light, ticket_state

SUITE = "tickets-v2"
# Solo en el benchmark: con ella las tres clases de pregunta (choice, score, noul) tienen referencia.
QUESTIONS = {**DESK_QUESTIONS, "bloqueo": {"type": "noul", "instructions":
    "Is at least one person unable to do their essential work right now because of the problem in the `ticket`? "
    "Answer yes only if work is stopped, not merely slower or inconvenient, and no workaround lets them continue."}}
LEVELS = list(PRIORITIES)


def fingerprint():
    """Hash de tickets, preguntas y referencias: dos ejecuciones con el mismo hash midieron lo mismo."""
    data = json.dumps([TICKETS, QUESTIONS], ensure_ascii=False, sort_keys=True, default=list)
    return hashlib.sha256(data.encode()).hexdigest()[:12]


def row(ticket, answers, elapsed_ms):
    category, blocking = answers["categoria"], answers["bloqueo"]["noul"]
    score = answers["prioridad"]["score"]
    confidence = round(100 * category["confidence"], 1)
    expected_category, expected_priority, _ = ticket["referencia"]
    return {"id": ticket["id"], "title": ticket["titulo"],
            "category": category["choice"], "category_confidence": confidence, "light": light(confidence)[0],
            "priority": LEVELS[min(len(LEVELS) - 1, max(0, round(score)))], "priority_score": round(score, 2),
            "blocking": round(blocking, 3),
            "expected_category": expected_category, "expected_priority": expected_priority,
            "expected_blocking": ticket["bloquea"], "latency_ms": round(elapsed_ms, 1)}


def summarize(rows):
    graded = [r for r in rows if r["expected_category"]]
    distance = [abs(LEVELS.index(r["priority"]) - LEVELS.index(r["expected_priority"])) for r in rows]
    latencies = sorted(r["latency_ms"] for r in rows)
    lights = {}
    for color in ("verde", "amarillo", "rojo"):
        band = [r for r in graded if r["light"] == color]
        lights[color] = {"correct": sum(r["category"] == r["expected_category"] for r in band), "total": len(band)}
    return {"category_correct": sum(r["category"] == r["expected_category"] for r in graded),
            "category_total": len(graded),
            "priority_correct": distance.count(0), "priority_near": sum(d <= 1 for d in distance), "priority_total": len(rows),
            "blocking_correct": sum((r["blocking"] >= .5) == r["expected_blocking"] for r in rows), "blocking_total": len(rows),
            "blocking_brier": round(statistics.fmean((r["blocking"] - r["expected_blocking"]) ** 2 for r in rows), 3),
            "lights": lights,
            "mean_latency_ms": round(statistics.fmean(latencies), 1),
            "p50_latency_ms": round(statistics.median(latencies), 1),
            "p95_latency_ms": latencies[min(len(latencies) - 1, round(.95 * (len(latencies) - 1)))]}


def run(models):
    """Genera (evento, datos): «model» al empezar cada modelo, «row» por ticket y «summary» al terminarlo."""
    for key, model in models.items():
        info = {"key": key, "name": getattr(model, "name", key), "checkpoint": getattr(model, "checkpoint", None),
                "calibrated": getattr(model, "calibrated", True)}
        yield "model", {**info, "status": "loading"}
        try:
            spent = getattr(model, "cost", 0.0)
            started = time.perf_counter()
            if hasattr(model, "load"):
                model.load()
            model.predict(ticket_state(TICKETS[0]), QUESTIONS)  # Calentamiento fuera de la medición.
            load_s = round(time.perf_counter() - started, 2)
            yield "model", {**info, "status": "running", "device": getattr(model, "device", None), "load_s": load_s}
            rows = []
            for ticket in TICKETS:
                started = time.perf_counter()
                answers = model.predict(ticket_state(ticket), QUESTIONS)["answers"]
                rows.append(row(ticket, answers, 1000 * (time.perf_counter() - started)))
                yield "row", {"key": key, **rows[-1]}
            cost = getattr(model, "cost", 0.0) - spent
            yield "summary", {**info, **summarize(rows), "device": getattr(model, "device", None), "load_s": load_s,
                              "cost_usd": round(cost, 6) if hasattr(model, "cost") else None, "rows": rows}
        except Exception as exc:
            yield "summary", {**info, "error": f"{type(exc).__name__}: {exc}"}
