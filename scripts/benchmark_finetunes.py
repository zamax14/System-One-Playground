"""Laya base frente a sus checkpoints ajustados, cada uno en la prueba reservada de su tarea de Laya-Tasks.

Correr desde la raíz de este repo con el entorno de Laya-Finetune (usa sus métricas y gráficas):
    ../Laya-Finetune/.venv/bin/python scripts/benchmark_finetunes.py [--tareas helpdesk tool_routing] [--png]
Una corrida ya guardada con la misma prueba y los mismos pesos no se repite.
"""
import argparse
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import torch

from layaft.evaluate import report
from layaft.evaluate.run import evaluate
from layaft.model.load import load
from layaft.task import Task

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".model-cache"
RESULTS = ROOT / "web" / "results" / "finetunes"
OUTPUT = ROOT / "assets" / "comparativas" / "laya-base-ft"
# Nombre en la tabla → checkpoint. La base va primero en cada tarea.
SUITES = {
    "helpdesk": {"Laya base": "multilingual",
                 "FT prueba · 1k": CACHE / "laya-mesa-de-ayuda-prueba",
                 "FT v4 · 8k": CACHE / "laya-mesa-de-ayuda-v4"},
    "tool_routing": {"Laya base": "multilingual",
                     "FT · 1k": CACHE / "laya-tool-routing-1k",
                     "FT · 8k": CACHE / "laya-tool-routing-8k",
                     "FT · 32k": CACHE / "laya-tool-routing-32k"},
    "context_prefilter": {"Laya base": "multilingual",
                          "FT · 1k": CACHE / "laya-context-prefilter-1k",
                          "FT · 8k": CACHE / "laya-context-prefilter-8k"},
}
# ponytail: la prueba es de textos cortos, así que todos cargan con 8k (el límite de la base) y sdpa;
# a 32k load() pide flex_attention, que compila con Triton sin ganar nada aquí.
CTX = 8192


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def run(task, name, checkpoint, device):
    cases = task.test_cases()
    path = RESULTS / task.name / f"{name.replace(' · ', '-').replace(' ', '-').lower()}.json"
    meta = {"model": name, "checkpoint": str(checkpoint.relative_to(ROOT)) if isinstance(checkpoint, Path) else checkpoint,
            "weights_sha256": sha256(checkpoint / "model.safetensors") if isinstance(checkpoint, Path) else None,
            "task": task.name, "fingerprint": task.fingerprint(cases), "test_sha256": sha256(task.test_path)}
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if all(saved[k] == v for k, v in meta.items()):
            print(f"Ya medido: {path.relative_to(ROOT)}")
            return saved
    print(f"{task.name}: {name} en {len(cases)} casos", flush=True)
    agent = load(checkpoint, device=device, ctx=CTX)
    summary, rows = evaluate(agent, cases, task)
    del agent
    gc.collect()
    torch.cuda.empty_cache()
    data = meta | {"device": device, "gpu": torch.cuda.get_device_name() if device == "cuda" else None,
                   "created_at": datetime.now(timezone.utc).isoformat(), "summary": summary, "rows": rows}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tareas", nargs="+", choices=SUITES, default=list(SUITES))
    parser.add_argument("--tasks-dir", type=Path, default=ROOT.parent / "Laya-Tasks" / "tasks")
    parser.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    parser.add_argument("--png", action="store_true", help="también exporta PNG a 2× con Chrome")
    args = parser.parse_args()
    for name in args.tareas:
        task = Task.load(args.tasks_dir / f"{name}.yaml")
        runs = {label: run(task, label, checkpoint, args.device) for label, checkpoint in SUITES[name].items()}
        summaries = {label: r["summary"] for label, r in runs.items()}
        cases = next(iter(runs.values()))["summary"]["total"]
        where = "GPU local" if args.device == "cuda" else "CPU"
        report.chart(task, summaries, OUTPUT / f"{name}.svg",
                     subtitle=f"{task.name} · {cases} casos de prueba reservados · {where}",
                     footer=f"Laya-Tasks · huella {runs['Laya base']['fingerprint']}")
        if args.png:
            subprocess.run([shutil.which("google-chrome"), "--headless=new", "--no-sandbox", "--disable-gpu",
                            "--hide-scrollbars", "--force-device-scale-factor=2", "--window-size=880,440",
                            f"--screenshot={OUTPUT / f'{name}.png'}", (OUTPUT / f"{name}.svg").as_uri()],
                           check=True, capture_output=True)
        (OUTPUT / f"{name}.md").write_text(report.table(task, summaries) + "\n", encoding="utf-8")
        print(f"\n## {name}\n\n{report.table(task, summaries)}\n", flush=True)


if __name__ == "__main__":
    main()
