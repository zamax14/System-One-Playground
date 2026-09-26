"""Benchmark de contexto largo: los 20 tickets del benchmark al principio de hilos de correo de 1k a 8k tokens.

    .venv/bin/python scripts/benchmark_largo.py                            # todos los modelos y longitudes
    .venv/bin/python scripts/benchmark_largo.py --modelos laya jev         # solo algunos

Cada ticket se deja igual y detrás se añade «Historial del hilo y adjuntos»: bloques de texto de oficina sin ningún
problema de TI (actas, avisos de RRHH, firmas legales…), hasta la longitud pedida en tokens de Laya. La respuesta
correcta no cambia; lo que se mide es si el modelo la sigue encontrando.

- El ruido se genera una vez con GPT (OpenRouter u OpenAI) y queda en assets/benchmark/ruido.json.
- Los resultados van a web/results/largo.json, que se reanuda si la corrida se corta.
- Las gráficas, barras de Laya base frente a la reentrenada, van a assets/benchmark/largo-*.svg.
"""
import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fastload  # noqa: E402  Antes que torch.

import benchmark  # noqa: E402
from remote import OPENROUTER, ChatModel, JevModel, post  # noqa: E402
from tickets import TICKETS, ticket_state  # noqa: E402

NOISE = ROOT / "assets" / "benchmark" / "ruido.json"
RESULTS = ROOT / "web" / "results" / "largo.json"
CHARTS = ROOT / "assets" / "benchmark"
SEED = 20260924
# Tokens de Laya del estado. 7600 deja sitio a la pregunta y sus opciones (hasta 256) dentro de 8192.
LENGTHS = {"original": None, "1k": 1024, "2k": 2048, "4k": 4096, "8k": 7600}
FINETUNED = ROOT / ".model-cache" / "laya-mesa-de-ayuda"
COLORS = {"laya": "#4fa8f0", "laya-mesa": "#2fbf94", "jev": "#ff8e3c", "gpt-luna": "#d9376e"}
# Si un bloque de ruido habla de tecnología podría cambiar la respuesta correcta: se descarta.
TECH_WORDS = ("computador", "ordenador", "portátil", "laptop", "software", "internet", "wifi", "wi-fi", "vpn", "red ",
              "contraseña", "impresora", "sistema", "servidor", "virus", "phishing", "aplicación", "app ", "teams",
              "outlook", "correo electrónico", "usuario", "acceso", "licencia", "pantalla", "equipo de cómputo", "erp",
              "crm", "soporte", "ti ", "informática", "ciberseguridad", "enlace", "archivo", "carpeta", "clave")
NOISE_KINDS = ["actas de reuniones de áreas de negocio", "avisos y circulares de Recursos Humanos",
               "firmas corporativas y avisos legales de confidencialidad al pie de correos",
               "mensajes anteriores del hilo sobre organizar un evento, un viaje o una comida de equipo",
               "resúmenes de ventas, indicadores y metas del trimestre", "políticas de viáticos, vacaciones y horarios"]


NOISE_SCHEMA = {"type": "object", "properties": {"bloques": {"type": "array", "items": {"type": "string"}}},
                "required": ["bloques"], "additionalProperties": False}


def generate_noise():
    """Unos 60 bloques de 150 a 250 palabras; basta con unos 12k tokens distintos para rellenar hasta 8k."""
    key = fastload.secret("OPENROUTER_API_KEY", "openrouter")
    url, model, extra = f"{OPENROUTER}/chat/completions", "openai/gpt-5.6-luna", {"reasoning": {"effort": "low"}}
    if not key:
        key, url, model, extra = (fastload.secret("OPENAI_API_KEY", "OPENAI"), "https://api.openai.com/v1/chat/completions",
                                  "gpt-6-luna", {"reasoning_effort": "low"})
    blocks = []
    for kind in NOISE_KINDS:
        prompt = (f"Escribe 12 bloques de texto distintos, en español, de 150 a 250 palabras cada uno: {kind} de una "
                  "empresa mediana. Deben sonar reales, con nombres, fechas y cifras. No menciones tecnología de ningún "
                  "tipo: nada de computadoras, programas, redes, internet, correo que falla, contraseñas, cuentas de "
                  "usuario, impresoras, pantallas, archivos, seguridad informática ni soporte técnico.")
        body = post(url, {"model": model, "messages": [{"role": "user", "content": prompt}],
                          "response_format": {"type": "json_schema", "json_schema": {
                              "name": "ruido", "strict": True, "schema": NOISE_SCHEMA}}, **extra}, key)
        found = json.loads(body["choices"][0]["message"]["content"])["bloques"]
        if not isinstance(found, list) or any(not isinstance(b, str) for b in found):
            raise ValueError("La respuesta de ruido debe contener una lista de textos")
        blocks += [b.strip() for b in found if not any(w in b.lower() for w in TECH_WORDS)]
        print(f"ruido: {kind}: {len(found)} bloques, {len(blocks)} válidos en total", flush=True)
    NOISE.parent.mkdir(parents=True, exist_ok=True)
    NOISE.write_text(json.dumps({"modelo": model, "bloques": blocks}, ensure_ascii=False, indent=1), encoding="utf-8")
    return blocks


