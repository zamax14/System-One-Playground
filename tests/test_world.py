import threading
import unittest

from pondera.demos.atlas import FICHA, SCALES, Evaluator, country_state, extract_scores, load_countries, load_prior, questions_for, relative


class Model:
    def __init__(self, predict): self.predict = predict


class WorldChecks(unittest.TestCase):
    def test_every_country_has_a_complete_ficha(self):
        countries = load_countries()
        self.assertEqual(len(countries), 176)
        self.assertEqual(len(countries), len({c['id'] for c in countries}))
        for country in countries:
            ficha = country['ficha']
            self.assertEqual(set(ficha), set(FICHA), country['id'])
            self.assertTrue(all(value.strip() for value in ficha.values()), country['id'])
            for key, allowed in SCALES.items():
                self.assertIn(ficha[key], allowed, country['id'])
        self.assertNotIn('ATA', {c['id'] for c in countries})

    def test_state_names_only_salient_traits(self):
        by_id = {c['id']: c for c in load_countries()}
        self.assertTrue(country_state(by_id['MEX']).startswith('México: tacos'))
        self.assertIn('muy picante', country_state(by_id['MEX']))
        # Un rasgo ausente no se menciona: si se nombra, Laya lo toma por coincidencia.
        self.assertNotIn('pica', country_state(by_id['NOR']))
        self.assertNotIn('vegetariano', country_state(by_id['ARG']))
        self.assertEqual(by_id['TWN']['name'], 'Taiwán')  # Los nombres corregidos en la ficha mandan.
        for country in by_id.values():
            state = country_state(country)
            self.assertLess(len(state), 700, country['id'])
            for label in ('Picante:', 'Pescado y marisco:', 'Comer vegetariano:', 'Carne:'):
                self.assertNotIn(label, state, country['id'])  # Las etiquetas hacían eco de la consulta.

    def test_prior_matches_the_fichas_and_orders_scores(self):
        countries = load_countries()
        prior = load_prior(countries)
        self.assertEqual(set(prior), {c['id'] for c in countries})
        # Mismo «sí» del modelo: sale más alto el país que suele decir menos «sí».
        self.assertGreater(relative(.9, prior=-2), relative(.9, prior=2))
        self.assertLess(relative(.5, 0), relative(.9, 0))
        self.assertTrue(0 < relative(1.0, 5) < 1 and 0 < relative(0.0, -5) < 1)

    def test_scores_are_independent_and_validated(self):
        countries = load_countries()[:2]
        scores = extract_scores({'answers': {c['id']: {'noul': .9} for c in countries}}, countries)
        self.assertAlmostEqual(sum(scores.values()), 1.8)
        for value in (float('nan'), float('inf'), -1, 2, None):
            with self.assertRaises(ValueError):
                extract_scores({'answers': {countries[0]['id']: {'noul': value}}}, countries[:1])

    def test_question_carries_the_query(self):
        country = load_countries()[0]
        question = questions_for([country], 'comida picante')[country['id']]
        self.assertEqual(question['type'], 'noul')
        self.assertIn('comida picante', question['instructions'])

    def test_cancelled_query_never_publishes(self):
        entered, release = threading.Event(), threading.Event()
        def predict(state, questions):
            if 'old' in next(iter(questions.values()))['instructions']:
                entered.set()
                self.assertTrue(release.wait(5))
            return {'answers': {key: {'noul': .6} for key in questions}}
        countries = load_countries()[:10]
        evaluator = Evaluator(countries, Model(predict), prior={c['id']: 0 for c in countries})
        old, _ = evaluator.submit('old')
        self.assertTrue(entered.wait(5))
        new, _ = evaluator.submit('new')
        release.set()
        kinds = []
        while not kinds or kinds[-1] != 'done':
            kinds.append(new.get(timeout=5)[0])
        self.assertEqual(kinds, ['batch', 'batch', 'done'])
        self.assertTrue(old.empty())  # La consulta cancelada no publicó ni su primer país.


if __name__ == '__main__': unittest.main()
