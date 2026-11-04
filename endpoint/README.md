# kan-transcribe-endpoint (v1)

Kan専用の文字起こし HTTP API。Qwen3-ASR-1.7B（ローカル/MPS）＋ Ollama による個人辞書補正。
Tailscale 内のみ公開（100.72.208.31:8791）。launchd: `com.kan.transcribe-endpoint` で常駐。

## 使い方

トークンは `.env`（0600）の `TRANSCRIBE_TOKEN`。値はファイルから読むこと（共有・転記しない）。

```zsh
TOKEN=$(sed -n 's/^TRANSCRIBE_TOKEN=//p' ~/transcribe-endpoint/.env)

# ヘルスチェック（認証不要）
curl -s http://100.72.208.31:8791/health

# 文字起こし（wav/mp3/m4a/mp4 可）
curl -s -X POST http://100.72.208.31:8791/transcribe \
  -H "Authorization: Bearer $TOKEN" \
  -F file=@/path/to/audio.wav

# 任意パラメータ: terms（追加の固有名詞、カンマ区切り or JSON配列）, context（背景テキスト）,
# language（既定 ja）, correct（既定 true。false で補正なし）
curl -s -X POST http://100.72.208.31:8791/transcribe \
  -H "Authorization: Bearer $TOKEN" \
  -F file=@/path/to/meeting.m4a \
  -F 'terms=山田太郎,新規プロジェクト名' \
  -F 'context=週次の定例会議。予算の話が中心。'
```

レスポンス: `{text, raw_text, segments: [{start, end, text}], engine, corrected, corrections, audio_duration_s, elapsed_s}`
（start/end は秒。text は補正後、raw_text は ASR 生出力）

## 運用

