"""Builds and runs visual/tests/sun-test.cpp (the sun's screen position, visual/src/sun.h). Exit code 0 = pass.

    python visual/tests/run-sun-test.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ZIG = os.path.join(ROOT, ".tools", "zig", "zig.exe")
out = os.path.join(HERE, "out", "sun-test")
os.makedirs(out, exist_ok=True)
exe = os.path.join(out, "sun-test.exe")
subprocess.check_call([ZIG, "c++", "-target", "x86-windows-gnu", "-O2", "sun-test.cpp", "-o", exe], cwd=HERE)
result = subprocess.run([exe], capture_output=True, text=True)
print(result.stdout.strip())
sys.exit(result.returncode)
