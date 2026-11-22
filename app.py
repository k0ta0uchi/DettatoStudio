#!/usr/bin/env python3
"""
Dettato Studio — dettato (kobimusic/dettato) 用 GUI
NeuralNote風ダークUI:
  左: トラック一覧（色/M/S/音量）  右上: 波形  右下: ピアノロール（トラック色分け）
  上部: ORIG <-> MIDI スライダーで原音とMIDI合成音をクロスフェード比較再生
  Settings... からモデルを一括ダウンロード可能
起動:
  python app.py            通常
  python app.py --demo     デモノートでUI確認（音源なし）
"""
import os, sys, math, tempfile, traceback
from pathlib import Path
from dataclasses import dataclass, field

# pythonw（窓なし起動）では stdout/stderr が None になり tqdm等が落ちるため塞ぐ
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="ignore")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="ignore")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

# exe化（PyInstaller frozen）時は exe のあるフォルダを基準にする。
# そうでない（python app.py）時はこのファイルのフォルダ。
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
# 起動した場所（exe/スクリプトと同じフォルダ）に models/ を作る
try:
    (APP_DIR / "models").mkdir(parents=True, exist_ok=True)
except Exception:
    pass

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QFileDialog, QProgressBar, QComboBox, QSpinBox,
    QScrollArea, QFrame, QMessageBox, QDialog, QTextEdit, QLineEdit,
    QCheckBox, QSizePolicy,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from model_manager import MODELS, model_status, default_weights_dir, download_all
from synth import synth_tracks_to_wav

TRACK_COLORS = ["#3B82F6","#A855F7","#22C55E","#F97316","#EC4899","#06B6D4",
                "#EAB308","#EF4444","#8B5CF6","#14B8A6","#F43F5E","#84CC16"]
NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
def pitch_name(m): return f"{NOTE_NAMES[m%12]}{m//12-1}"

@dataclass
class Track:
    name: str
    program: int = 0
    is_drum: bool = False
    notes: np.ndarray = field(default_factory=lambda: np.zeros((0,4)))  # onset,end,pitch,vel
    color: str = "#3B82F6"
    muted: bool = False
    solo: bool = False
    volume: float = 0.85
    @property
    def range_str(self):
        if len(self.notes)==0: return "-"
        ps = self.notes[:,2].astype(int)
        return f"{pitch_name(int(ps.min()))}-{pitch_name(int(ps.max()))}"

# ---------------- Waveform ----------------
class WaveformWidget(QWidget):
    seek_requested = Signal(float)  # ratio 0-1
    def __init__(self):
        super().__init__()
        self.peaks = None; self.play_ratio = 0.0; self.filename = ""
        self.setMinimumHeight(110)
    def set_audio(self, path):
        import soundfile as sf
        info = sf.info(path)
        data, _ = sf.read(path, always_2d=True)
        mono = data.mean(axis=1)
        n_buckets = 1200
        if len(mono) > n_buckets:
            trim = len(mono)//n_buckets*n_buckets
            self.peaks = np.abs(mono[:trim].reshape(n_buckets,-1)).max(axis=1)
        else:
            self.peaks = np.abs(mono)
        self.filename = Path(path).name
        self.update()
    def clear(self): self.peaks=None; self.filename=""; self.update()
    def mousePressEvent(self, e):
        if self.peaks is not None:
            self.seek_requested.emit(max(0,min(1, e.position().x()/max(1,self.width()))))
    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w,h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#0E0E14"))
        if self.peaks is None:
            # 空状態（スクショ再現：点線枠＋ボタンは親側で中央配置するためここは枠のみ）
            p.setPen(QPen(QColor("#2A2A3A"),1,Qt.DashLine))
            p.drawRoundedRect(8,8,w-16,h-16,8,8)
            p.setPen(QColor("#55556A")); p.setFont(QFont("Segoe UI",8))
            p.drawText(self.rect().adjusted(0,28,0,0), Qt.AlignHCenter, "OR DROP A FILE HERE")
            return
        p.setPen(QColor("#6B7280")); p.setFont(QFont("Segoe UI",7))
        p.drawText(10,14, f"MIX WAVEFORM   {self.filename}")
        mid = h//2 + 6; max_amp = float(self.peaks.max()) or 1.0
        p.setPen(QColor("#9CA3AF"))
        bw = w / len(self.peaks)
        for i, v in enumerate(self.peaks):
            amp = (v/max_amp)*(h*0.38)
            p.drawLine(int(i*bw), int(mid-amp), int(i*bw), int(mid+amp))
        # 再生ヘッド
        x = int(self.play_ratio*w)
        p.setPen(QPen(QColor("#FFFFFF"),1)); p.drawLine(x,0,x,h)
        # 時間目盛りは親が持つ duration で別途描かない（簡易）

