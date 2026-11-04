# v2.3 ASR総入れ替え＋二重ASR融合検証（2026-11-04）

## 背景

v2.2 稼働後、Kanから「GitLabと言ったのに GitHubラボ になるなど、微妙な誤りがまだ結構ある。モデルの問題か。処理が長くなるのは良いので、検索もして精度を高めてほしい」との指摘を受けた。

## 調査（検索結果の要約）

- Qwen3-ASR-1.7B は読み上げ音声の CER では最良級だが、固有名詞 F1 では Whisper large-v3 系に劣るという複数の評価がある（Neosophie の日本語ASR評価、ja-asr-leaderboard-2026）。カタカナ・英字混じりの固有名詞を取り違える弱点が、今回の GitLab 件と一致する。
- `neosophie/Qwen3-ASR-1.7B-JA` は Qwen3-ASR-1.7B を日本語の固有名詞・技術用語に特化してファインチューニングした公開モデルで、固有名詞 F1 でベースモデルと Whisper を上回るとされる。qwen-asr パッケージのまま差し替え可能。
- Cohere Transcribe は 2026-11-01 のベンチで多言語漏出が大きく不採用のまま。

## 実測ベンチ（TTS 12文、主対象は固有名詞）

macOS Kyoko の say で生成した dictation 想定文12件を、各モデル生出力で比較した。抜粋:

| 文 | Qwen3-ASR-1.7B | JA版 | Whisper turbo（辞書プロンプト） |
|---|---|---|---|
| GitLabで…GitHubと使い分け | Gitラブ…Gitサブ | GitLab…GitLab | GitLab（2箇所目は GiSub） |
| Cloudflareにデプロイ | 正 | Claudfla | 正 |
| 羅針盤の森川さん | ラッシュ版 | 最新版 | 正 |
| DockerとKubernetes | ドーカーとキューバにいつ | DockerとCUBA2 | DockerとCuberNeeds |

どのモデルも単独では全勝しない。誤りの出方がモデルごとに異なるため、主ASR＋参照ASRの融合が有効と判断した。

融合補正のモデル選別プローブ（主=JA版、参照=Whisper）では、補正LLMに gemma4:31b-mlx を使った方が qwen3.8:27b-mlx より選別が正確だった（Kubernetes や GitLab の復元に成功）。このため補正LLMも gemma4 へ変更した。

## 変更内容

変更: `endpoint/app.py`、`endpoint/terms.txt`、`endpoint/tests/`（モック戻り値の追随）、`endpoint/README.md`。

- 主ASR: `neosophie/Qwen3-ASR-1.7B-JA`（`ASR_MODEL_ID` で差替可能）
- 参照ASR: mlx-whisper large-v3-turbo をチャンク単位で併走。initial_prompt に静的辞書全語。失敗時は参照なしで従来経路にフォールバック
- 補正: gemma4:31b-mlx。参照がある場合は融合プロンプト（主を土台に相違箇所を選別）。受理ガードに「参照側に実在するスパン」を証拠として追加
- 静的辞書: 25語→36語（技術用語11語追加）。決定的置換に3件追加（ギットラボ→GitLab、スーパーベース→Supabase、ドーカー→Docker）
- レスポンスに `reference: {engine, segments}` を追加（アプリ互換は維持）

## 検証（稼働中サービスへの実API、correct=true）

TTS評価12件＋従来ベンチ5件の計17件で、16件が期待通り:

- 従来失敗していた Cloudflare（JA版の Claudfla）、Vercel、Supabase、Kubernetes、羅針盤（JA版の 最新版／打診番／新版）がすべて正しく復元された
- GitHub／Claude Code／TransAI／髙松／Mapbox は維持。一般文の対照ケースは無変更
- 残った1件は「GitLabでリポジトリを管理して、GitHubと使い分けています。」で、両モデルとも同じ箇所（で→ダ／Oda 等）を崩した TTS 由来の崩れと、2箇所目の GitLab/GitHub の混同（両モデルが GitLab と聞き取った）が残った
- 所要時間は1発話 1.6〜5.9秒（初回コールド 11.4秒）。v2.2 の約1〜4秒より長いが、精度優先で許容する運用
- 自動テスト21件すべて成功。デプロイ後 `/health`: engine=qwen3-asr-1.7b-ja、ollama_model=gemma4:31b-mlx、辞書36語、キャッシュ ready

## ロールバック

本番の `app.py.bak-v2.3-20261104`、`terms.txt.bak-v2.3-20261104` を復元して再起動する。モデルだけ戻す場合は `ASR_MODEL_ID=Qwen/Qwen3-ASR-1.7B`、補正だけ戻す場合は `OLLAMA_MODEL=qwen3.8:27b-mlx` を環境変数で指定する。

## 残課題

- 両モデルが同じ箇所を同じように崩すケース（速い発話の小さい音など）は融合でも復元できない。
- 実音声（Kan本人の声）での評価は未実施。日常利用で残った誤字は文ごと記録し、辞書・置換ルールへ追加していく。
