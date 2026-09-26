"""Carga de Laya rápida y compartida entre las demos.

`build_model` crea el encoder con `AutoModel.from_config`, que rellena al azar 322 M de
parámetros; `load_state_dict(strict=True)` los reemplaza todos. Saltarse ese relleno baja la
carga en CPU de ~14 s a ~1,4 s y da exactamente los mismos pesos y logits.
"""
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def secret(env, filename):
    """Llave desde la variable de entorno o, si falta, desde un archivo de la raíz (ignorado en git)."""
    value = os.environ.get(env)
    if not value and (ROOT / filename).is_file():
        value = (ROOT / filename).read_text(encoding="utf-8").strip()
    return value or None


if secret("HF_TOKEN", "HF_TOKEN"):  # Descargas autenticadas de Hugging Face.
    os.environ["HF_TOKEN"] = secret("HF_TOKEN", "HF_TOKEN")
HF_HOME = ROOT / ".model-cache" / "huggingface"
os.environ["HF_HOME"] = str(HF_HOME)
os.environ["HF_HUB_CACHE"] = str(HF_HOME / "hub")
CHECKPOINT = "convaiinnovations/laya-multilingual@82d57fc4f2d1be3d2caac494045f2ec51d0842f3"

# torch 2.14 envía algunas operaciones de GPU a kernels de Triton que compilan C y necesitan Python.h
# (paquete python3-dev). Con este interruptor oficial usa las operaciones normales de torch.
# torch lo lee al importarse: este módulo debe importarse antes que torch (server.py ya lo hace así).
os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")


def pick_device(requested="auto"):
    import torch
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise ValueError("Pediste --device cuda, pero torch no ve ninguna GPU (¿instalaste requirements-gpu.txt?)")
    return requested


def load_agent(device="cpu", path=None):
    """El checkpoint de Hugging Face, o uno local (por ejemplo, el que deja scripts/finetune_mesa.py)."""
    os.environ.setdefault("USE_TF", "0")
    import laya
    from huggingface_hub import snapshot_download
    try:
        from transformers.initialization import no_init_weights
    except ImportError:  # transformers < 5 lo exponía en modeling_utils.
        from transformers.modeling_utils import no_init_weights
    repo, revision = CHECKPOINT.split("@")
    checkpoint = str(path) if path else snapshot_download(
        repo, revision=revision, allow_patterns=["rl_agent_config.json", "model.safetensors", "tokenizer/*", "encoder/*"])
    # El contexto desactiva las funciones de init de torch mientras se construye el modelo.
    with no_init_weights():
        return laya.load(checkpoint, device=device)


class SharedModel:
    """Una instancia de Laya para todas las demos; cada uso del modelo va en serie."""
    name = "Laya Multilingual"
    checkpoint = CHECKPOINT

    # 8192 es el máximo del encoder (mmBERT, max_position_embeddings). El checkpoint se entrenó con secuencias
    # de hasta 1024; cuánto rinde más allá lo mide scripts/benchmark_largo.py.
    def __init__(self, max_len=8192, head_max_len=256, device="auto", path=None, name=None):
        self.max_len, self.head_max_len, self.requested, self.path = max_len, head_max_len, device, path
        if path:
            local_path = Path(path).resolve()
            self.name = name or local_path.name
            self.checkpoint = str(local_path.relative_to(ROOT)) if local_path.is_relative_to(ROOT) else local_path.name
        self.agent, self.status, self.error, self.device = None, "idle", None, None
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            if self.agent is None:
                self.status = "loading"
                try:
                    # Sin tope de hilos: torch usa los núcleos físicos (medido: 4 hilos era un 35 % más lento).
                    device = pick_device(self.requested)
                    agent = load_agent(device=device, path=self.path)
                except Exception as exc:
                    self.status, self.error = "error", f"{type(exc).__name__}: {exc}"
                    raise
                # max_len solo es un tope: el relleno es dinámico, no encarece estados cortos.
                agent.cfg["max_len"], agent.cfg["head_max_len"] = self.max_len, self.head_max_len
                # La primera inferencia paga la preparación de kernels (sobre todo en GPU): se hace aquí
                # para no cobrársela a la primera decisión de una demo.
                agent.predict("Hola", {"calentar": {"type": "noul", "instructions": "¿Es un saludo?"}})
                self.agent, self.status, self.device = agent, "ready", device
        return self.agent

    def release(self):
        """Suelta los pesos para dejar la GPU a otro modelo local; la próxima predicción recarga (~3 s)."""
        with self.lock:
            if self.agent is None:
                return
            self.agent, self.status = None, "idle"
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def tokens(self, text):
        agent = self.load()
        with self.lock:  # El tokenizador rápido no admite usos concurrentes.
            return agent.tok(text)["input_ids"]

    def predict(self, state, questions):
        agent = self.load()
        from laya.common import build_sequence
        with self.lock:
            # Laya trunca el estado sin avisar; aquí se rechaza antes de inferir.
            for question in questions.values():
                full, _ = build_sequence(agent.tok, state, agent._to_internal(question),
                                         10**6, self.head_max_len)
                if len(full) > self.max_len:
                    raise ValueError(f"El estado no cabe en el contexto: {len(full)} de {self.max_len} tokens")
            result = agent.predict(state, questions)
            # Laya pasa a CPU para siempre si la GPU se queda sin memoria: que el indicador lo diga.
            self.device = agent.device.type
            return result
