"""Guarda una corrida reanudable de Laya, Jev o Luna para comparar el mismo benchmark."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pondera import benchmark
from pondera.models.remote import ChatModel, JevModel
from pondera.demos.tickets import TICKETS, ticket_state

RESULTS = ROOT / "web" / "results"


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def record(key, model, path):
    fingerprint = benchmark.fingerprint()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data["suite"], data["fingerprint"], data["checkpoint"]) != (benchmark.SUITE, fingerprint, model.checkpoint):
            raise ValueError(f"{path} corresponde a otra suite o checkpoint; consérvalo y elige otra ruta")
        if data["status"] == "complete":
            print(f"Ya está guardada la corrida de {model.name}: {path}")
            return data
    else:
        data = {"key": key, "name": model.name, "checkpoint": model.checkpoint,
                "calibrated": getattr(model, "calibrated", True), "suite": benchmark.SUITE, "fingerprint": fingerprint,
                "created_at": datetime.now(timezone.utc).isoformat(), "status": "running",
                "device": getattr(model, "device", None), "load_s": 0, "calls": 0,
                "cost_usd": 0.0 if hasattr(model, "cost") else None, "rows": []}
        save(path, data)

    try:
        started = time.perf_counter()
        previous = getattr(model, "cost", 0.0)
        model.predict(ticket_state(TICKETS[0]), benchmark.QUESTIONS)  # Calentamiento, también se cobra.
        data["device"] = getattr(model, "device", None)
        data["load_s"] += round(time.perf_counter() - started, 2)
        data["calls"] += 1
        if data["cost_usd"] is not None:
            data["cost_usd"] += model.cost - previous
        data["status"] = "running"
        data.pop("error", None)
        save(path, data)

        done = {item["id"] for item in data["rows"]}
        for ticket in TICKETS:
            if ticket["id"] in done:
                continue
            started = time.perf_counter()
            previous = getattr(model, "cost", 0.0)
            answers = model.predict(ticket_state(ticket), benchmark.QUESTIONS)["answers"]
            data["rows"].append(benchmark.row(ticket, answers, 1000 * (time.perf_counter() - started)))
            data["calls"] += 1
            if data["cost_usd"] is not None:
                data["cost_usd"] += model.cost - previous
            save(path, data)
            print(f"{model.name}: {len(data['rows'])}/{len(TICKETS)}")

        data.update(benchmark.summarize(data["rows"]))
        if data["cost_usd"] is not None:
            data["cost_usd"] = round(data["cost_usd"], 6)
        data["status"] = "complete"
        save(path, data)
        return data
    except Exception as exc:
        data["status"] = "error"
        data["error"] = f"{type(exc).__name__}: {exc}"
        save(path, data)
        raise


def main():
    parser = argparse.ArgumentParser(description="Guarda una corrida reanudable del benchmark de Pondera")
    parser.add_argument("model", choices=("laya", "jev", "gpt-luna"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto", help="dispositivo de Laya")
    parser.add_argument("--output", type=Path, help="ruta nueva para conservar corridas de otro checkpoint")
    parser.add_argument("--checkpoint", type=Path,
                        help="carpeta de una Laya reentrenada (github.com/zamax14/Laya-Finetune) en lugar de la base")
    args = parser.parse_args()
    key = args.model
    if args.model == "laya":
        from pondera.models.fastload import SharedModel
        model = SharedModel(device=args.device, path=args.checkpoint and args.checkpoint.resolve(),
                            name="Laya reentrenada" if args.checkpoint else None)
        key = "laya-mesa" if args.checkpoint else "laya"
    else:
        model = JevModel() if args.model == "jev" else ChatModel("openai/gpt-5.6-luna", "GPT-5.6 Luna")
    default = RESULTS / ("laya-reentrenada.json" if key == "laya-mesa" else f"{key}.json")
    record(key, model, args.output or default)


if __name__ == "__main__":
    main()
