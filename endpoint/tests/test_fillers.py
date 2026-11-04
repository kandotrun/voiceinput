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


class FillerTests(unittest.TestCase):
    def strip(self, text):
        out, _ = endpoint.strip_fillers(text)
        return out

    def test_strips_standalone_fillers(self):
        self.assertEqual(self.strip("あの、明日の会議は、えっと、三時からです。"), "明日の会議は、三時からです。")
        self.assertEqual(self.strip("そのー、来週の予定なんですけど。"), "来週の予定なんですけど。")
        self.assertEqual(self.strip("まあ、とりあえず進めましょう。"), "とりあえず進めましょう。")
        self.assertEqual(self.strip("うーん、考えておきます。"), "考えておきます。")
        self.assertEqual(self.strip("昨日は、あの、駅前の店に行きました。"), "昨日は、駅前の店に行きました。")
        self.assertEqual(
            self.strip("えっと、GitLabの件です。あのー、明日までに対応します。"),
            "GitLabの件です。明日までに対応します。",
        )

    def test_keeps_demonstratives_and_content(self):
        for text in ("あの日は雨でした。", "あの件は後で確認します。", "その件は重要です。", "まあいいか、次に行こう。"):
            self.assertEqual(self.strip(text), text)


if __name__ == '__main__':
    unittest.main()
