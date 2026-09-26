"""Construcción del benchmark de contexto largo, con un contador de palabras en lugar del tokenizador."""
import importlib.util
import unittest
from pathlib import Path

from pondera.demos.tickets import TICKETS, ticket_state

spec = importlib.util.spec_from_file_location("benchmark_largo", Path(__file__).resolve().parents[1] / "scripts" / "benchmark_largo.py")
largo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(largo)


class LongStateChecks(unittest.TestCase):
    def test_ticket_first_padding_under_target_and_deterministic(self):
        blocks = [f"Bloque {i}: " + "palabra " * 50 for i in range(40)]
        count = lambda text: len(text.split())
        base = ticket_state(TICKETS[0])["ticket"]
        self.assertEqual(largo.long_state(TICKETS[0], None, blocks, count), {"ticket": base})
        state = largo.long_state(TICKETS[0], 1000, blocks, count)["ticket"]
        self.assertTrue(state.startswith(base))  # El ticket va primero y sin cambios.
        self.assertLessEqual(count(state), 1000)
        self.assertGreater(count(state), 1000 - 60)  # Se rellena hasta casi el tope.
        self.assertEqual(state, largo.long_state(TICKETS[0], 1000, blocks, count)["ticket"])
        self.assertNotEqual(state, largo.long_state(TICKETS[1], 1000, blocks, count)["ticket"].replace(
            ticket_state(TICKETS[1])["ticket"], base))  # Cada ticket lleva otro orden de ruido.


if __name__ == "__main__":
    unittest.main()
