#!/usr/bin/env python3
"""
Dettato Studio Launcher
- 単体exe（stdlibのみでビルド、軽量）。本体やtorchは含まない。
- 起動時、同じフォルダに venv が無ければ同梱の uv.exe で自動構築する:
    uv venv venv --python 3.11
    uv pip install -r requirements.txt --python venv\\Scripts\\python.exe
  セットアップ中だけ小さな進捗ウィンドウ（Tk）を出し、ターミナルは出さない。
- venv 構築済み（requirements ハッシュ一致のマーカー有り）なら即 app.py を起動。
- models\\ フォルダも exe と同じフォルダに作る。
使い方: DettatoStudio.exe [--demo] [app.pyへ渡す引数...]
"""
import hashlib, os, subprocess, sys, threading
from pathlib import Path

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="ignore")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="ignore")

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
BASE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
VENV = BASE / "venv"
VENV_PY = VENV / "Scripts" / "python.exe" if os.name == "nt" else VENV / "bin" / "python"
VENV_PYW = VENV / "Scripts" / "pythonw.exe" if os.name == "nt" else VENV_PY
MARKER = VENV / ".dettato_ready"
REQ = BASE / "requirements.txt"
LOG = BASE / "launcher_setup.log"
UV_ZIP_URL = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"

def req_hash() -> str:
    return hashlib.sha256(REQ.read_bytes()).hexdigest() if REQ.exists() else ""

def venv_ready() -> bool:
    return VENV_PY.exists() and MARKER.exists() and MARKER.read_text(errors="ignore").strip() == req_hash()

def find_uv() -> Path | None:
    c = BASE / "uv.exe"
    if c.exists():
        return c
    import shutil
    w = shutil.which("uv")
    return Path(w) if w else None

def download_uv(log) -> Path:
    """uv.exe が無い場合は公式zipをDLして展開する（フォールバック）"""
    import io, urllib.request, zipfile
    log("uv.exe が見つからないため公式リリースをダウンロードします…")
    data = urllib.request.urlopen(UV_ZIP_URL, timeout=120).read()
    z = zipfile.ZipFile(io.BytesIO(data))
    for name in z.namelist():
        if name.endswith("uv.exe"):
            (BASE / "uv.exe").write_bytes(z.read(name))
            log("uv.exe を取得しました")
            return BASE / "uv.exe"
    raise RuntimeError("uv zip の中に uv.exe がありませんでした")

def _child_env():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env

def run_stream(cmd: list[str], log) -> int:
    log("> " + " ".join(str(c) for c in cmd))
    with open(LOG, "a", encoding="utf-8", errors="ignore") as lf:
        proc = subprocess.Popen([str(c) for c in cmd], cwd=str(BASE), env=_child_env(),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                creationflags=CREATE_NO_WINDOW)
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log(line); lf.write(line + "\n"); lf.flush()
        return proc.wait()

def setup_venv(log) -> None:
    (BASE / "models").mkdir(parents=True, exist_ok=True)
    uv = find_uv() or download_uv(log)
    if not VENV_PY.exists():
        log("venv を作成します（Python 3.11）…")
        rc = run_stream([uv, "venv", str(VENV), "--python", "3.11"], log)
        if rc != 0:
            raise RuntimeError(f"uv venv が失敗しました (rc={rc})。詳細: {LOG.name}")
    log("依存をインストールします（torch + dettato、初回は時間がかかります）…")
    rc = run_stream([uv, "pip", "install", "-r", str(REQ), "--python", str(VENV_PY)], log)
    if rc != 0:
        raise RuntimeError(f"uv pip install が失敗しました (rc={rc})。詳細: {LOG.name}")
    log("動作チェック中…")
    rc = run_stream([VENV_PY, "-c", "import PySide6, dettato; print('IMPORT OK')"], log)
    if rc != 0:
        raise RuntimeError(f"import チェックが失敗しました。詳細: {LOG.name}")
    MARKER.write_text(req_hash(), encoding="utf-8")
    log("セットアップ完了")

def models_ready() -> bool:
    try:
        sys.path.insert(0, str(BASE))
        from model_manager import model_status, default_weights_dir
        return all(ok for *_x, ok, _s in [(a, b, c, d) for a, b, c, d in model_status(default_weights_dir(BASE))])
    except Exception:
        return False

def download_models(log, progress=None) -> None:
    """venv の python で model_manager.py を実行し、モデルを自動DLする"""
    sys.path.insert(0, str(BASE))
    from model_manager import default_weights_dir
    wd = default_weights_dir(BASE)
    log("モデルをダウンロードします（4モデル、約110MB）…")
    cmd = [str(VENV_PY), str(BASE / "model_manager.py"), str(wd)]
    with open(LOG, "a", encoding="utf-8", errors="ignore") as lf:
        proc = subprocess.Popen(cmd, cwd=str(BASE), env=_child_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                creationflags=CREATE_NO_WINDOW)
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip(); lf.write(line + "\n"); lf.flush()
            if line.startswith("PROGRESS "):
                parts = line.split(" ", 2)
                if progress and len(parts) >= 2 and parts[1].isdigit():
                    progress(int(parts[1]), parts[2] if len(parts) > 2 else "")
                if len(parts) > 2:
                    log(parts[2])
            elif line:
                log(line)
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"モデルのダウンロードが失敗しました (rc={rc})。詳細: {LOG.name}")

def launch_app(args: list[str]) -> None:
    py = VENV_PYW if Path(VENV_PYW).exists() else VENV_PY
    subprocess.Popen([str(py), str(BASE / "app.py"), *args], cwd=str(BASE),
                     creationflags=CREATE_NO_WINDOW, close_fds=True)

def main() -> None:
    args = sys.argv[1:]
    (BASE / "models").mkdir(parents=True, exist_ok=True)
    if venv_ready() and models_ready():
        launch_app(args)
        return
    # --- セットアップUI（Tk / stdlibのみ） ---
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title("Dettato Studio — セットアップ")
    root.geometry("560x360")
    root.configure(bg="#0B0B10")
    lbl = tk.Label(root, text="初回セットアップ中です。環境構築とモデルのダウンロードを自動で行います…\n（torch のダウンロード等で数分〜十数分かかります）",
                   bg="#0B0B10", fg="#E5E7EB", justify="left", font=("Yu Gothic UI", 10))
    lbl.pack(anchor="w", padx=14, pady=(12, 6))
    bar = ttk.Progressbar(root, mode="indeterminate"); bar.pack(fill="x", padx=14, pady=4); bar.start(12)
    txt = tk.Text(root, bg="#12121A", fg="#9CA3AF", font=("Consolas", 8), wrap="word")
    txt.pack(fill="both", expand=True, padx=14, pady=(4, 12))
    def log(msg: str):
        root.after(0, lambda: (txt.insert("end", msg + "\n"), txt.see("end")))
    def worker():
        try:
            if not venv_ready():
                setup_venv(log)
            if not models_ready():
                download_models(log, progress=lambda pct, msg: root.after(0, lambda: lbl.config(text=f"モデルをダウンロード中… {pct}%")))
            root.after(0, lambda: (launch_app(args), root.destroy()))
        except Exception as e:
            log(f"\nエラー: {e}")
            root.after(0, lambda: (bar.stop(), lbl.config(text="セットアップに失敗しました。ログ（launcher_setup.log）を確認してください。")))
    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()

if __name__ == "__main__":
    main()
