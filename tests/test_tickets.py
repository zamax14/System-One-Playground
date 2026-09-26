"""Mesa de ayuda sin modelo."""
import unittest

from pondera.demos import tickets
from pondera.demos.tickets import CATEGORIES, PRIORITIES, TICKETS, assign, light, public, ticket_state


def answer(category="redes", confidence=.9, score=2.2):
    def predict(state, questions):
        self_check = questions["categoria"]["criteria"], questions["prioridad"]["criteria"]
        assert len(self_check[0]) == len(CATEGORIES) and len(self_check[1]) == len(PRIORITIES)
        probabilities = {k: (.9 if k == category else .02) for k in CATEGORIES}
        return {"answers": {
            "categoria": {"choice": category, "confidence": confidence, "probabilities": probabilities},
            "prioridad": {"score": score, "confidence": .4, "probabilities": {str(i): .25 for i in range(len(PRIORITIES))}}}}
    return predict


class DeskChecks(unittest.TestCase):
    def test_twenty_tickets_with_valid_references(self):
        self.assertEqual(len(TICKETS), 20)
        self.assertEqual(len({t["id"] for t in TICKETS}), 20)
        for t in TICKETS:
            category, priority, expert = t["referencia"]
            self.assertIn(priority, PRIORITIES)
            if category:
                self.assertIn(category, CATEGORIES)
                self.assertEqual(CATEGORIES[category][1], expert, t["id"])  # El experto es el responsable de la categoría.
            self.assertNotIn("referencia", public(t))
            self.assertNotIn(str(t["referencia"]), str(ticket_state(t)))

    def test_descriptions_do_not_leak_the_answer(self):
        # Un benchmark que dice la respuesta en el texto no mide nada.
        for t in TICKETS:
            text = t["descripcion"].lower()
            self.assertFalse([h for h in tickets.LEAK_HINTS if h in text], t["id"])
            category = t["referencia"][0]
            if category:
                self.assertNotIn(CATEGORIES[category][0].lower(), text, t["id"])
            self.assertIsInstance(t["bloquea"], bool)
            self.assertNotIn("bloquea", public(t))

    def test_every_category_has_an_expert(self):
        self.assertEqual({owner for _, owner, _ in CATEGORIES.values()}, set(tickets.EXPERTS))

    def test_light_thresholds(self):
        self.assertEqual([light(c)[0] for c in (100, 80.1, 80, 70, 60, 59.9, 0)],
                         ["verde", "verde", "amarillo", "amarillo", "amarillo", "rojo", "rojo"])

    def test_assign_routes_to_the_category_owner(self):
        result = assign(TICKETS[1], answer("redes", .92, 2.2))
        self.assertEqual((result["categoria"]["choice"], result["experto"]), ("redes", "sofia"))
        self.assertEqual(result["prioridad"]["choice"], "alta")  # 2,2 se redondea al nivel 2.
        self.assertEqual((result["confianza"], result["semaforo"]), (92.0, "verde"))
        self.assertEqual(set(result["prioridad"]["probabilities"]), set(PRIORITIES))
        low = assign(TICKETS[19], answer("hardware", .3, 3.6))
        self.assertEqual((low["semaforo"], low["prioridad"]["choice"]), ("rojo", "critica"))

    def test_invalid_answers_are_rejected(self):
        with self.assertRaises(ValueError):
            assign(TICKETS[0], answer("impresoras"))
        with self.assertRaises(ValueError):
            assign(TICKETS[0], answer(score=float("nan")))


if __name__ == "__main__":
    unittest.main()
