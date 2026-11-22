"""MIDIノート列 -> WAV合成（ピアノっぽい単純シンセ）
ORIG vs MIDI比較再生用に、MIDI側をその場で音にする。
"""
import numpy as np

SR = 44100

def midi_to_freq(m: int) -> float:
    return 440.0 * (2.0 ** ((m - 69) / 12.0))

def synth_tracks_to_wav(tracks, duration: float, out_path: str, sr: int = SR):
    """tracks: list of dict {notes: (N,4) [onset,end,pitch,vel], muted, solo, volume, is_drum}
    soloが1つでもあればsolo以外は鳴らさない。
    """
    import soundfile as sf
    n = int(max(duration, 0.1) * sr)
    mix = np.zeros(n, dtype=np.float32)
    has_solo = any(t.get("solo") for t in tracks)

    for t in tracks:
        if t.get("muted"):
            continue
        if has_solo and not t.get("solo"):
            continue
        vol = float(t.get("volume", 0.85))
        notes = t.get("notes")
        if notes is None or len(notes) == 0:
            continue
        is_drum = bool(t.get("is_drum"))
        for onset, end, pitch, vel in notes:
            s = int(onset * sr)
            e = int(min(end, duration) * sr)
            if e <= s:
                e = s + int(0.08 * sr)
            length = e - s
            if s >= n:
                continue
            e = min(e, n)
            length = e - s
            t_axis = np.arange(length) / sr
            v = (float(vel) / 127.0) if vel and vel > 1 else 0.8
            if is_drum:
                # ドラムは短いノイズ/クリックで代用
                seg = np.random.randn(length).astype(np.float32) * np.exp(-t_axis * 45)
                seg *= 0.5 * v * vol
            else:
                f = midi_to_freq(int(pitch))
                # 倍音付き + 減衰エンベロープ（ピアノ風）
                seg = (np.sin(2*np.pi*f*t_axis) * 0.65
                       + np.sin(2*np.pi*f*2*t_axis) * 0.22
                       + np.sin(2*np.pi*f*3*t_axis) * 0.08)
                attack = np.minimum(1.0, t_axis / 0.005)
                decay = np.exp(-t_axis * 2.2)
                # リリース
                rel = np.ones_like(t_axis)
                rel_len = int(0.05 * sr)
                if length > rel_len:
                    rel[-rel_len:] = np.linspace(1, 0, rel_len)
                seg = seg * attack * decay * rel * 0.32 * v * vol
            mix[s:e] += seg.astype(np.float32)

    peak = np.max(np.abs(mix)) if mix.size else 0
    if peak > 0.95:
        mix = mix / peak * 0.92
    sf.write(out_path, mix, sr)
    return out_path
