import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import eval as app


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        app.STOP.clear()
        self.cases = app.load_cases('data/smoke.jsonl')

    def test_gold_never_sent_and_mock_label_blind(self):
        case = self.cases[0]
        other = dict(case, expected={'team':'sales','urgent':False})
        self.assertEqual(app.mock_response(case), app.mock_response(other))

    def test_probability_metrics(self):
        c = {'questions':{'q':{'type':'noul'}}, 'expected':{'q':True}}
        m = app.evaluate(c, {'answers':{'q':{'noul':.8}}})[0]
        self.assertEqual(m['correct'], 1)
        self.assertAlmostEqual(m['brier'], .08)
        with self.assertRaises(ValueError):
            app.evaluate(c, {'answers':{'q':{'noul':float('nan')}}})

    def test_score_is_expected_value(self):
        c = self.cases[2]
        row = app.evaluate(c, {'answers':{'impact':{'probabilities':{'0':.1,'1':.1,'2':.1,'3':.7}}}})[0]
        self.assertAlmostEqual(row['mae'], .6)

    def test_resume_and_config_guard(self):
        with tempfile.TemporaryDirectory() as t:
            a = argparse.Namespace(dataset='data/smoke.jsonl', models='clef', provider='mock', endpoint='', repeats=1,
                                   run_id='test', db=str(Path(t)/'db'), retry_errors=False, delay=0, output=None)
            with patch('builtins.print'):
                app.run_once(a)
                with patch.object(app, 'mock_response', side_effect=AssertionError('must resume')):
                    result = app.run_once(a)
            self.assertEqual(result['summary']['clef']['requests'], 4)
            self.assertEqual(result['summary']['clef']['errors'], 0)
            a.repeats = 2
            with self.assertRaises(ValueError):
                app.run_once(a)

    def test_auth_error_does_not_retry_or_leak(self):
        error = urllib.error.HTTPError('https://example.test', 401, 'secret', {}, None)
        with patch('urllib.request.urlopen', side_effect=error) as call:
            with self.assertRaisesRegex(RuntimeError, '^API HTTP 401$'):
                app.request_json('https://example.test', 'secret')
            self.assertEqual(call.call_count, 1)

    def test_transient_error_retries(self):
        error = urllib.error.HTTPError('https://example.test', 429, 'busy', {'Retry-After':'0'}, None)
        with patch('urllib.request.urlopen', side_effect=error) as call:
            with self.assertRaises(RuntimeError):
                app.request_json('https://example.test', 'secret', retries=2)
            self.assertEqual(call.call_count, 3)


if __name__ == '__main__':
    unittest.main()
