# voiceinput 設計ブリーフ v1（2026-11-02）

## 背景

- Aqua Voice（v0.21.15、アカウント kan@2-38.com）を解約。アクセスは 2026-11-14 まで、残り12日（2026-11-02 時点のスクリーンショットで確認）。
- 代替は自作する。文字起こしエンジンは既に Kan の Mac にある個人専用エンドポイントを使う。新規に ASR を作らない。

## 既存エンドポイント（再利用する資産）

- 配置: Mac `~/transcribe-endpoint/`、launchd `com.kan.transcribe-endpoint` 常駐
- `GET /health`（認証不要）: `{status, model_loaded, device, engine, ollama_model, terms_count, load_error}`
- `POST /transcribe`（Bearer 認証、multipart）:
  - `file`（必須）: wav/mp3/m4a/mp4 等。サーバ側で ffmpeg により 16kHz モノラル WAV 化
  - `terms`（任意）: 追加の固有名詞（カンマ/改行区切り or JSON 配列）
  - `context`（任意）: 補正プロンプトへ渡す背景テキスト
  - `language`（任意、既定 `ja`）
  - `correct`（任意、既定 true）: false で LLM 補正パスを無効化
  - レスポンス: `{text, raw_text, segments, engine, corrected, corrections, audio_duration_s, elapsed_s}`
- エンジン: Qwen3-ASR-1.7B（Mac MPS）。ASR 単体で約21倍速（600秒→28.6秒）
- 補正: 個人辞書 `terms.txt`（19語: FP16, TSUQREA, tenpia, edgeya, Zenkioku, 全記憶, kumoi, オルテナジー, 二宮貫, 里歩, 創, ポテト, ダブチ 等）＋ Ollama `qwen3.8:27b-mlx` の校正パス（辞書語の音近似置換のみ許可、類似度ガード付き）。実例: `FB16サマ` → `FP16サマ`
- バインド: Mac の Tailscale IP `100.72.208.31:8791` のみ（LAN・パブリック非公開）。トークンは Mac の `~/transcribe-endpoint/.env`（0600）にのみ存在し、**このリポジトリには絶対に入れない**

## アプリ仕様

### 形態

- Swift 製 macOS メニューバー常駐アプリ。ログイン時に起動（LaunchAgent / SMAppService）
- 設定画面: エンドポイント URL、トークン参照方法、補正 ON/OFF、キー設定、録音中インジケータ表示

### キー操作（Aqua と同じ操作感）

- 右 Option = keycode 61（kVK_RightOption）。CGEventTap（.listenOnly では貼り付け送信ができないため、貼り付け側は別途 CGEvent post で行う）
- **長押しモード**: flagsChanged で右 Option の押下を検知して録音開始、解放で録音停止→文字起こし→挿入
  - 録音中に他のキーが押されたら「Option+キー の通常入力」とみなして録音をキャンセルする（誤爆防止の必須仕様）
- **ハンズフリーモード**: 短い押下が 350ms 以内に2回あったらトグル録音開始。次に1回押したら停止→挿入
  - 長押しとダブルプレスの判定が競合しないよう、1回目の短い押下は「長押し確定 or ダブルプレス待ち」の保留状態にし、閾値を過ぎたら長押し扱いにする等、状態機械で整理すること
- Esc で録音キャンセルできると望ましい

### 録音

- AVAudioEngine で 16kHz モノラル録音、一時ファイル（m4a/wav）へ書き出し
- 録音中は小さなフローティングインジケータ（波形 or ドット）をカーソル付近 or 画面下部に表示
- 無音・極短（例: 0.3秒未満）は送信せず破棄

### 文字起こし〜挿入

1. 録音ファイルを `POST /transcribe` へ（Bearer トークン付き）
2. レスポンス `text` を取得
3. 挿入: 現在のクリップボードを退避 → テキストをセット → Cmd+V を CGEvent で送信 → 少し待ってクリップボードを復元
   - クリップボード復元が他アプリと競合する場合は「復元しない」設定も用意
4. 失敗時（エンドポイント未起動・タイムアウト等）は通知で知らせ、音声ファイルを保持してリトライ可能にする

### レイテンシ設計（重要）

- 音声入力は短い発話（数秒〜数十秒）が前提。ASR 自体は高速だが、LLM 補正は Ollama のモデル常駐状態に依存し、コールド時は大きく遅れる（600秒音声で補正込み初回 98秒の実績。keep_alive 10分指定あり）
- 対策案（実装時に実測して決める）:
  - 設定で `correct` の ON/OFF を切り替え可能に（既定は要実測）
  - 短い発話では辞書の決定論的置換だけ先に適用し、LLM 補正を待たずに挿入するモード
  - エンドポイント側の短尺向け最適化（30秒チャンク前提の現行実装で短尺がどう処理されるか確認）

