"""Writes short test tones in formats our six songs don't cover, to check the player keeps the
right speed at other sample rates and in mono. Output: music/tests/fixtures/ (git-ignored).

    python music/tests/make-fixtures.py
"""
import math
import os
import struct
import wave

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
CASES = [("tone-48000-mono_Test.wav", 48000, 1), ("tone-22050-stereo_Test.wav", 22050, 2),
         ("tone-32000-stereo_Test.wav", 32000, 2)]
SECONDS = 6

os.makedirs(OUT, exist_ok=True)
for name, rate, channels in CASES:
    with wave.open(os.path.join(OUT, name), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(rate * SECONDS):
            sample = int(8000 * math.sin(2 * math.pi * 440 * i / rate))
            frames += struct.pack("<h", sample) * channels
        w.writeframes(bytes(frames))
    print("wrote", name)
