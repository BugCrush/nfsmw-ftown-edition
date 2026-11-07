"""Checks PatchMap.log written next to the stand-in (known answer: the four patches patchmap-standin.cpp makes).
Usage: python check-patchmap.py <folder with PatchMap.log>
"""
import os
import re
import sys

log = open(os.path.join(sys.argv[1], "PatchMap.log"), encoding="utf-8").read()
print(log)
ranges = re.findall(r"^RANGE start=(0x[0-9A-F]+) len=(\d+) section=(\S+)$", log, re.M)
owners = dict(re.findall(r"^OWNER start=(0x[0-9A-F]+) owner=(\S+)$", log, re.M))
targets = re.findall(r"^TARGET at=0x[0-9A-F]+ kind=(\w+) dest=0x[0-9A-F]+ module=(\S+)$", log, re.M)
imports = re.findall(r"^IMPORT slot=0x[0-9A-F]+ import=(\S+) module=(\S+)$", log, re.M)
done = re.search(r"^DONE ranges=(\d+) bytes=\d+ imports=(\d+)$", log, re.M)

problems = []
if len(ranges) != 3:
    problems.append("expected 3 ranges, got %d" % len(ranges))
if not any(k == "jmp" and m.startswith("patchmap-standin-mod.dll") for k, m in targets):
    problems.append("no jmp target into patchmap-standin-mod.dll")
if not any(int(n) == 8 and owners.get(s) == "-" for s, n, sec in ranges if sec == ".text"):
    problems.append("no 8-byte .text range without owner")
if not any(sec == ".rdata" and owners.get(s, "-").startswith("patchmap-standin-mod.dll") for s, n, sec in ranges):
    problems.append("no .rdata range owned by patchmap-standin-mod.dll")
if not any(i.lower() == "kernel32.dll!gettickcount" and m.startswith("patchmap-standin-mod.dll") for i, m in imports):
    problems.append("no import hook KERNEL32.dll!GetTickCount -> patchmap-standin-mod.dll")
if not done or done.groups() != ("3", "1"):
    problems.append("DONE line should be ranges=3 imports=1, got %r" % (done.groups() if done else None,))
for p in problems:
    print("FAIL:", p)
print("PASS" if not problems else "%d problem(s)" % len(problems))
sys.exit(1 if problems else 0)
