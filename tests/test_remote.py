"""Adaptadores de OpenRouter sin red: forma de las respuestas, esquema y llamadas."""
import io
import json
import unittest
from unittest import mock

import remote
from remote import ChatModel, JevModel, normalize, schema

QUESTIONS = {"cat": {"type": "choice", "instructions": "?", "criteria": {"a": "A", "b": "B"}},
             "nivel": {"type": "score", "instructions": "?", "criteria": ["bajo", "medio", "alto"]},
             "si": {"type": "noul", "instructions": "?"}}


def reply(payload):
    return mock.patch.object(remote, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode()))


class RemoteChecks(unittest.TestCase):
    def test_normalize_fills_the_shared_answer_shape(self):
        out = normalize({"cat": {"choice": "b", "probabilities": {"a": 1, "b": 3}},
                         "nivel": {"level": "2", "probabilities": {"0": 0, "1": 0, "2": 0}},
                         "si": {"probability": .8}}, QUESTIONS)
        self.assertEqual(out["cat"], {"type": "choice", "choice": "b", "probabilities": {"a": .25, "b": .75}, "confidence": .75})
        self.assertEqual(out["nivel"]["score"], 2)  # Sin distribución: toda la masa en el nivel dicho.
        self.assertEqual(out["si"]["noul"], .8)
        self.assertEqual(normalize({"si": {"noul": .1}}, {"si": QUESTIONS["si"]})["si"]["confidence"], .9)

    def test_normalize_rejects_missing_or_out_of_range_answers(self):
        with self.assertRaises(ValueError):
            normalize({}, QUESTIONS)
        with self.assertRaises(ValueError):
            normalize({"si": {"noul": 1.5}}, {"si": QUESTIONS["si"]})

    def test_schema_only_allows_the_options(self):
        s = schema(QUESTIONS)
        self.assertEqual(s["required"], ["cat", "nivel", "si"])
        self.assertEqual(s["properties"]["cat"]["properties"]["choice"]["enum"], ["a", "b"])
        self.assertEqual(s["properties"]["nivel"]["properties"]["level"]["enum"], ["0", "1", "2"])
        self.assertFalse(s["properties"]["si"]["additionalProperties"])

    def test_models_without_key_report_the_error(self):
        with mock.patch.object(remote, "secret", return_value=None):
            model = JevModel()
        self.assertEqual(model.status, "error")
        with self.assertRaises(RuntimeError):
            model.predict("x", QUESTIONS)

    def test_jev_and_chat_answer_and_count_cost(self):
        with mock.patch.object(remote, "secret", return_value="k"):
            jev, chat = JevModel(), ChatModel("openai/x", "X")
        answers = {"cat": {"choice": "a", "probabilities": {"a": .9, "b": .1}, "confidence": .9},
                   "nivel": {"score": 1.2, "probabilities": {"0": .1, "1": .6, "2": .3}}, "si": {"noul": .3}}
        with reply({"answers": answers, "usage": {"input_tokens": 50, "cost": .001}}) as call:
            self.assertEqual(jev.predict("x", QUESTIONS)["answers"]["cat"]["choice"], "a")
        self.assertTrue(call.call_args.args[0].full_url.endswith("/systemone"))
        content = json.dumps({"cat": {"choice": "b", "probabilities": {"a": .2, "b": .8}},
                              "nivel": {"level": "0", "probabilities": {"0": .7, "1": .2, "2": .1}},
                              "si": {"probability": .6}})
        with reply({"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 70, "cost": .002}}):
            self.assertEqual(chat.predict("x", QUESTIONS)["answers"]["nivel"]["score"], .4)
        self.assertEqual((jev.usage()["cost_usd"], chat.usage()["input_tokens"]), (.001, 70))


if __name__ == "__main__":
    unittest.main()
