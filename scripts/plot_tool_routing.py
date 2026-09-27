"""Draw the tool-routing comparison from five completed runs of the same test set."""
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess

from plot_benchmark import chart, COLORS, HEIGHT, WIDTH

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "web" / "results" / "tool-routing"
OUTPUT = ROOT / "assets" / "comparativas" / "laya-ft-jev-luna"
NAMES = {"laya-base": "Laya base · 1k", "laya-ft-1k": "Laya FT · 1k",
         "laya-ft-8k": "Laya FT · 8k", "jev": "Jev", "luna": "Luna"}
COLORS.update({"laya-base": "#4fa8f0", "laya-ft-1k": "#2fbf94",
               "laya-ft-8k": "#7757e4", "luna": "#d9376e"})


def runs():
    raw = all((RESULTS / f"{key}.json").exists() for key in NAMES)
    if raw:
        loaded = []
        for key, name in NAMES.items():
            run = json.loads((RESULTS / f"{key}.json").read_text(encoding="utf-8"))
            if run["status"] != "complete" or len(run["rows"]) != 120:
                raise ValueError(f"Corrida incompleta: {key}")
            tool_set = sum(all(row["answers"][qid]["predicted"] == row["answers"][qid]["expected"]
                               for qid in ("web_search", "calendar", "email", "files", "database"))
                           for row in run["rows"])
            loaded.append({key_: run[key_] for key_ in ("checkpoint", "context_size", "device", "task",
                                                         "fingerprint", "test_sha256", "created_at", "status",
                                                         "all_correct", "total", "p50_latency_ms", "p95_latency_ms",
                                                         "cost_usd")}
                          | {"key": key, "name": name, "weights_sha256": run.get("weights_sha256"),
                             "action_correct": run["questions"]["action"]["correct"],
                             "tool_set_correct": tool_set})
    else:
        loaded = json.loads((OUTPUT / "resultados.json").read_text(encoding="utf-8"))
    if [r["key"] for r in loaded] != list(NAMES) or any(r["status"] != "complete" or r["total"] != 120 for r in loaded):
        raise ValueError("Faltan corridas completas para los cinco modelos")
    if len({(r["task"], r["fingerprint"], r["test_sha256"]) for r in loaded}) != 1:
        raise ValueError("Las corridas no usan la misma prueba")
    return loaded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png", action="store_true")
    args = parser.parse_args()
    measured = runs()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "resultados.json").write_text(json.dumps(measured, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    footer = "120 solicitudes de prueba · rutas de herramientas · Datzin"
    cost_max = math.ceil(max(r["cost_usd"] or 0 for r in measured) / .01) * .01
    cost_ticks = [i * .01 for i in range(round(cost_max / .01) + 1)]

    def accuracy(run):
        return [100 * run["all_correct"] / 120,
                100 * run["action_correct"] / 120,
                100 * run["tool_set_correct"] / 120]

    charts = {
        "acierto": chart("Decisiones sobre herramientas", "Prueba original de 120 solicitudes · Jev y Luna guardados",
                         ["Decisión completa", "Acción", "Herramientas"], measured,
                         accuracy, lambda r, i: f"{accuracy(r)[i]:.0f} %",
                         [0, 20, 40, 60, 80, 100], lambda v: f"{v:.0f} %", footer),
        "latencia": chart("Tiempo por decisión", "Laya en GPU local; Jev y Luna incluyen la red",
                          ["p50", "p95"], measured,
                          lambda r: [r["p50_latency_ms"], r["p95_latency_ms"]],
                          lambda r, i: f'{[r["p50_latency_ms"], r["p95_latency_ms"]][i]:.0f} ms',
                          [0, 600, 1200, 1800, 2400, 3000], lambda v: f"{v:.0f} ms", footer),
        "costo": chart("Costo de API", "120 solicitudes por modelo; Laya local no consume API",
                       ["Corrida completa"], measured,
                       lambda r: [r["cost_usd"] or 0],
                       lambda r, i: "$0" if r["cost_usd"] is None else f'${r["cost_usd"]:.4f}',
                       cost_ticks, lambda v: f"${v:.3f}", footer),
    }
    for name, svg in charts.items():
        path = OUTPUT / f"{name}.svg"
        path.write_text(svg, encoding="utf-8")
        print(path.relative_to(ROOT))
        if args.png:
            chrome = shutil.which("google-chrome")
            if not chrome:
                raise RuntimeError("Falta google-chrome para exportar PNG")
            png = path.with_suffix(".png")
            subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=2", f"--window-size={WIDTH},{HEIGHT}",
                            f"--screenshot={png}", path.as_uri()], check=True, capture_output=True)
            print(png.relative_to(ROOT))


if __name__ == "__main__":
    main()
