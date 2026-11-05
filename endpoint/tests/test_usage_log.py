import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

spec = importlib.util.spec_from_file_location('endpoint_under_test', BASE / 'app.py')
endpoint = importlib.util.module_from_spec(spec)
with patch('threading.Thread.start'):
    spec.loader.exec_module(endpoint)


class UsageLogTests(unittest.TestCase):
    def test_log_usage_writes_jsonl(self):
        # Regression: _log_usage used datetime/timezone without importing them,
        # and the NameError was swallowed by its try/except, so usage.jsonl
        # was never written (found 2026-11-04, fixed 2026-11-05).
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(endpoint, 'BASE', Path(tmp)):
                endpoint._log_usage({
                    'raw_text': 'raw text',
                    'text': 'final text',
                    'corrections': 1,
                    'reference': True,
                    'elapsed_s': 1.5,
                    'audio_duration_s': 3.0,
                })
            log_file = Path(tmp) / 'logs' / 'usage.jsonl'
            self.assertTrue(log_file.exists())
            lines = log_file.read_text(encoding='utf-8').strip().splitlines()
            self.assertEqual(len(lines), 1)
            rec = json.loads(lines[0])
            self.assertTrue(rec['ts'])
            self.assertEqual(rec['raw'], 'raw text')
            self.assertEqual(rec['text'], 'final text')


if __name__ == '__main__':
    unittest.main()
