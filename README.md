# voiceinput

Aqua Voice の代替として作る、Kan 専用の Mac 音声入力アプリ。

既存の個人文字起こしエンドポイント（Mac 上で常駐する Qwen3-ASR-1.7B ＋ 個人辞書補正）を使い、どのアプリでも **右 Option（Right Alt）キー** で音声入力できるようにする。

## 操作

- **長押し（プッシュトゥトーク）**: 右 Option を押している間だけ録音し、離すと文字起こししてカーソル位置へ挿入
- **ダブルプレス（ハンズフリー）**: 右 Option を2回素早く押すと録音を継続し、もう1回押すと停止して挿入

## 設計

詳細は [docs/SPEC.md](docs/SPEC.md)。要点:

- Swift 製メニューバー常駐アプリ（AppKit / SwiftUI 設定画面）
- キー監視は CGEventTap で右 Option（keycode 61）の flagsChanged を見る。録音中に他のキーが押されたら修飾キーコンビネーションとみなしてキャンセル
- 録音は AVAudioEngine、16kHz モノラルで一時ファイルへ
- 文字起こしは既存エンドポイント `POST /transcribe`（Mac の `~/transcribe-endpoint/`、Tailscale IP:8791、Bearer 認証）へ送信。トークンはリポジトリに入れず、アプリ設定 / ローカルファイルから読む
- 挿入はクリップボード経由＋ Cmd+V シミュレーション（元のクリップボードは復元する）。要アクセシビリティ権限
- 短い発話ではレイテンシ優先のため、LLM 補正（correct）の ON/OFF を設定可能にする

## 必要な権限

- マイク
- アクセシビリティ（キー監視と貼り付け）
- 入力監視（Input Monitoring）が必要になる場合はその案内も出す

## 状態

設計フェーズ。Mac 上で Xcode ビルドして検証する。