def tokenizer():
    """El tokenizador de Laya sin cargar el modelo: las longitudes se miden en sus tokens para todos los modelos."""
    from huggingface_hub import snapshot_download
    from laya.agent import _fix_tokenizer_config
    from transformers import AutoTokenizer
    repo, revision = fastload.CHECKPOINT.split("@")
    path = snapshot_download(repo, revision=revision, allow_patterns=["tokenizer/*", "rl_agent_config.json"])
    _fix_tokenizer_config(path)
    return AutoTokenizer.from_pretrained(str(Path(path) / "tokenizer"))


def long_state(ticket, target, blocks, count):
    """El ticket igual y detrás bloques de ruido en un orden fijo por ticket, sin pasar de target tokens."""
    base = ticket_state(ticket)["ticket"]
    if target is None:
        return {"ticket": base}
    text = base + "\n\nHistorial del hilo y adjuntos:"
    for block in random.Random(f"{SEED}-{ticket['id']}").sample(blocks, len(blocks)):
        candidate = f"{text}\n\n{block}"
        if count(candidate) > target:
            break
        text = candidate
    return {"ticket": text}


def models(keys):
    out = {}
    for key in keys:
        if key == "laya":
            out[key] = fastload.SharedModel()
        elif key == "laya-mesa":
            if not (FINETUNED / "rl_agent_config.json").exists():
                print(f"Sin {FINETUNED.relative_to(ROOT)}: se omite la Laya ajustada")
                continue
            out[key] = fastload.SharedModel(path=FINETUNED, name="Laya reentrenada")
        elif key == "jev":
            out[key] = JevModel()
        else:
            out[key] = ChatModel("openai/gpt-5.6-luna", "GPT-5.6 Luna")
    return out


def save(data):
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporary.replace(RESULTS)


def run(selected, suite):
    data = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    if data.get("fingerprint") != suite["fingerprint"]:
        data = {"suite": "tickets-v2-largo", "fingerprint": suite["fingerprint"], "tokens": suite["tokens"], "models": {}}
    for key, model in selected.items():
        entry = data["models"].setdefault(key, {"name": model.name, "checkpoint": getattr(model, "checkpoint", None),
                                                "calibrated": getattr(model, "calibrated", True), "lengths": {}})
        spent = getattr(model, "cost", 0.0)
        for length in LENGTHS:
            done = entry["lengths"].setdefault(length, {"rows": []})
            if "summary" in done:
                continue
            if not done["rows"]:
                model.predict(suite["states"][length][0], benchmark.QUESTIONS)  # Calentamiento con esa longitud.
            seen = {r["id"] for r in done["rows"]}
            for ticket, state in zip(TICKETS, suite["states"][length]):
                if ticket["id"] in seen:
                    continue
                started = time.perf_counter()
                try:
                    answers = model.predict(state, benchmark.QUESTIONS)["answers"]
                except Exception as exc:
                    done["error"] = f"{type(exc).__name__}: {exc}"
                    print(f"{model.name} · {length}: {done['error']}", flush=True)
                    break
                done["rows"].append(benchmark.row(ticket, answers, 1000 * (time.perf_counter() - started)))
                save(data)
            if len(done["rows"]) == len(TICKETS):
                done["summary"] = benchmark.summarize(done["rows"])
                done.pop("error", None)
                s = done["summary"]
                print(f"{model.name:22} {length:8} categoría {s['category_correct']}/{s['category_total']} · prioridad "
                      f"{s['priority_correct']}/20 · bloqueo {s['blocking_correct']}/20 · p50 {s['p50_latency_ms']:.0f} ms",
                      flush=True)
            entry["device"] = getattr(model, "device", None)
            if hasattr(model, "cost"):
                entry["cost_usd"] = round(entry.get("cost_usd", 0) + model.cost - spent, 6)
                spent = model.cost
            save(data)
        if hasattr(model, "release"):
            model.release()  # Libera la GPU para el siguiente modelo local.
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(data)
    return data


# ---------------------------------------------------------------- Gráficas, con el estilo de scripts/plot_benchmark.py

WIDTH, HEIGHT, LEFT, RIGHT, TOP, BOTTOM = 880, 440, 72, 840, 126, 354
INK, GRID, MUTED = "#0d0d0d", "#d4d5d9", "#696969"


def text(x, y, label, *, size=12, color=INK, weight=400, anchor="start"):
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Nunito,system-ui,sans-serif" '
            f'font-size="{size}" font-weight="{weight}" fill="{color}">{escape(str(label))}</text>')


