"""Las corridas locales y remotas se guardan sin repetir inferencias completas."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import benchmark
from fastload import ROOT, SharedModel
from scripts.record_benchmark import record
from tests.test_server import FakeModel


class PaidFake(FakeModel):
    name = "Modelo de prueba"
    checkpoint = "hf/test@revision"
    calibrated = True
    cost = 0.0

    def __init__(self):
        super().__init__()
        self.calls = 0

    def predict(self, state, questions):
        self.calls += 1
        self.cost += .001
        return super().predict(state, questions)


class LocalFake(FakeModel):
    name = "Laya de prueba"
    checkpoint = "hf/laya@revision"
    device = "cpu"


class RecordChecks(unittest.TestCase):
    def test_local_checkpoint_metadata_uses_a_portable_path(self):
        model = SharedModel(path=ROOT / ".model-cache" / "example")
        self.assertEqual(model.checkpoint, ".model-cache/example")

    def test_local_run_has_no_api_cost(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            result = record("laya", LocalFake(), Path(directory) / "laya.json")
            self.assertEqual((result["device"], result["cost_usd"], len(result["rows"])), ("cpu", None, 20))

    def test_live_benchmark_counts_warmup_cost(self):
        model = PaidFake()
        summary = [data for kind, data in benchmark.run({"jev": model}) if kind == "summary"][0]
        self.assertEqual((model.calls, summary["cost_usd"]), (21, .021))

    def test_record_is_complete_and_repeated_run_is_free(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            path = Path(directory) / "run.json"
            first = PaidFake()
            result = record("jev", first, path)
            self.assertEqual((result["status"], len(result["rows"]), result["calls"]), ("complete", 20, 21))
            self.assertEqual(result["cost_usd"], .021)
            second = PaidFake()
            self.assertEqual(record("jev", second, path)["fingerprint"], result["fingerprint"])
            self.assertEqual(second.calls, 0)


if __name__ == "__main__":
    unittest.main()