# ---------------- Piano Roll ----------------
class PianoRollWidget(QWidget):
    seek_requested = Signal(float)
    def __init__(self):
        super().__init__()
        self.tracks: list[Track] = []
        self.duration = 10.0
        self.play_ratio = 0.0
        self.px_per_sec = 90.0
        self.row_h = 13
        self.key_w = 52
        self.pitch_high = 96  # C7
        self.pitch_low = 24   # C1
        self.setMinimumHeight(420)
        self.setMouseTracking(True)
        self._hover = ""
    @property
    def content_w(self): return int(self.duration*self.px_per_sec)
    def total_size(self):
        return QSize(self.key_w+self.content_w, (self.pitch_high-self.pitch_low+1)*self.row_h)
    def mousePressEvent(self, e):
        x = e.position().x()-self.key_w
        if x>=0 and self.duration>0:
            self.seek_requested.emit(max(0,min(1, x/self.content_w if self.content_w else 0)))
    def paintEvent(self, _):
        p = QPainter(self); w,h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#0A0A0F"))
        rows = self.pitch_high-self.pitch_low+1
        # 横グリッド＋鍵盤
        for i in range(rows):
            pitch = self.pitch_high - i
            y = i*self.row_h
            is_black = (pitch%12) in (1,3,6,8,10)
            is_c = (pitch%12)==0
            # 行背景
            p.fillRect(self.key_w, y, w-self.key_w, self.row_h,
                       QColor("#101018") if is_black else QColor("#0C0C12"))
            if is_c:
                p.setPen(QPen(QColor("#23232F"),1)); p.drawLine(self.key_w,y+self.row_h-1,w,y+self.row_h-1)
            # 鍵盤
            p.fillRect(0,y,self.key_w,self.row_h, QColor("#111") if is_black else QColor("#E8E8E8"))
            p.setPen(QColor("#333") if not is_black else QColor("#888"))
            if is_c:
                p.setFont(QFont("Segoe UI",7)); p.setPen(QColor("#666"))
                p.drawText(34,y+self.row_h-2, f"C{pitch//12-1}")
            p.setPen(QPen(QColor("#2A2A35"),1)); p.drawLine(0,y+self.row_h-1,self.key_w,y+self.row_h-1)
        # 縦グリッド（1秒ごと）
        p.setPen(QPen(QColor("#1C1C28"),1))
        for s in range(int(self.duration)+1):
            x = self.key_w + int(s*self.px_per_sec)
            if x>w: break
            p.drawLine(x,0,x,h)
            p.setPen(QColor("#55556A")); p.setFont(QFont("Segoe UI",7))
            p.drawText(x+3,12, f"0:{s:02d}" if s<60 else f"{s//60}:{s%60:02d}")
            p.setPen(QPen(QColor("#1C1C28"),1))
        # ノート（トラック色分け）
        has_solo = any(t.solo for t in self.tracks)
        for t in self.tracks:
            if t.muted or (has_solo and not t.solo): continue
            col = QColor(t.color)
            for onset,end,pitch,vel in t.notes:
                pitch=int(pitch)
                if pitch<self.pitch_low or pitch>self.pitch_high: continue
                x = self.key_w + int(onset*self.px_per_sec)
                nw = max(4, int((end-onset)*self.px_per_sec)-1)
                y = (self.pitch_high-pitch)*self.row_h+1
                c = QColor(col); c.setAlpha(int(120+135*min(1,(vel or 90)/127)))
                p.fillRect(x,y,nw,self.row_h-2,c)
        # 再生ヘッド
        x = self.key_w + int(self.play_ratio*self.content_w)
        p.setPen(QPen(QColor("#FFFFFF"),1)); p.drawLine(x,0,x,h)

# ---------------- Workers ----------------
class TranscribeWorker(QThread):
    done = Signal(object); failed = Signal(str); log = Signal(str)
    def __init__(self, audio_path, device, weights_dir):
        super().__init__(); self.audio_path=audio_path; self.device=device; self.weights_dir=weights_dir
    def run(self):
        try:
            if self.weights_dir: os.environ["DETTATO_WEIGHTS"]=str(self.weights_dir)
            import dettato
            self.log.emit("モデル読み込み中…（初回はDLが走ります）")
            try:
                model = dettato.Dettato.from_pretrained(self.device)
                result = model.transcribe(self.audio_path)
            except Exception:
                result = dettato.transcribe(self.audio_path)
            self.done.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())

