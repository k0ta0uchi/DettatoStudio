"""dettato モデルDL管理
Hugging Face Hub の kobimusic コレクション4モデルを一括DLする。
dettato公式のオフライン仕様: DETTATO_WEIGHTS=<folder> に
  dettato/ dettato-evidence/ dettato-grouper/ dettato-drums/
  （各 config.json + model.safetensors）を置く。
"""
import os
from pathlib import Path

MODELS = [
    # (repo_id, local_subdir, label, approx)
    ("kobimusic/dettato",          "dettato",          "1. Transcriber (15.3M)", "~60 MB"),
    ("kobimusic/dettato-evidence", "dettato-evidence", "2. Evidence Repairer (4.9M)", "~20 MB"),
    ("kobimusic/dettato-grouper",  "dettato-grouper",  "3. Grouper (2.9M)", "~12 MB"),
    ("kobimusic/dettato-drums",    "dettato-drums",    "4. Drums (5.0M)", "~20 MB"),
]

def default_weights_dir(app_dir: Path) -> Path:
    env = os.environ.get("DETTATO_WEIGHTS")
    if env:
        return Path(env)
    d = app_dir / "models"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d

def model_status(weights_dir: Path):
    """各モデルのDL済みチェック [(label, subdir, exists, size_mb)]"""
    out = []
    for _repo, sub, label, _approx in MODELS:
        d = weights_dir / sub
        ok = (d / "config.json").exists() and any(d.glob("*.safetensors"))
        size = 0.0
        if d.exists():
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e6
        out.append((label, sub, ok, round(size, 1)))
    return out

def all_downloaded(weights_dir: Path) -> bool:
    return all(ok for *_x, ok, _s in [(a,b,c,d) for a,b,c,d in model_status(weights_dir)])

def download_all(weights_dir: Path, progress_cb=None, log_cb=None):
    """ブロッキング実行（QThreadから呼ぶ想定）
    progress_cb(overall_percent:int, message:str)
    """
    # pythonw（窓なし）では sys.stdout/stderr が None で tqdm が落ちる対策
    import sys, io
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["TQDM_DISABLE"] = "1"
    try:
        from huggingface_hub.utils import disable_progress_bars
        disable_progress_bars()
    except Exception:
        pass
    from huggingface_hub import snapshot_download
    weights_dir.mkdir(parents=True, exist_ok=True)
    total = len(MODELS)
    for i, (repo, sub, label, _approx) in enumerate(MODELS):
        base = int(i / total * 100)
        if log_cb:
            log_cb(f">> {label}  ({repo})")
        if progress_cb:
            progress_cb(base, f"Downloading {label} ...")
        dest = weights_dir / sub
        snapshot_download(repo_id=repo, local_dir=str(dest))
        if progress_cb:
            progress_cb(int((i+1)/total*100), f"Done {label}")
        if log_cb:
            log_cb(f"[OK] {label}")
    os.environ["DETTATO_WEIGHTS"] = str(weights_dir)
    return str(weights_dir)


if __name__ == "__main__":
    # CLI: python model_manager.py [weights_dir]
    # ランチャー（launcher.py）が venv の python で呼び、進捗を標準出力で受け取る。
    # 出力形式: "PROGRESS <0-100> <message>" / それ以外はログ行
    import sys
    # 日本語Windowsの cp932 では ✓ 等が encode エラーになるため UTF-8 に固定
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    wd = Path(sys.argv[1]) if len(sys.argv) > 1 else default_weights_dir(Path(__file__).resolve().parent)
    def _prog(pct, msg):
        print(f"PROGRESS {pct} {msg}", flush=True)
    def _log(msg):
        print(msg, flush=True)
    try:
        download_all(wd, progress_cb=_prog, log_cb=_log)
        print("MODELS DONE", flush=True)
    except Exception as e:
        print(f"MODELS FAILED: {e}", flush=True)
        sys.exit(1)
