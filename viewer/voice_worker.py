"""Speak the player's commentary out loud with OmniVoice (voice cloned from a stored sample).

Runs in the OmniVoice environment of the video-agent repo (weights already cached there):

    uv run --project D:/video-agent/tools/tts/omnivoice python viewer/voice_worker.py --run agent/<name>
    uv run --project D:/video-agent/tools/tts/omnivoice python viewer/voice_worker.py --run agent/<name> --voice en-m-uk-s4

Watches <run>/speech.jsonl (written by the `say` tool), synthesizes each new line to
<run>/voice/<id>.wav and plays them in order on this PC's speakers. If lines pile up while one is
playing, older waiting lines are skipped so speech stays close to live. Progress goes to
<run>/voice.jsonl, which the viewer uses to show what is being spoken.
"""
import argparse
import json
import os
import queue
import sys
import threading
import time
import winsound

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Set by main() from --run: the run folder whose speech.jsonl is spoken.
SPEECH = STATUS = WAVS = None
VIDEO_AGENT = r"D:\video-agent"
SAMPLES = os.path.join(VIDEO_AGENT, "store", "voice", "samples")
SAMPLE_RATE = 24000

os.environ.setdefault("HF_HOME", os.path.join(VIDEO_AGENT, ".cache", "huggingface"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")


def status(entry):
    entry["t"] = time.time()
    with open(STATUS, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_lines(start):
    try:
        with open(SPEECH, encoding="utf-8") as f:
            rows = f.readlines()
    except FileNotFoundError:
        return []
    out = []
    for line in rows[start:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            break  # partially written
    return out


def player(q, max_wait):
    """Play finished wavs in order; skip stale ones when more are waiting."""
    while True:
        item = q.get()
        waiting = [item]
        while True:
            try:
                waiting.append(q.get_nowait())
            except queue.Empty:
                break
        for old in waiting[:-max_wait]:
            status({"id": old["id"], "state": "skipped"})
        for it in waiting[-max_wait:]:
            status({"id": it["id"], "state": "speaking", "dur": it["dur"]})
            winsound.PlaySound(it["wav"], winsound.SND_FILENAME)
            status({"id": it["id"], "state": "done"})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="run to speak for, e.g. agent/first-run")
    ap.add_argument("--voice", default="en-f-lively-s2", help="sample name in video-agent/store/voice/samples")
    ap.add_argument("--steps", type=int, default=32, help="diffusion steps (32 default quality, 16 faster)")
    ap.add_argument("--speed", type=float, default=None, help=">1 faster speech")
    ap.add_argument("--max-wait", type=int, default=2, help="lines kept when speech falls behind")
    ap.add_argument("--from-start", action="store_true", help="also speak lines said before the worker started")
    a = ap.parse_args()
    global SPEECH, STATUS, WAVS
    run = os.path.join(ROOT, "runs", *a.run.replace("\\", "/").split("/"))
    SPEECH, STATUS, WAVS = (os.path.join(run, n) for n in ("speech.jsonl", "voice.jsonl", "voice"))

    import soundfile as sf
    import torch
    from omnivoice import OmniVoice

    sample = os.path.join(SAMPLES, a.voice)
    ref_text = open(os.path.join(sample, "sample.txt"), encoding="utf-8").read().strip()
    print(f"loading OmniVoice, voice {a.voice} ...", flush=True)
    model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)
    prompt = model.create_voice_clone_prompt(ref_audio=os.path.join(sample, "sample.wav"), ref_text=ref_text)
    model.generate(text="Ready.", voice_clone_prompt=prompt, num_step=a.steps)   # warm-up
    os.makedirs(WAVS, exist_ok=True)

    q = queue.Queue()
    threading.Thread(target=player, args=(q, a.max_wait), daemon=True).start()
    seen = 0 if a.from_start else len(read_lines(0))
    print(f"ready; speaking new lines from {SPEECH} (starting after line {seen})", flush=True)

    while True:
        new = read_lines(seen)
        if not new:
            time.sleep(0.15)
            continue
        seen += len(new)
        for line in new:
            t0 = time.perf_counter()
            kwargs = {"text": line["text"], "voice_clone_prompt": prompt, "num_step": a.steps}
            if a.speed:
                kwargs["speed"] = a.speed
            try:
                wav = model.generate(**kwargs)[0]
            except Exception as e:  # one bad line must not stop the commentary
                status({"id": line["id"], "state": "failed", "error": str(e)[:200]})
                continue
            if hasattr(wav, "detach"):
                wav = wav.detach().float().cpu().numpy()
            wav = wav.squeeze()
            path = os.path.join(WAVS, f"{line['id']}.wav")
            sf.write(path, wav, SAMPLE_RATE)
            dur = len(wav) / SAMPLE_RATE
            gen = time.perf_counter() - t0
            status({"id": line["id"], "state": "ready", "dur": round(dur, 2), "gen_s": round(gen, 2)})
            print(f"#{line['id']} {gen:.2f}s -> {dur:.1f}s audio: {line['text'][:70]}", flush=True)
            q.put({"id": line["id"], "wav": path, "dur": round(dur, 2)})


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.stdout.flush()
        os._exit(0)