class DownloadWorker(QThread):
    progress = Signal(int,str); log = Signal(str); done = Signal(str); failed = Signal(str)
    def __init__(self, weights_dir): super().__init__(); self.weights_dir=Path(weights_dir)
    def run(self):
        try:
            r = download_all(self.weights_dir,
                             progress_cb=lambda p,m: self.progress.emit(p,m),
                             log_cb=lambda m: self.log.emit(m))
            self.done.emit(r)
        except Exception:
            self.failed.emit(traceback.format_exc())

# ---------------- Model Dialog ----------------
class ModelDialog(QDialog):
    def __init__(self, parent, weights_dir: Path):
        super().__init__(parent)
        self.setWindowTitle("Models — dettato weights")
        self.resize(560,420); self.weights_dir=weights_dir; self.worker=None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("dettatoは4つのモデル（合計28.1M params）をHugging Faceから取得します。\nDL先フォルダが DETTATO_WEIGHTS として使われます。"))
        row = QHBoxLayout()
        self.path_edit = QLineEdit(str(weights_dir)); row.addWidget(self.path_edit,1)
        b = QPushButton("参照…"); b.clicked.connect(self._browse); row.addWidget(b)
        lay.addLayout(row)
        self.status_label = QLabel(""); lay.addWidget(self.status_label)
        self.refresh_status()
        self.bar = QProgressBar(); self.bar.setRange(0,100); lay.addWidget(self.bar)
        self.logbox = QTextEdit(); self.logbox.setReadOnly(True); lay.addWidget(self.logbox,1)
        btns = QHBoxLayout()
        self.dl_btn = QPushButton("⬇  4モデルを一括ダウンロード"); self.dl_btn.clicked.connect(self._download)
        close_btn = QPushButton("閉じる"); close_btn.clicked.connect(self.accept)
        btns.addWidget(self.dl_btn); btns.addStretch(1); btns.addWidget(close_btn); lay.addLayout(btns)
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self,"モデル保存先", self.path_edit.text())
        if d: self.path_edit.setText(d); self.refresh_status()
    def refresh_status(self):
        wd = Path(self.path_edit.text())
        lines=[]
        for label, sub, ok, size in model_status(wd):
            lines.append(f"{'✓ DL済み' if ok else '― 未DL'}  {label}  ({size} MB)")
        self.status_label.setText("\n".join(lines))
    def _download(self):
        self.dl_btn.setEnabled(False)
        self.worker = DownloadWorker(Path(self.path_edit.text()))
        self.worker.progress.connect(lambda p,m: (self.bar.setValue(p), self.status_label.setText(m)))
        self.worker.log.connect(lambda m: self.logbox.append(m))
        self.worker.done.connect(lambda r: (self.logbox.append(f"完了: {r}"), self.refresh_status(), self.dl_btn.setEnabled(True)))
        self.worker.failed.connect(lambda e: (self.logbox.append(e), self.dl_btn.setEnabled(True)))
        self.worker.start()
    def selected_dir(self): return Path(self.path_edit.text())

# ---------------- Track Item ----------------
class TrackItem(QWidget):
    changed = Signal()
    def __init__(self, track: Track):
        super().__init__(); self.track=track
        lay = QVBoxLayout(self); lay.setContentsMargins(10,8,10,8); lay.setSpacing(4)
        top = QHBoxLayout()
        dot = QLabel("●"); dot.setStyleSheet(f"color:{track.color}; font-size:14px;")
        name = QLabel(track.name); name.setStyleSheet("color:#E5E7EB; font-weight:600;")
        top.addWidget(dot); top.addWidget(name); top.addStretch(1)
        self.m_btn = QPushButton("M"); self.s_btn = QPushButton("S")
        for btn, on in ((self.m_btn, track.muted),(self.s_btn, track.solo)):
            btn.setFixedSize(22,20); btn.setCheckable(True); btn.setChecked(on)
            btn.setStyleSheet("QPushButton{background:#1F1F2A;color:#9CA3AF;border-radius:3px;} QPushButton:checked{background:#3B82F6;color:white;}")
        self.m_btn.toggled.connect(lambda v: (setattr(track,'muted',v), self.changed.emit()))
        self.s_btn.toggled.connect(lambda v: (setattr(track,'solo',v), self.changed.emit()))
        top.addWidget(self.m_btn); top.addWidget(self.s_btn); lay.addLayout(top)
        sub = QLabel(f"{len(track.notes)} notes · {track.range_str}" + (" · DRUMS" if track.is_drum else f" · Prg {track.program}"))
        sub.setStyleSheet("color:#6B7280; font-size:11px;"); lay.addWidget(sub)
        self.vol = QSlider(Qt.Horizontal); self.vol.setRange(0,100); self.vol.setValue(int(track.volume*100))
        self.vol.setStyleSheet(f"QSlider::handle:horizontal{{background:{track.color}; width:10px;}}")
        self.vol.valueChanged.connect(lambda v: (setattr(track,'volume',v/100), self.changed.emit()))
        lay.addWidget(self.vol)
        self.setStyleSheet("background:#12121A; border-bottom:1px solid #1E1E2A;")

