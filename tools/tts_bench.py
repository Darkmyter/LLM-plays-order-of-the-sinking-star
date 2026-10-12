"""Measure OmniVoice speed on this machine (warm model). Run with the OmniVoice environment:

    D:\\video-agent\\tools\\tts\\omnivoice\\.venv\\Scripts\\python.exe tts_bench.py [out_dir]

Read-only use of the other project's weights and voice samples.
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", r"D:\video-agent\.cache\huggingface")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import soundfile as sf
import torch
from omnivoice import OmniVoice

SAMPLES = Path(r"D:\video-agent\store\voice\samples")
VOICE = sys.argv[2] if len(sys.argv) > 2 else "en-f-lively-s2"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "tts_bench_out")
OUT.mkdir(parents=True, exist_ok=True)
SR = 24000

LINES = [
    "Hmm, the rock is in the gap. If I push it east, the gate might open.",
    "Interesting! The freezer thawed and the rock is free.",
    "Okay, that did nothing. Let me undo and try the other side.",
]

t0 = time.perf_counter()
model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)
print(f"model load: {time.perf_counter() - t0:.1f}s", flush=True)

ref_text = (SAMPLES / VOICE / "sample.txt").read_text(encoding="utf-8").strip()
t0 = time.perf_counter()
prompt = model.create_voice_clone_prompt(ref_audio=str(SAMPLES / VOICE / "sample.wav"), ref_text=ref_text)
print(f"clone prompt (once): {time.perf_counter() - t0:.2f}s", flush=True)


def synth(text, steps):
    t = time.perf_counter()
    audio = model.generate(text=text, voice_clone_prompt=prompt, num_step=steps)
    torch.cuda.synchronize()
    took = time.perf_counter() - t
    wav = audio[0]
    wav = wav.detach().float().cpu().numpy() if hasattr(wav, "detach") else wav
    return wav.squeeze(), took


synth("Warm up.", 16)   # first call compiles kernels; not counted
for steps in (32, 16, 8):
    print(f"\n--- num_step={steps}")
    for i, line in enumerate(LINES):
        wav, took = synth(line, steps)
        dur = len(wav) / SR
        sf.write(str(OUT / f"{VOICE}_s{steps}_{i}.wav"), wav, SR)
        print(f"  {took:5.2f}s to make {dur:4.1f}s of speech  (x{dur / took:4.1f} real time)  {line[:48]}", flush=True)
print("\nGPU memory used by this process: %.1f GB" % (torch.cuda.max_memory_allocated() / 1e9))
