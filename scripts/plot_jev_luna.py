"""Exporta tres gráficas Jev vs Luna listas para compartir."""

import json
from pathlib import Path
import shutil
import subprocess

from plot_benchmark import ROOT, RESULTS, chart


def main():
    runs = [json.loads((RESULTS / f"{key}.json").read_text(encoding="utf-8"))
            for key in ("jev", "gpt-luna")]
    if any(r["status"] != "complete" or len(r["rows"]) != 20 or r["calls"] != 21 for r in runs):
        raise ValueError("Se necesitan dos corridas completas de 20 tickets y 21 llamadas")
    if len({(r["suite"], r["fingerprint"]) for r in runs}) != 1:
        raise ValueError("Jev y Luna no comparten la misma suite y huella")

    out = ROOT / "assets" / "linkedin"
    out.mkdir(parents=True, exist_ok=True)
    footer = "Una prueba de Datzin · 20 tickets · septiembre de 2026"
    charts = {
        "acierto": chart(
            "Jev vs Luna · acierto", "¿Cuántas respuestas coincidieron con la referencia?",
            ["Categoría", "Prioridad exacta", "Bloqueo"], runs,
            lambda r: [100 * r["category_correct"] / r["category_total"],
                       100 * r["priority_correct"] / r["priority_total"],
                       100 * r["blocking_correct"] / r["blocking_total"]],
            lambda r, i: [f'{r["category_correct"]}/{r["category_total"]}',
                          f'{r["priority_correct"]}/{r["priority_total"]}',
                          f'{r["blocking_correct"]}/{r["blocking_total"]}'][i],
            [0, 20, 40, 60, 80, 100], lambda v: f"{v:.0f} %", footer),
        "latencia": chart(
            "Jev vs Luna · tiempo de respuesta", "Milisegundos por ticket, incluida la conexión",
            ["Habitual", "Promedio", "Más lento"], runs,
            lambda r: [r["p50_latency_ms"], r["mean_latency_ms"], r["p95_latency_ms"]],
            lambda r, i: f'{[r["p50_latency_ms"], r["mean_latency_ms"], r["p95_latency_ms"]][i]:.0f} ms',
            [0, 600, 1200, 1800, 2400, 3000], lambda v: f"{v:.0f} ms", footer),
        "costo": chart(
            "Jev vs Luna · costo de API", "Dólares por 20 tickets y una llamada de preparación",
            ["Prueba completa"], runs,
            lambda r: [r["cost_usd"]],
            lambda r, i: f'${r["cost_usd"]:.6f}',
            [0, .002, .004, .006, .008], lambda v: f"${v:.3f}", footer),
    }
    chrome = shutil.which("google-chrome")
    if not chrome:
        raise SystemExit("Se necesita google-chrome para exportar PNG")
    for name, svg in charts.items():
        path = out / f"jev-luna-{name}.svg"
        path.write_text(svg, encoding="utf-8")
        png = path.with_suffix(".png")
        subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=2", "--window-size=880,440",
                        f"--screenshot={png}", path.as_uri()], check=True, capture_output=True)
        print(png.relative_to(ROOT))


if __name__ == "__main__":
    main()
