"""Measure the same Laya-Finetune tool-routing test set with Laya, Jev and Luna.

Run with Laya-Finetune's environment and PYTHONPATH pointing at that checkout.
The task YAML path is explicit because the test set belongs to that project.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from layaft.evaluate.run import summarize
from layaft.model.load import load
from layaft.task import Task

from system_one_playground.models.remote import ChatModel, JevModel

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "web" / "results" / "tool-routing"
CHECKPOINTS = {
    "laya-base": "multilingual",
    "laya-ft-1k": ROOT / ".model-cache" / "laya-tool-routing-1k",
    "laya-ft-8k": ROOT / ".model-cache" / "laya-tool-routing-8k",
}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=(*CHECKPOINTS, "jev", "luna"))
    parser.add_argument("--task", type=Path, required=True, help="Laya-Finetune/tasks/tool_routing.yaml")
    parser.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    args = parser.parse_args()

    task = Task.load(args.task)
    cases = task.test_cases()
    if not cases:
        raise ValueError(f"No hay casos de prueba en {task.test_path}")
    fingerprint = task.fingerprint(cases)
    test_sha256 = hashlib.sha256(task.test_path.read_bytes()).hexdigest()
    if args.model in CHECKPOINTS:
        model = load(CHECKPOINTS[args.model], device=args.device, ctx=1024 if args.model == "laya-base" else None)
        checkpoint = (str(CHECKPOINTS[args.model].relative_to(ROOT))
                      if isinstance(CHECKPOINTS[args.model], Path) else CHECKPOINTS[args.model])
        context_size = model.cfg["max_len"]
        device = args.device
    else:
        model = JevModel() if args.model == "jev" else ChatModel("openai/gpt-5.6-luna", "GPT-5.6 Luna")
        checkpoint, context_size, device = model.checkpoint, None, "api"
    path = RESULTS / f"{args.model}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data["fingerprint"], data["test_sha256"], data["checkpoint"]) != (fingerprint, test_sha256, checkpoint):
            raise ValueError(f"{path} contiene otra evaluación; elige otra ruta")
        if data["status"] == "complete":
            print(f"Corrida completa: {path}")
            return
    else:
        data = {"model": args.model, "checkpoint": checkpoint, "context_size": context_size,
                "device": device, "task": task.name, "fingerprint": fingerprint,
                "test_sha256": test_sha256, "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "running", "cost_usd": 0 if device == "api" else None, "rows": []}
        save(path, data)
    done = {row["id"] for row in data["rows"]}
    if device == "api":
        model.cost = data["cost_usd"]
    try:
        for case in cases:
            if case["id"] in done:
                continue
            started = time.perf_counter()
            answers = model.predict(task.state(case), task.laya)["answers"]
            data["rows"].append({"id": case["id"], "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                                 "answers": {qid: q.record(answers[qid], case["answers"].get(qid))
                                             for qid, q in task.questions.items()}})
            if device == "api":
                data["cost_usd"] = round(model.cost, 8)
            save(path, data)
            if len(data["rows"]) % 10 == 0:
                print(f"{args.model}: {len(data['rows'])}/{len(cases)}", flush=True)
        data.update(summarize(task, data["rows"]))
        data["status"] = "complete"
        save(path, data)
    except Exception as exc:
        data.update(status="error", error=f"{type(exc).__name__}: {exc}")
        save(path, data)
        raise


if __name__ == "__main__":
    main()
