import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

spec = importlib.util.spec_from_file_location('endpoint_under_test', BASE / 'app.py')
endpoint = importlib.util.module_from_spec(spec)
with patch('threading.Thread.start'):
    spec.loader.exec_module(endpoint)


def apply(text):
    out, _ = endpoint.apply_deterministic([{'text': text}])
    return out[0]['text']


class DeterministicSubsTests(unittest.TestCase):
    def test_full_scratch_garbling(self):
        # Observed 2026-11-05 in real usage: ASR wrote フリースクラッチ
        # for フルスクラッチ (build from scratch).
        self.assertEqual(
            apply('フリースクラッチで作ったものも、手を入れやすくなってる。'),
            'フルスクラッチで作ったものも、手を入れやすくなってる。',
        )

    def test_existing_subs_still_work(self):
        self.assertEqual(apply('ギットハブにプッシュして。'), 'GitHubにプッシュして。')
        self.assertEqual(apply('ラッシュ版の森川さんに連絡して。'), '羅針盤の森川さんに連絡して。')

    def test_non_contiguous_free_and_scratch_untouched(self):
        text = 'フリー素材とスクラッチ開発は別です。'
        self.assertEqual(apply(text), text)

    def test_full_scratch_in_terms(self):
        self.assertIn('フルスクラッチ', endpoint.BASE_TERMS)


if __name__ == '__main__':
    unittest.main()
