"""Ruta de aprendizaje sin modelo: reglas del bucle de decisión."""
import unittest

from system_one_playground.demos.courses import CATALOG, COURSES, GOALS, MAX_STEPS, PROFILES, Roadmap, SKILLS


def chooser(pick):
    """Modelo falso: `pick(ids)` elige entre los candidatos que le llegan."""
    def predict(state, questions):
        ids = list(questions["siguiente"]["criteria"])
        choice = pick(ids)
        return {"answers": {"siguiente": {"choice": choice, "confidence": .8,
                                          "probabilities": {i: 1 / len(ids) for i in ids}}}}
    return predict


def greedy(roadmap):
    """Elige siempre un curso que enseñe algo que falta; si no hay, el primero."""
    return chooser(lambda ids: next((i for i in ids if any(s in roadmap.missing for s in CATALOG[i]["ensena"])), ids[0]))


class CatalogChecks(unittest.TestCase):
    def test_catalog_is_coherent(self):
        self.assertEqual(len(CATALOG), len(COURSES))
        for course in COURSES:
            self.assertTrue(course["ensena"], course["id"])
            for skill in course["ensena"] + course["requisitos"]:
                self.assertIn(skill, SKILLS, course["id"])
            self.assertNotIn(course["nivel"], ("", None))

    def test_every_goal_is_reachable_and_every_profile_is_valid(self):
        for name, goal in GOALS.items():
            for skill in goal["requiere"]:
                self.assertTrue(any(skill in c["ensena"] for c in COURSES), f"{name}: {skill}")
        for name, profile in PROFILES.items():
            self.assertGreater(profile["horas_semana"], 0, name)
            for course in profile["completados"]:
                self.assertIn(course, CATALOG, name)
            # Quien ya hizo un curso tiene lo que enseña: el estado de partida es consistente.
            for course in profile["completados"]:
                for skill in CATALOG[course]["ensena"]:
                    self.assertIn(skill, profile["habilidades"], name)


class LoopChecks(unittest.TestCase):
    def test_candidates_respect_prerequisites_and_drop_completed(self):
        roadmap = Roadmap("data-science", "ana")
        ids = [c["id"] for c in roadmap.candidates()]
        self.assertIn("python-basico", ids)
        self.assertNotIn("programacion-cero", ids)  # Ya lo hizo.
        self.assertNotIn("pandas-analisis", ids)    # Le falta Python.
        roadmap.step(chooser(lambda ids: "python-basico"))
        self.assertIn("pandas-analisis", [c["id"] for c in roadmap.candidates()])

    def test_a_greedy_policy_reaches_the_goal(self):
        roadmap = Roadmap("data-science", "ana")
        while not roadmap.done:
            roadmap.step(greedy(roadmap))
        self.assertEqual((roadmap.reason, roadmap.missing), ("Objetivo alcanzado", []))
        self.assertEqual(roadmap.hours, sum(CATALOG[h["curso"]]["horas"] for h in roadmap.history))
        last = roadmap.history[-1]
        self.assertEqual((last["horas_totales"], last["restante"]), (roadmap.hours, []))
        self.assertEqual(last["semanas"], round(roadmap.hours / PROFILES["ana"]["horas_semana"], 1))

    def test_prior_skills_shorten_the_route_and_a_finished_one_rejects_steps(self):
        carla, bruno = Roadmap("data-science", "carla"), Roadmap("data-science", "bruno")
        for roadmap in (carla, bruno):
            while not roadmap.done:
                roadmap.step(greedy(roadmap))
        self.assertLess(len(carla.history), len(bruno.history))
        self.assertLess(carla.hours, bruno.hours)
        with self.assertRaises(LookupError):
            carla.step(greedy(carla))

    def test_a_useless_choice_is_recorded_as_such(self):
        roadmap = Roadmap("data-science", "bruno")
        record = roadmap.step(chooser(lambda ids: "seguridad-web" if "seguridad-web" in ids else "html-css"))
        self.assertFalse(record["util"])
        self.assertEqual(record["aporta"], [])
        self.assertEqual(record["restante"], [SKILLS[s] for s in GOALS["data-science"]["requiere"]])

    def test_the_loop_always_stops(self):
        roadmap = Roadmap("desarrollo-web", "bruno")
        while not roadmap.done:
            roadmap.step(chooser(lambda ids: ids[-1]))  # Política pésima: siempre el último candidato.
        self.assertLessEqual(len(roadmap.history), MAX_STEPS)
        self.assertIn(roadmap.reason, ("Objetivo alcanzado", "No quedan cursos disponibles", "Demasiados pasos"))

    def test_answers_outside_the_candidates_are_rejected(self):
        roadmap = Roadmap("data-science", "ana")
        with self.assertRaises(ValueError):
            roadmap.step(chooser(lambda ids: "deep-learning"))  # Sin prerrequisitos: no es candidato.

        def broken(state, questions):
            return {"answers": {"siguiente": {"choice": "python-basico", "confidence": .5, "probabilities": {"a": .5}}}}
        with self.assertRaises(ValueError):
            roadmap.step(broken)
        self.assertEqual(roadmap.history, [])  # Nada se aplicó.

    def test_bad_goal_or_profile(self):
        for args in (("no-existe", "ana"), ("data-science", "nadie")):
            with self.assertRaises(ValueError):
                Roadmap(*args)


if __name__ == "__main__":
    unittest.main()