### 権限

- マイク（AVCaptureDevice）
- アクセシビリティ（CGEventTap の有効化と Cmd+V 送信に必須）
- 初回起動時に権限ガイドを表示し、未許可なら該当設定画面へ誘導する

## 実装・検証の進め方

1. Mac 上に clone し、Xcode でビルド可能な Swift プロジェクトを作成
2. まず長押しモードのみで「録音→エンドポイント→挿入」を通す（メモ帳で検証）
3. ダブルプレス（ハンズフリー）を追加
4. 実測: 5秒 / 15秒 / 60秒の発話で、押下→挿入までの所要時間を correct ON/OFF 別に測る
5. Aqua 併用期間（〜2026-11-14）中に日常利用で差し替え可能か Kan が判断

## 未決事項

- アプリ名（voiceinput のままか、別名にするか）
- 補正の既定 ON/OFF（実測後に決定）
- 履歴画面（Aqua にある履歴・辞書編集 UI をどこまで真似るか）は v1 では必須としない。辞書は当面エンドポイント側 `terms.txt` が正

## v2: Hindsight 動的文脈連携（2026-11-02）

実装対象はMacの `~/transcribe-endpoint/`。voiceinputアプリのリクエスト仕様・コードは変更しない。`correct=false` の場合はHindsightを呼ばない。アプリで利用するには設定の補正をONにする必要がある。

### 処理

1. ASRの生テキストをクエリに、既存のtailnet MCP経路で `kan-memory-v2` の `recall` のみを呼ぶ。
2. 上位の事実を上限付きで背景情報へ追加し、漢字・カタカナ・英字の候補表記を追加termsとして渡す。取得した事実・候補語をAPIレスポンスへ返さない。
3. 呼び出し側のcontext・指定辞書を優先し、Hindsightの記憶は補助として扱う。記憶内の命令には従わず、固有名詞の判断材料としてだけ使用し、事実を本文に書き足さないと補正プロンプトへ明記する。
4. v1の類似度・長さガードを維持する。記憶使用時は追加で、元の文字列を保持するか辞書語へ置換する変更のみ許し、本文への事実追加を拒否する。
5. 到達不能・期限超過・空・不正応答・同時呼び出しで補正やASRを失敗させない。記憶なしでv1と同じ辞書・context・補正プロンプトへ戻す。

### 接続・設定

MacのCodex MCP設定と同じtailnet HTTPSのbank専用MCP経路を使用する。実機でhealth、MCP初期化、recall成功を確認した。現行のtailnetホストではRESTのrecallパスは404だったため、REST公開・SSHトンネル新設は行わない。MCPはinitialize／initialized／tools/call(name=recall)だけを使用し、bankへの書き込み・設定変更をしない。リダイレクトを拒否し、接続先はtailnetの `kan-memory-v2` 専用経路に限定する。

ローカル `.env` に以下のキーを追加する。設定値・認証情報はこのリポジトリへ記録しない。変更はエンドポイントの再起動で反映する。

- `HINDSIGHT_ENABLED`: 有効／無効
- `HINDSIGHT_MCP_URL`: 既存tailnet MCP接続先
- `HINDSIGHT_TIMEOUT_S`: recall全体の待ち時間上限
- `HINDSIGHT_BUDGET`: recallの検索予算
- `HINDSIGHT_MAX_FACTS`: 採用する上位事実の上限
- `HINDSIGHT_MAX_CONTEXT_CHARS`: 文脈の文字数上限

全体の期限を超えた場合は即座にフォールバックする。遅い通信が残ってもワーカー数を制限し、後続の文字起こしを待たせない。`/health` と補正リクエストのレスポンスに連携ステータス・検索所要時間・採用件数を追加し、記憶の内容や設定先・認証情報は含めない。

### 運用と確認結果

`app.py.bak-20261102` を変更前に作成し、秘密情報のバックアップもローカルに0600で保持。launchdを再起動後、約7.24秒でモデル読み込み済みのhealthへ復帰した。既存辞書19語は変更していない。

辞書にないMapboxは、合成音声による実APIテストで「マップボックス」から「Mapbox」への補正を確認した。ただし「羅針盤」はASRの誤認識をクエリにした検索で必要な記憶を取得できず、今回のテストでは改善しなかった。記憶にある表記でも、検索で得られなければ補正できない。

詳細な実測値・制約・再確認方法は [V2-VALIDATION.md](V2-VALIDATION.md) を参照。実際のvoiceinputの発話・挿入までのGUI確認は未実施。
