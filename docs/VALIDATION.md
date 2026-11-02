# v1 検証

## 自動確認（2026-11-02、Apple Silicon / Xcode 27.1）

- `xcodebuild -project VoiceInput.xcodeproj -scheme voiceinput -configuration Debug -derivedDataPath build build`: 成功
- `xcodebuild -project VoiceInput.xcodeproj -scheme voiceinput -configuration Release -derivedDataPath build build`: 成功
- `python3 Tests/run.py`: キー状態22項目、multipartのfile/language/correct、ダミーBearer、JSON text、HTTP 401、壊れたJSON、空文字、リダイレクト拒否、不正URLを検証
- `GET http://100.72.208.31:8791/health`: status=ok、model_loaded=trueを確認。音声の実送信は未検証
- macOS 27 SDKでは互換性のため使用しているAVAudioNodeの従来installTap APIに非推奨警告あり。ビルドを妨げない。AppIntents未使用のメタデータ抽出スキップ警告あり

## Kanによる実地確認（未実施）

- [ ] 固定場所から起動、メニューバー表示、日本語設定画面
- [ ] 初回マイク・アクセシビリティ案内、拒否・後から許可・再接続
- [ ] 必要な場合の入力監視、再起動後のキー監視
- [ ] 右Option長押し → 解放 → テキストエディットへ日本語挿入
- [ ] 短押し1回は送信なし、350ms以内の短押し2回 → ハンズフリー → 次の1回で停止
- [ ] 2回目が長押しの場合は解放で送信、350msを超えた2回目は独立した押下
- [ ] 左Optionだけでは開始しない、左右同時押し・Option+文字・他の修飾キーで誤挿入しない
- [ ] Escでキャンセル、キャンセル後の解放で送信しない
- [ ] インジケータ、別Space・フルスクリーンでの表示
- [ ] 0.3秒未満・無音破棄、小声や騒音での実用性、16kHz mono WAVの実録音
- [ ] 元クリップボード（テキスト・画像等）の復元、復元OFF、処理中に別コピーした場合
- [ ] 複数アプリへの貼り付け・挿入先の終了・Secure Input等での制限
- [ ] エンドポイント停止・不正トークン・タイムアウト → 通知・音声保持 → 設定から再試行
- [ ] 上書きトークン保存・既定へ戻す、通知拒否時の設定画面エラー表示
- [ ] ログイン起動の登録・解除、スリープ復帰・入力デバイス変更後のキャンセルと再録音

## レイテンシ実測（未実施）

correctの既定OFFは暫定。押下開始・録音停止・挿入完了を記録し、録音停止から挿入までと総時間を分けて比較する。モデルのコールド／ウォーム状態も記録する。

| 発話 | correct | 停止→挿入 | 押下→挿入 | モデル状態・結果 |
|---|---|---|---|---|
| 5秒 | OFF | 未測定 | 未測定 | |
| 5秒 | ON | 未測定 | 未測定 | |
| 15秒 | OFF | 未測定 | 未測定 | |
| 15秒 | ON | 未測定 | 未測定 | |
| 60秒 | OFF | 未測定 | 未測定 | |
| 60秒 | ON | 未測定 | 未測定 | |