def bar_chart(path, title, subtitle, data, value, label, y_max, y_label, footer, keys=("laya", "laya-mesa")):
    """Barras agrupadas por longitud: Laya base frente a la reentrenada, con el valor encima de cada barra."""
    runs = [(key, data["models"][key]) for key in keys if key in data["models"]]
    lengths = list(LENGTHS)
    y = lambda v: BOTTOM - v / y_max * (BOTTOM - TOP)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" '
             f'role="img" aria-label="{escape(title)}">',
             f'<rect x="4" y="4" width="875" height="435" rx="12" fill="{INK}"/>',
             f'<rect x="1" y="1" width="875" height="435" rx="12" fill="white" stroke="{INK}" stroke-width="2"/>',
             text(24, 36, title, size=20, weight=700), text(24, 57, subtitle, size=12, color=MUTED)]
    for i, (key, entry) in enumerate(runs):
        parts += [f'<rect x="{72 + i * 230}" y="74" width="15" height="15" rx="3" fill="{COLORS[key]}" stroke="{INK}" stroke-width="2"/>',
                  text(72 + i * 230 + 23, 87, entry["name"], size=12, weight=700)]
    for tick in range(5):
        v = y_max * tick / 4
        dash = "" if tick == 0 else ' stroke-dasharray="3 4"'
        parts += [f'<line x1="{LEFT}" x2="{RIGHT}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{GRID}"{dash}/>',
                  text(LEFT - 10, y(v) + 4, y_label(v), color=MUTED, anchor="end")]
    group = (RIGHT - LEFT) / len(lengths)
    bar = min(group * .72, 150) / len(runs)
    for g, length in enumerate(lengths):
        center = LEFT + group * (g + .5)
        parts += [text(center, BOTTOM + 24, length, weight=700, anchor="middle"),
                  text(center, BOTTOM + 40, f"~{data['tokens'][length]:,} tokens".replace(",", "."), size=11,
                       color=MUTED, anchor="middle")]
        for i, (key, entry) in enumerate(runs):
            summary = entry["lengths"].get(length, {}).get("summary")
            if not summary:
                continue
            v, x = value(summary), center - bar * len(runs) / 2 + i * bar
            parts += [f'<rect x="{x + 2:.1f}" y="{y(v):.1f}" width="{bar - 4:.1f}" height="{BOTTOM - y(v):.1f}" rx="4" '
                      f'fill="{COLORS[key]}" stroke="{INK}" stroke-width="2"/>',
                      text(x + bar / 2, y(v) - 7, label(v), size=11, weight=700, anchor="middle")]
    parts += [text(24, 418, footer, size=11, color=MUTED), "</svg>"]
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def charts(data):
    footer = f"tickets-v2-largo · huella {data['fingerprint']} · {data.get('updated_at', '')[:10]}"
    pct, where = (lambda v: f"{v:.0f} %"), "con el ticket al inicio de un hilo de correo de hasta 8k tokens"
    for name, title, subtitle, value in [
            ("categoria", "Categoría según la longitud del contexto", f"Porcentaje correcto en 19 tickets, {where}",
             lambda s: 100 * s["category_correct"] / s["category_total"]),
            ("prioridad", "Prioridad exacta según la longitud del contexto", f"Porcentaje correcto en 20 tickets, {where}",
             lambda s: 100 * s["priority_correct"] / s["priority_total"]),
            ("bloqueo", "Bloqueo según la longitud del contexto", f"Porcentaje correcto en 20 tickets, {where}",
             lambda s: 100 * s["blocking_correct"] / s["blocking_total"])]:
        bar_chart(CHARTS / f"largo-{name}.svg", title, subtitle, data, value, pct, 100, pct, footer)
    worst = max(s["summary"]["p50_latency_ms"] for k in ("laya", "laya-mesa") if k in data["models"]
                for s in data["models"][k]["lengths"].values() if "summary" in s)
    step = 10 ** len(str(int(worst))) / 10
    bar_chart(CHARTS / "largo-latencia.svg", "Latencia según la longitud del contexto",
              "Mediana por ticket (tres preguntas) en una RTX 4070 Ti SUPER", data, lambda s: s["p50_latency_ms"],
              lambda v: f"{v:.0f} ms", step * (-(-worst // step)), lambda v: f"{v:.0f} ms", footer)


def main():
    parser = argparse.ArgumentParser(description="Benchmark de contexto largo de 1k a 8k tokens")
    parser.add_argument("--modelos", nargs="+", choices=list(COLORS), default=list(COLORS))
    args = parser.parse_args()
    blocks = (json.loads(NOISE.read_text(encoding="utf-8"))["bloques"] if NOISE.exists() else generate_noise())
    tok = tokenizer()
    count = lambda text: len(tok(text)["input_ids"])
    states = {length: [long_state(t, target, blocks, count) for t in TICKETS] for length, target in LENGTHS.items()}
    tokens = {length: round(sum(count(s["ticket"]) for s in ss) / len(ss)) for length, ss in states.items()}
    print("Tokens medios del estado por longitud:", tokens, flush=True)
    fingerprint = f"{benchmark.fingerprint()}-{len(blocks)}"
    data = run(models(args.modelos), {"states": states, "tokens": tokens, "fingerprint": fingerprint})
    charts(data)
    print(f"Resultados en {RESULTS.relative_to(ROOT)} y gráficas en {CHARTS.relative_to(ROOT)}/largo-*.svg")


if __name__ == "__main__":
    main()