# ---------------- Main Window ----------------
class MainWindow(QMainWindow):
    def __init__(self, demo=False):
        super().__init__()
        self.setWindowTitle("Dettato Studio — dettato GUI")
        self.resize(1280,820)
        self.tracks: list[Track]=[]
        self.audio_path=None; self.duration=0.0; self.midi_path=None
        self.weights_dir = default_weights_dir(APP_DIR)
        self._midi_wav=None; self._result=None
        self._build_ui()
        self._setup_players()
        if demo: self._load_demo()
    # --- UI構築（スクショ再現） ---
    def _build_ui(self):
        self.setStyleSheet("""
            QMainWindow, QWidget{background:#0B0B10; color:#D1D5DB; font-family:'Segoe UI','Yu Gothic UI',sans-serif;}
            QPushButton{background:#17171F; color:#D1D5DB; border:1px solid #262633; border-radius:5px; padding:5px 10px;}
            QPushButton:hover{background:#1F1F2A;} QPushButton:disabled{color:#4B5563;}
            QComboBox, QSpinBox, QLineEdit{background:#17171F; color:#E5E7EB; border:1px solid #262633; border-radius:5px; padding:4px 8px;}
            QScrollArea{border:none;} QProgressBar{background:#17171F; border:1px solid #262633; border-radius:4px; text-align:center;}
            QProgressBar::chunk{background:#3B82F6;}
        """)
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        # 黄色バー（Audio input is muted…）は機能しない飾りだったため非表示（2026-11-22 Kota希望）
        # ヘッダー
        head = QHBoxLayout(); head.setContentsMargins(12,8,12,8)
        title = QLabel("●  DETTATO <span style='color:#6B7280'>STUDIO v2 — dettato</span>"); title.setStyleSheet("font-size:14px; font-weight:700; color:#F3F4F6;")
        head.addWidget(title); head.addSpacing(18)
        self.btn_to_start = QPushButton("⏮"); self.btn_play = QPushButton("▶"); self.btn_eye = QPushButton("👁")
        for b in (self.btn_to_start, self.btn_play, self.btn_eye): b.setFixedWidth(34)
        self.btn_play.clicked.connect(self._toggle_play); self.btn_to_start.clicked.connect(lambda: self._seek(0))
        head.addWidget(self.btn_to_start); head.addWidget(self.btn_play); head.addWidget(self.btn_eye)
        self.btn_transcribe_head = QPushButton("[T]"); self.btn_transcribe_head.setStyleSheet("background:#1E3A5F; color:#93C5FD;")
        self.btn_transcribe_head.clicked.connect(self._transcribe); head.addWidget(self.btn_transcribe_head)
        rec = QLabel(" ● "); rec.setStyleSheet("color:#EF4444;"); head.addWidget(rec)
        self.time_label = QLabel("00:00.00  /  --:--.--"); self.time_label.setStyleSheet("font-size:14px; color:#E5E7EB; padding:0 10px;")
        head.addWidget(self.time_label)
        self.device_combo = QComboBox(); self.device_combo.addItems(["MODEL: LARGE · CUDA","MODEL: LARGE · CPU","MODEL: LARGE · MPS"])
        head.addWidget(self.device_combo); head.addSpacing(14)
        # ★ ORIG-MIDI スライダー
        head.addWidget(QLabel("ORIG"))
        self.mix_slider = QSlider(Qt.Horizontal); self.mix_slider.setRange(0,100); self.mix_slider.setValue(100); self.mix_slider.setFixedWidth(150)
        self.mix_slider.setToolTip("左=オリジナル音源 / 右=MIDI（合成音）。ドラッグで聞き比べ")
        self.mix_slider.valueChanged.connect(self._apply_mix)
        head.addWidget(self.mix_slider); head.addWidget(QLabel("MIDI")); head.addSpacing(10)
        head.addWidget(QLabel("🔊"))
        self.master_vol = QSlider(Qt.Horizontal); self.master_vol.setRange(0,100); self.master_vol.setValue(80); self.master_vol.setFixedWidth(90)
        self.master_vol.valueChanged.connect(self._apply_mix); head.addWidget(self.master_vol)
        self.vol_label = QLabel("-24.6"); head.addWidget(self.vol_label)
        self.mute_btn = QPushButton("🔇 MUTE"); self.mute_btn.setCheckable(True); self.mute_btn.toggled.connect(self._apply_mix); head.addWidget(self.mute_btn)
        settings_btn = QPushButton("Settings…"); settings_btn.setToolTip("モデル管理（ダウンロード）")
        settings_btn.clicked.connect(self._open_models); head.addWidget(settings_btn)
        root.addLayout(head)
        # サブバー
        sub = QHBoxLayout(); sub.setContentsMargins(12,4,12,4)
        sub.addStretch(1); sub.addWidget(QLabel("EXPORT TEMPO"))
        self.tempo_spin = QSpinBox(); self.tempo_spin.setRange(30,300); self.tempo_spin.setValue(120); sub.addWidget(self.tempo_spin)
        exp_btn = QPushButton("📁 Export MIDI out"); exp_btn.clicked.connect(self._export_midi); sub.addWidget(exp_btn)
        self.drag_btn = QPushButton("⬇ Drag MIDI out"); self.drag_btn.setStyleSheet("border:1px solid #3B82F6; color:#93C5FD;")
        self.drag_btn.clicked.connect(self._export_midi); sub.addWidget(self.drag_btn)
        clr = QPushButton("🗑"); clr.clicked.connect(self._clear); sub.addWidget(clr)
        root.addLayout(sub)
        # 本体: 左トラック + 右（波形+ピアノロール）
        body = QHBoxLayout(); body.setSpacing(0)
        left = QVBoxLayout(); left_w = QWidget(); left_w.setFixedWidth(210); left_w.setLayout(left)
        lh = QHBoxLayout(); lh.addWidget(QLabel("INSTRUMENTS")); self.inst_count = QLabel("0"); lh.addWidget(self.inst_count)
        add_btn = QPushButton("+"); add_btn.setFixedWidth(24); add_btn.clicked.connect(self._load_midi_dialog); lh.addWidget(add_btn); left.addLayout(lh)
        self.track_scroll = QScrollArea(); self.track_scroll.setWidgetResizable(True)
        self.track_container = QWidget(); self.track_layout = QVBoxLayout(self.track_container)
        self.track_layout.setContentsMargins(0,0,0,0); self.track_layout.addStretch(1)
        self.track_scroll.setWidget(self.track_container); left.addWidget(self.track_scroll,1)
        left.addWidget(QLabel("MASTER")); body.addWidget(left_w)
        # 右
        right = QVBoxLayout(); right.setSpacing(0)
        self.file_label = QLabel(""); self.file_label.setStyleSheet("color:#9CA3AF; padding:2px 8px;"); right.addWidget(self.file_label)
        wave_wrap = QWidget(); wave_lay = QVBoxLayout(wave_wrap); wave_lay.setContentsMargins(0,0,0,0)
        self.wave = WaveformWidget(); self.wave.seek_requested.connect(self._seek_ratio); wave_lay.addWidget(self.wave)
        self.load_btn = QPushButton("📁  Load audio file"); self.load_btn.setStyleSheet("border:1px solid #3B82F6; color:#93C5FD; padding:7px 18px;")
        self.load_btn.clicked.connect(self._load_audio_dialog)
        # 波形の上に重ねる代わりに下に小さく配置（ドラッグ&ドロップはウィンドウ全体で受付）
        wave_btn_row = QHBoxLayout(); wave_btn_row.addStretch(1); wave_btn_row.addWidget(self.load_btn)
        wave_btn_row.addWidget(QPushButton("MIDIを開く…", clicked=self._load_midi_dialog)); wave_btn_row.addStretch(1)
        wave_lay.addLayout(wave_btn_row); right.addWidget(wave_wrap)
        # ピアノロール（横スクロール）
        self.roll_scroll = QScrollArea(); self.roll_scroll.setWidgetResizable(False); self.roll_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.roll = PianoRollWidget(); self.roll.seek_requested.connect(self._seek_ratio)
        self.roll_scroll.setWidget(self.roll); right.addWidget(self.roll_scroll,1)
        self.transcribe_btn = QPushButton("🎵  Transcribe"); self.transcribe_btn.setStyleSheet("border:1px solid #3B82F6; color:#93C5FD; padding:8px 22px; font-size:13px;")
        self.transcribe_btn.clicked.connect(self._transcribe)
        trow = QHBoxLayout(); trow.addStretch(1); trow.addWidget(self.transcribe_btn); trow.addStretch(1); right.addLayout(trow)
        body.addLayout(right,1); root.addLayout(body,1)
        # ステータスバー
        status = QHBoxLayout(); status.setContentsMargins(12,5,12,5)
        self.status_left = QLabel("0 instruments  ·  0 notes"); status.addWidget(self.status_left); status.addStretch(1)
        self.progress_label = QLabel(""); status.addWidget(self.progress_label)
        self.progress_bar = QProgressBar(); self.progress_bar.setFixedWidth(180); self.progress_bar.setVisible(False); status.addWidget(self.progress_bar)
        self.progress_pct = QLabel(""); status.addWidget(self.progress_pct)
        root.addLayout(status)
        self.setAcceptDrops(True)
        # 再生位置タイマー
        self.timer = QTimer(self); self.timer.setInterval(50); self.timer.timeout.connect(self._tick)
    # --- プレイヤー ---
    def _setup_players(self):
        self.orig_player = QMediaPlayer(self); self.orig_out = QAudioOutput(self); self.orig_player.setAudioOutput(self.orig_out)
        self.midi_player = QMediaPlayer(self); self.midi_out = QAudioOutput(self); self.midi_player.setAudioOutput(self.midi_out)
        self._apply_mix()
    def _apply_mix(self):
        mix = self.mix_slider.value()/100 if hasattr(self,'mix_slider') else 1.0
        master = 0.0 if self.mute_btn.isChecked() else (self.master_vol.value()/100)
        self.orig_out.setVolume((1-mix)*master); self.midi_out.setVolume(mix*master)
        self.vol_label.setText(f"{mix*100:.0f}% MIDI")
    def _tick(self):
        dur = self.orig_player.duration() or self.midi_player.duration()
        pos = max(self.orig_player.position(), self.midi_player.position())
        if dur>0:
            ratio = pos/dur
            self.wave.play_ratio = ratio; self.wave.update()
            self.roll.play_ratio = ratio; self.roll.update()
            self.time_label.setText(f"{pos/60000:02.0f}:{pos/1000%60:05.2f}  /  {dur/60000:02.0f}:{dur/1000%60:05.2f}")
    def _toggle_play(self):
        playing = self.orig_player.playbackState()==QMediaPlayer.PlayingState or self.midi_player.playbackState()==QMediaPlayer.PlayingState
        if playing:
            self.orig_player.pause(); self.midi_player.pause(); self.btn_play.setText("▶"); self.timer.stop()
        else:
            if self.audio_path: self.orig_player.play()
            if self._midi_wav: self.midi_player.play()
            self.btn_play.setText("⏸"); self.timer.start()
    def _seek(self, ms):
        self.orig_player.setPosition(ms); self.midi_player.setPosition(ms)
    def _seek_ratio(self, ratio):
        dur = self.orig_player.duration() or self.midi_player.duration() or int(self.duration*1000)
        self._seek(int(ratio*dur))
    # --- ファイル ---
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if Path(p).suffix.lower() in (".mid",".midi"): self._load_midi(p)
            else: self._load_audio(p)
            break
    def _load_audio_dialog(self):
        f,_ = QFileDialog.getOpenFileName(self,"音源ファイル","", "Audio (*.mp3 *.wav *.flac *.ogg *.m4a);;All (*)")
        if f: self._load_audio(f)
    def _load_audio(self, path):
        self.audio_path=path
        try:
            import soundfile as sf; self.duration = float(sf.info(path).duration)
            self.wave.set_audio(path)
        except Exception as ex:
            QMessageBox.warning(self,"波形読み込み失敗", f"soundfileで読めませんでした（再生は試みます）\n{ex}")
            self.duration=0
        self.file_label.setText(Path(path).name)
        self.orig_player.setSource(QUrl.fromLocalFile(path))
        self._resize_roll(); self._update_status()
    def _load_midi_dialog(self):
        f,_ = QFileDialog.getOpenFileName(self,"MIDIファイル","", "MIDI (*.mid *.midi)")
        if f: self._load_midi(f)
    def _load_midi(self, path):
        try:
            import mido
            mid = mido.MidiFile(path); tracks=[]
            for i, tr in enumerate(mid.tracks):
                notes=[]; active={}; t=0; name=f"Track {i}"; program=0
                for msg in tr:
                    t += msg.time
                    if msg.type=="track_name": name=msg.name
                    if msg.type=="program_change": program=msg.program
                    sec = mido.tick2second(t, mid.ticks_per_beat, 500000)
                    if msg.type=="note_on" and msg.velocity>0: active[msg.note]=(sec,msg.velocity)
                    elif msg.type in ("note_off",) or (msg.type=="note_on" and msg.velocity==0):
                        if msg.note in active:
                            s,v = active.pop(msg.note); notes.append([s,sec,msg.note,v])
                if notes:
                    tracks.append(Track(name=name, program=program, notes=np.array(notes), color=TRACK_COLORS[len(tracks)%len(TRACK_COLORS)]))
            self._set_tracks(tracks); self.midi_path=path
            if self.duration==0 and tracks:
                self.duration = float(max(t.notes[:,1].max() for t in tracks))
            self._after_tracks_changed()
        except Exception as ex:
            QMessageBox.critical(self,"MIDI読み込み失敗", str(ex))
    # --- dettato ---
    def _device(self):
        return ["cuda","cpu","mps"][self.device_combo.currentIndex()]
    def _transcribe(self):
        if not self.audio_path:
            QMessageBox.information(self,"Transcribe","先に音源ファイルを読み込んでください"); return
        # モデル未DLなら案内
        from model_manager import all_downloaded
        if not all_downloaded(self.weights_dir):
            r = QMessageBox.question(self,"モデル未ダウンロード",
                "モデルがまだ全部DLされていません。\nSettingsからDLしますか？（DL済みなら初回推論時に自動DLもされます）",
                QMessageBox.Yes|QMessageBox.No)
            if r==QMessageBox.Yes: self._open_models(); return
        self.progress_bar.setVisible(True); self.progress_bar.setRange(0,0)
        self.progress_label.setText("TRANSCRIBING"); self.transcribe_btn.setEnabled(False)
        self.worker = TranscribeWorker(self.audio_path, self._device(), str(self.weights_dir))
        self.worker.done.connect(self._on_transcribed); self.worker.failed.connect(self._on_failed)
        self.worker.log.connect(lambda m: self.progress_label.setText(m)); self.worker.start()
    def _on_transcribed(self, result):
        self._result=result; tracks=[]
        for i, tr in enumerate(result.tracks):
            notes = np.array(tr.notes, dtype=float) if len(tr.notes) else np.zeros((0,4))
            tracks.append(Track(name=str(tr.name), program=int(getattr(tr,'program',0) or 0),
                                is_drum=bool(getattr(tr,'is_drum',False)), notes=notes,
                                color=TRACK_COLORS[i%len(TRACK_COLORS)]))
        self._set_tracks(tracks); self._after_tracks_changed()
        self.progress_bar.setVisible(False); self.progress_label.setText(""); self.transcribe_btn.setEnabled(True)
        # 自動で .mid も隣に保存
        try:
            out = str(Path(self.audio_path).with_suffix(".mid")); result.save_midi(out); self.midi_path=out
        except Exception: pass
    def _on_failed(self, err):
        self.progress_bar.setVisible(False); self.progress_label.setText(""); self.transcribe_btn.setEnabled(True)
        QMessageBox.critical(self,"文字起こし失敗", err[-3000:])
    # --- トラック管理 ---
    def _set_tracks(self, tracks):
        self.tracks=tracks; self.roll.tracks=tracks
        # 左リスト再構築
        while self.track_layout.count()>1:
            item=self.track_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for t in tracks:
            w = TrackItem(t); w.changed.connect(self._after_tracks_changed_light); self.track_layout.insertWidget(self.track_layout.count()-1, w)
        self.inst_count.setText(str(len(tracks))); self._resize_roll(); self._update_status()
    def _resize_roll(self):
        if self.tracks:
            alln = np.concatenate([t.notes for t in self.tracks if len(t.notes)])
            if len(alln):
                self.roll.pitch_low = max(12, int(alln[:,2].min())-4); self.roll.pitch_high = min(108, int(alln[:,2].max())+4)
                self.duration = max(self.duration, float(alln[:,1].max()))
        self.roll.duration = max(self.duration, 1.0)
        sz = self.roll.total_size(); self.roll.resize(sz); self.roll.update()
    def _update_status(self):
        total = sum(len(t.notes) for t in self.tracks)
        rng = "-"
        if self.tracks and total:
            alln = np.concatenate([t.notes for t in self.tracks if len(t.notes)])
            rng = f"{pitch_name(int(alln[:,2].min()))} - {pitch_name(int(alln[:,2].max()))}"
        self.status_left.setText(f"{len(self.tracks)} instruments  ·  {total} notes  ·  Large model  ·  {rng}  ·  {self.duration:.2f} s")
    def _after_tracks_changed_light(self):
        self.roll.update(); self._resynth_midi()
    def _after_tracks_changed(self):
        self._resize_roll(); self._update_status(); self._resynth_midi()
    def _resynth_midi(self):
        if not self.tracks: return
        try:
            fd, tmp = tempfile.mkstemp(suffix=".wav"); os.close(fd)
            synth_tracks_to_wav([{"notes":t.notes,"muted":t.muted,"solo":t.solo,"volume":t.volume,"is_drum":t.is_drum} for t in self.tracks],
                                duration=max(self.duration,1.0), out_path=tmp)
            self._midi_wav=tmp; self.midi_player.setSource(QUrl.fromLocalFile(tmp))
        except Exception as ex:
            print("MIDI synth failed:", ex)
    def _export_midi(self):
        if self._result is not None:
            f,_ = QFileDialog.getSaveFileName(self,"MIDIを保存","","MIDI (*.mid)")
            if f: self._result.save_midi(f)
            return
        if self.midi_path and Path(self.midi_path).exists():
            f,_ = QFileDialog.getSaveFileName(self,"MIDIを保存","", "MIDI (*.mid)")
            if f: import shutil; shutil.copy(self.midi_path, f)
            return
        if not self.tracks: QMessageBox.information(self,"Export","書き出せるノートがありません"); return
        f,_ = QFileDialog.getSaveFileName(self,"MIDIを保存","","MIDI (*.mid)")
        if not f: return
        import mido
        mid = mido.MidiFile(ticks_per_beat=480)
        for t in self.tracks:
            tr = mido.MidiTrack(); mid.tracks.append(tr)
            tr.append(mido.MetaMessage("track_name", name=t.name, time=0))
            if t.is_drum: ch=9
            else:
                ch = mid.tracks.index(tr)-1 if False else 0
                tr.append(mido.Message("program_change", program=t.program, time=0))
            events=[]
            for onset,end,pitch,vel in t.notes:
                events.append((float(onset),"on",int(pitch),int(vel or 90)))
                events.append((float(end),"off",int(pitch),0))
            events.sort(key=lambda x:x[0]); last=0.0
            for sec,kind,pitch,vel in events:
                dt = mido.second2tick(max(0,sec-last),480, mido.bpm2tempo(120)); last=sec
                tr.append(mido.Message("note_on" if kind=="on" else "note_off", note=pitch, velocity=vel, time=int(dt), channel=9 if t.is_drum else 0))
        mid.save(f)
    def _clear(self):
        self.tracks=[]; self._set_tracks([]); self.wave.clear(); self.file_label.setText(""); self.audio_path=None; self.duration=0; self._update_status()
    def _open_models(self):
        dlg = ModelDialog(self, self.weights_dir)
        if dlg.exec(): self.weights_dir = dlg.selected_dir()
    def _load_demo(self):
        rng = np.random.default_rng(7); tracks=[]
        for ti,(name,base) in enumerate([("Piano",60),("Bass",36),("Strings",67)]):
            notes=[]; t=0.2
            for _ in range(28):
                p = base + int(rng.integers(-5,9)); d = float(rng.choice([0.22,0.3,0.45]))
                notes.append([t,t+d,p,90]); t += float(rng.choice([0.25,0.5,0.5,0.75]))
            tracks.append(Track(name=name, notes=np.array(notes), color=TRACK_COLORS[ti]))
        self.duration=16.0; self.file_label.setText("demo — わくわくクッキングタイム的なBGM")
        self._set_tracks(tracks); self._after_tracks_changed()

def main():
    app = QApplication(sys.argv)
    win = MainWindow(demo="--demo" in sys.argv)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
