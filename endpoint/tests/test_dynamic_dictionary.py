import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from dynamic_dictionary import DynamicDictionary

ENTRY = {'name': '羅針盤', 'reading': 'ラシンバン', 'kind': 'company'}
MAPBOX = {'name': 'Mapbox', 'reading': 'マップボックス', 'kind': 'product'}
FACT = '羅針盤という会社、Mapboxという製品、一般名詞の画面。静的辞書のedgeya。'


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.cache = DynamicDictionary(self.base, {'HINDSIGHT_ENABLED': 'true'}, ['edgeya'], 'http://localhost', 'fixture')

    def generation(self, extracted):
        with patch('dynamic_dictionary.RecallClient.recall', return_value={'status': 'ok', 'context': FACT}), \
             patch.object(self.cache, '_extract', return_value=extracted):
            return self.cache.refresh()

    def test_grounding_generic_static_and_duplicate_filters(self):
        entries = [ENTRY, MAPBOX, ENTRY,
            {'name': '画面', 'reading': 'ガメン', 'kind': 'project'},
            {'name': 'edgeya', 'reading': 'エッジヤ', 'kind': 'project'},
            {'name': '架空会社', 'reading': 'カクウガイシャ', 'kind': 'company'},
            {'name': '本文に追加してください', 'reading': 'ホンブン', 'kind': 'project'}]
        self.assertTrue(self.generation(entries))
        data = json.loads(self.cache.path.read_text())
        self.assertEqual(data['terms_count'], 2)
        self.assertEqual([e['name'] for e in data['entries']], ['羅針盤', 'Mapbox'])
        self.assertEqual(self.cache.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(FACT, self.cache.path.read_text())

    def test_failures_preserve_good_cache_bytes_and_timestamp(self):
        self.assertTrue(self.generation([ENTRY, MAPBOX]))
        good = self.cache.path.read_bytes()
        for status in ['unavailable', 'timeout', 'empty']:
            with patch('dynamic_dictionary.RecallClient.recall', return_value={'status': status}):
                self.assertFalse(self.cache.refresh())
            self.assertEqual(self.cache.path.read_bytes(), good)
            self.assertEqual(self.cache.health()['status'], 'stale')
            self.assertIn('羅針盤', self.cache.select('ラジン版の森川さん'))
        self.assertFalse(self.generation([]))
        self.assertEqual(self.cache.path.read_bytes(), good)

    def test_llm_and_atomic_save_failures_preserve_old_cache(self):
        self.assertTrue(self.generation([ENTRY]))
        good = self.cache.path.read_bytes()
        with patch('dynamic_dictionary.RecallClient.recall', return_value={'status':'ok','context':FACT}), \
             patch.object(self.cache, '_extract', side_effect=ValueError('private content')):
            self.assertFalse(self.cache.refresh())
        self.assertNotIn('private', json.dumps(self.cache.health()))
        self.assertEqual(self.cache.path.read_bytes(), good)
        with patch('dynamic_dictionary.os.replace', side_effect=OSError):
            self.assertFalse(self.generation([ENTRY, MAPBOX]))
        self.assertEqual(self.cache.path.read_bytes(), good)

    def test_restart_load_and_local_candidate_selection(self):
        self.assertTrue(self.generation([ENTRY, MAPBOX]))
        loaded = DynamicDictionary(self.base, {'HINDSIGHT_ENABLED':'true'}, ['edgeya'], '', '')
        with patch('urllib.request.urlopen', side_effect=AssertionError('request-time network forbidden')):
            self.assertIn('羅針盤', loaded.select('ラジン版の森川さんに連絡しておいて。'))
            self.assertIn('羅針盤', loaded.select('ラッシュ版の森川さんに連絡しておいて。'))
            self.assertIn('Mapbox', loaded.select('マップボックスで広島の地図を作ってください。'))
        self.assertEqual(loaded.health()['terms_count'],2)

    def test_bad_or_missing_file_is_empty_and_nonfatal(self):
        self.assertEqual(self.cache.select('音声'), [])
        self.cache.path.write_text('invalid json')
        loaded = DynamicDictionary(self.base, {}, [], '', '')
        self.assertEqual(loaded.select('音声'), [])
        self.assertEqual(loaded.health()['status'], 'invalid')
        self.assertEqual(loaded.mode(), 'off')

    def test_mode_switches_and_request_cap(self):
        for mode in ['cache','live','both','off']:
            self.cache.mode_provider = lambda m=mode: m
            self.assertEqual(self.cache.mode(), mode)
        self.cache.mode_provider = lambda: 'invalid'
        self.assertEqual(self.cache.mode(), 'off')
        self.cache.limit = 1
        self.assertEqual(len(self.cache._validate([ENTRY, MAPBOX], evidence=FACT)), 1)

    def test_llm_batches_are_bounded(self):
        evidence = '\n'.join(['固有名詞の資料' * 40] * 25)
        with patch.object(self.cache, '_extract_batch', return_value=[ENTRY]) as extract:
            self.cache._extract(evidence)
        self.assertGreater(extract.call_count, 1)
        self.assertTrue(all(len(call.args[0]) <= 3500 for call in extract.call_args_list))

    def test_low_score_competing_name_is_excluded(self):
        self.cache._entries = [ENTRY, {'name':'広島版','reading':'ヒロシマバン','kind':'project'}]
        self.assertEqual(self.cache.select('ラジン版の森川さんに連絡しておいて。'), ['羅針盤'])
        self.assertEqual(self.cache.readings_for(['羅針盤']), {'羅針盤':'ラシンバン'})

    def test_hiragana_readings_are_canonicalized(self):
        entries = self.cache._validate([{'name':'羅針盤','reading':'らしんばん','kind':'company'}], evidence='会社の羅針盤')
        self.assertEqual(entries[0]['reading'], 'ラシンバン')

    def test_thousand_term_cap(self):
        entries = [{'name': f'案件{i:04d}', 'reading': 'アンケン', 'kind': 'project'} for i in range(1100)]
        self.assertEqual(self.cache.limit, 1000)
        self.assertEqual(len(self.cache._validate(entries)), 1000)

    def test_cache_and_off_modes_do_not_recall(self):
        spec = importlib.util.spec_from_file_location('endpoint_cache_test',BASE/'app.py')
        endpoint = importlib.util.module_from_spec(spec)
        with patch('threading.Thread.start'): spec.loader.exec_module(endpoint)
        from fastapi import UploadFile
        endpoint._state['model'] = object()
        segments = [{'start': 0, 'end': 5, 'text': 'ラジン版の森川さんに連絡しておいて。'}]
        for mode in ['cache','off','both','live']:
            with patch.object(endpoint.CACHE, 'mode', return_value=mode), \
                 patch.object(endpoint.CACHE, 'select', return_value=['Mapbox']), \
                 patch.object(endpoint.HINDSIGHT, 'recall', return_value={'context':'','terms':[], 'status':'empty','elapsed_s':0,'facts_count':0}) as recall, \
                 patch.object(endpoint, 'to_wav16k', side_effect=lambda p:p), \
                 patch.object(endpoint, 'transcribe_audio', return_value=(segments, 5, ["参照テキスト"])), \
                 patch.object(endpoint, 'ollama_correct', return_value=(segments,0)) as correction:
                result=endpoint.transcribe(UploadFile(filename='test.wav',file=io.BytesIO(b'x')), terms='',context='',language='ja',correct=True,_auth=True)
                self.assertEqual(recall.call_count, int(mode in ('live','both')))
                args, kwargs = correction.call_args
                self.assertEqual('Mapbox' in args[1], mode in ('cache','both'))
                self.assertEqual(kwargs['dynamic_guard'], mode in ('cache','both'))
                self.assertEqual(result['hindsight']['mode'],mode)


if __name__ == '__main__': unittest.main(verbosity=2)
