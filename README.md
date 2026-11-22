# Dettato Studio — dettato用GUI

[kobimusic/dettato](https://github.com/kobimusic/dettato)（多楽器 Audio→MIDI変換）のための、
NeuralNote風デスクトップGUI。Python + PySide6。

![見た目のイメージ](スクリーンショット準拠: ダークテーマ)

## 画面構成（スクショ再現）
- **上部バー**: 再生/停止、時刻表示、モデル/デバイス選択（CUDA/CPU/MPS）
- **ORIG — スライダー — MIDI**: 左端=オリジナル音源のみ、右端=MIDI合成音のみ。
  ドラッグでクロスフェードして聞き比べできる（再生中にリアルタイム切替OK）
- **左側 INSTRUMENTS**: トラック一覧。色ドット、ノート数・音域、**M**(ミュート)/**S**(ソロ)、音量スライダー
- **右上**: 波形（MIX WAVEFORM）。クリックでシーク
- **右下**: ピアノロール。縦=実際の音程（左に鍵盤、C位置表示）、横=時間（秒グリッド）。
  ノートは**トラックごとに色分け**、ベロシティで濃淡。クリックでシーク、白線が再生ヘッド
- **下部ステータス**: 楽器数・ノート数・音域・長さ、文字起こし中は TRANSCRIBING + 進捗

## セットアップ（venv）
```bat
setup_venv.bat   :: venv\ を作って requirements を一括インストール
run.bat          :: 起動（ウィンドウレス pythonw）
run_demo.bat     :: デモノートでUIだけ確認（音源なし）
```
手動の場合:
```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## モデルのダウンロード
アプリ右上 **Settings…** →「4モデルを一括ダウンロード」。
- 取得先: Hugging Face `kobimusic/dettato` / `-evidence` / `-grouper` / `-drums`（合計28.1M params、約110MB）
- 保存先は変更可能。既定は `models\`。中身は公式オフライン形式
  （`models\dettato\config.json + model.safetensors` 等）で、`DETTATO_WEIGHTS` に自動設定される
- DLしなくても、初回 Transcribe 時に dettato が自動DLする（Settingsは事前DL・オフライン運用用）

## 使い方
1. `Load audio file` に音源を読み込む（ドラッグ&ドロップ可、mp3/wav/flac/ogg/m4a）
2. **[T] / Transcribe** を押す → dettato が楽器別トラック+MIDIを生成
3. 再生ボタンで再生、**ORIG-MIDIスライダー**で原音⇔MIDIを聞き比べ
4. `Export MIDI out` / `Drag MIDI out` で .mid を保存（文字起こし時は音源の隣にも自動保存）
5. 既存の .mid を開くこともできる（「MIDIを開く…」/ ドロップ）— 再シンセして比較再生できる

## 仕組みメモ
- 文字起こし: `dettato.transcribe(path)` / `Dettato.from_pretrained(device)`、
  `result.tracks[].notes` は (onset秒, end秒, pitch, velocity)
- MIDI側の音: `synth.py` がノート列をピアノ風シンセ（倍音+減衰）でWAV化し、
  原音プレイヤーと同期再生。スライダーは2プレイヤーの音量クロスフェード
- ドラムトラックはノイズバーストで代用再生

## ファイル
- `app.py` メインGUI / `synth.py` MIDI→WAV合成 / `model_manager.py` モデルDL管理
- `requirements.txt` / `setup_venv.bat` / `run.bat` / `run_demo.bat`

## 配布形式（ランチャーexe + uv自動セットアップ）
配布フォルダの中身:
```
DettatoStudio.exe   ランチャー（PyInstaller onefile/windowed、stdlibのみ・軽量）
uv.exe              同梱のuv（公式 Windows x64版）
app.py / synth.py / model_manager.py / requirements.txt
LICENSE / NOTICE / README.md
```
- 起動するとターミナルは出ない。venv が無い/古い場合だけ小さなセットアップ
  ウィンドウが出て、同梱 uv で自動構築する:
  `uv venv venv --python 3.11` → `uv pip install -r requirements.txt`
  （uvがPython本体も自動取得するので、配布先にPythonが無くても動く）
- 初回起動時は venv 構築に続けて **モデルのダウンロード（4モデル約110MB）まで自動**で行い、そのまま本体が起動する。アプリ単体で起動した場合も、モデル未DLなら起動直後に自動DLが始まる。Settings からはいつでも再DL・保存先変更ができる。
構築済み＋モデルDL済みなら即本体が起動する。判定は `venv\.dettato_ready`
  （requirements.txt のSHA256）。requirementsを変えると次回起動時に再installされる
- `models\` と `venv\` は exe と同じフォルダに作られる
- ログ: セットアップは `launcher_setup.log`、ビルドは `build.log`
- ランチャーのビルド: `build_exe.bat`（ビルド専用の `.build-venv` を使う）

## オープンソースについて
- このGUIのコードは**書き下ろし**で、dettato本体のソースは**含んでいない**
  （pip依存として外部から入れるだけ）。なので **フォークではなく独立リポジトリでOK**
- ライセンスは dettato と同じ **Apache-2.0** に統一（`LICENSE` / `NOTICE` 同梱済み）
- モデル重みと uv.exe 本体はリポジトリに含めない（`.gitignore` 済み。
  uv は https://github.com/astral-sh/uv/releases から取得して同梱配布する）
- モデル重みは実行時にHFからDL。dettatoのモデルカードには一部非商用
  データセット由来の注記があるので、商用配布時はそちらも確認を
- PySide6はLGPL（venv内に動的ライブラリとして入る形）