- 起動/停止: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.kan.transcribe-endpoint.plist` / `launchctl bootout gui/$(id -u) com.kan.transcribe-endpoint`
- ログ: `logs/stdout.log`, `logs/stderr.log`
- 辞書: `terms.txt`（1行1語、再起動で反映）
- 手動起動（デバッグ用）: `./run.sh`

## v2: Hindsight動的文脈（2026-11-02）

correct有効時だけ、ASR生テキストを既存tailnet MCPのkan-memory-v2へrecallし、補助文脈と候補語を補正へ追加します。MCPツールはrecallのみでbankは変更しません。呼び出し側context・termsを優先し、既存の類似度ガードと置換限定ガードを適用します。

.envの設定キー（値を共有・転記しない）:
HINDSIGHT_ENABLED、HINDSIGHT_MCP_URL、HINDSIGHT_TIMEOUT_S、HINDSIGHT_BUDGET、HINDSIGHT_MAX_FACTS、HINDSIGHT_MAX_CONTEXT_CHARS。
設定変更はlaunchdサービスの再起動で反映します。到達不能・遅延・空結果は記憶なしのv1補正へフォールバックし、ASRを失敗させません。healthと補正時の応答には状態・時間・件数のみを表示します。

検証: `venv/bin/python tests/test_hindsight.py`。
合成音声の比較結果は `logs/v2-bench-*.json`。取得した記憶そのものは保存・ログ出力しません。

ロールバック: `.env`の連携フラグを無効化して再起動すればv1の補正プロンプトへ戻ります。コード全体を戻す場合は `app.py.bak-20261102` を `app.py` へ復元してください。設定バックアップは `.env.bak-20261102`（0600）です。再起動後はhealthのモデル読み込みと状態を確認してください。

voiceinputアプリは変更不要ですが、設定で補正ONが必要です。実機のキー・マイク・挿入確認はKanが行います。今回の合成音声ではMapboxの辞書外補正に成功しましたが、羅針盤の誤認識は生出力からの検索で記憶を取得できず改善しませんでした。総レイテンシの増加もあるため、日常利用で確認してください。

## v2.1: 動的辞書キャッシュ

既定はcacheモード。Kanの追加指示により上限1000語。起動時と定期バックグラウンド更新でHindsightをrecallし、ローカルOllamaで固有名詞・読み・種類を抽出します。元の記憶にある表記だけを検証して採用し、静的辞書の重複、一般名詞・文章を除きます。生成失敗時は前回の良キャッシュを維持します。`dynamic_terms.json` は0600・atomic renameで保存し、記憶の事実本文は保存しません。

.envのHINDSIGHT_MODEでcache／live／both／offを選択できます。モードはリクエストごとに再読込します。その他の設定は再起動で反映します。cacheでは発話時のネットワーク検索を行わず、読みの類似度で少数の候補だけを辞書へ追加します。offはv1と同じ補正処理、liveは従来v2です。correct=falseの場合はリクエスト時のHindsight処理をスキップします。

設定キー: HINDSIGHT_CACHE_MAX_TERMS、HINDSIGHT_CACHE_REFRESH_S、HINDSIGHT_CACHE_REQUEST_TERMS、HINDSIGHT_CACHE_LLM_TIMEOUT_S。値は共有・転記しないでください。

手動再生成: `venv/bin/python refresh_dynamic_terms.py`。バックグラウンドと同じ生成手順です。状態・件数だけを出力します。生成中に発話するとローカルLLMの計算資源を共有するため、更新が終わってからレイテンシを比較してください。

自動テスト: `venv/bin/python -m unittest discover -s tests -p 'test_*.py'`。

v2へ戻す場合は `app.py.bak-v2.1-20261102`、`hindsight_context.py.bak-v2.1-20261102` を元の名前へ復元し、必要に応じて `.env.bak-v2.1-20261102`（0600）も復元してサービスを再起動してください。コードを戻さずHINDSIGHT_MODEをoffにすれば静的辞書のみへ戻ります。

## v2.2: 精度改善（2026-11-04）

日常利用で残っていた「絶妙な誤字」への対応。詳細と検証記録は `docs/V22-VALIDATION.md`。

- 補正範囲を拡張: 固有名詞の置換に加え、文脈上明らかな同音異義語などの誤変換も最小限の文字変更で直す。言い換え・内容変更は引き続き禁止し、受理ガード（辞書置換 or ハンク単位の小修正のみ許可）で人名のフルネーム展開などを弾く。
- 決定的置換を導入: ラッシュ版／ラジン版→羅針盤、ギットハブ→GitHub、クロードコード→Claude Code、トランスエーアイ／トランスエイアイ→TransAI。LLM補正の前に適用し、LLM失敗時もこの置換は残る。
- 静的辞書を19語→25語に拡張（羅針盤、TransAI、髙松、Sono、GitHub、Claude Code を追加）。主要語には読みを付与してプロンプトへ渡す。
- 動的辞書キャッシュの読み込みを堅牢化: 静的辞書へ昇格した語がキャッシュ側と重複しても、キャッシュ全体を無効化しない。
- ASRへ辞書を context として渡すバイアスは実測で改善がなく不採用。

## リポジトリ管理（2026-11-04〜）

ソースの正は kandotrun/voiceinput リポジトリの `endpoint/` とする。本番は Mac の `~/transcribe-endpoint/`（launchd `com.kan.transcribe-endpoint`）。

反映手順:

1. リポジトリの `endpoint/` の内容を `~/transcribe-endpoint/` へコピーする（次項のローカル専用ファイルはコピー対象外）。
2. `launchctl kickstart -k gui/$(id -u)/com.kan.transcribe-endpoint` で再起動する。
3. `GET /health` でモデル読み込み・辞書件数・キャッシュ状態を確認する。

本番ローカル専用（リポジトリに含めない）:

- `.env`（トークン・設定値。絶対にコミットしない）
- `dynamic_terms.json`（Hindsight から自動生成されるキャッシュ。生成手順は v2.1 節を参照）
- `logs/`、`venv/`、`__pycache__/`、`*.bak-*`（世代バックアップは移行期間のみ保持し、今後のロールバックは Git 履歴を使う）

## v2.3: ASR総入れ替え＋二重ASR融合補正（2026-11-04）

「GitLab→GitHubラボ」のような固有名詞の誤りが残るとの指摘を受けた見直し。詳細と検証記録は `docs/V23-VALIDATION.md`。

- 主ASRを `neosophie/Qwen3-ASR-1.7B-JA`（日本語固有名詞特化ファインチューニング版）へ変更。環境変数 `ASR_MODEL_ID` で差し替え可能で、従来モデルにも戻せる。
- 参照ASRとして Whisper large-v3-turbo（mlx-whisper）を併走させ、補正LLMに主・参照の両方を渡して異なる箇所を選ばせる融合補正を導入。参照の失敗は主経路に影響しない。辞書（静的辞書全語）を Whisper の initial_prompt にも渡す。
- 補正LLMを `gemma4:31b-mlx` へ変更（同一プローブで qwen3.8:27b-mlx より融合の選別が正確だったため）。環境変数 `OLLAMA_MODEL` で変更可能。
- 静的辞書に技術用語11語を追加（GitLab、Cloudflare、Vercel、Supabase、Docker、Kubernetes、Notion、TypeScript、Next.js、Linear、Figma）。決定的置換にギットラボ→GitLab、スーパーベース→Supabase、ドーカー→Docker を追加。
- 追加依存: エンドポイントの venv に `mlx-whisper` が必要（`uv pip install --python venv/bin/python mlx-whisper`）。Whisper モデルは初回実行時に Hugging Face から取得される。
- 処理時間は1発話あたり概ね2〜6秒（融合のため v2.2 より長い）。精度優先で許容する運用とした。
