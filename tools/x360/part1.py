"""Part 1 of the pack's Complex Installation without NFS-VltEd: expand the installer script for the chosen
options, resolve names against our database, apply with Attribulator's command line, return attributes.bin.

Usage: python part1.py <game GLOBAL dir> <pack root> <work dir> [option=0|1 ...]
Never writes into <game GLOBAL dir>.
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfsms  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ATTRIBULATOR = os.path.join(ROOT, ".tools", "attribulator-2.0.0", "Attribulator.CLI.dll")
DOTNET_X86 = os.path.join(ROOT, ".tools", "dotnet-x86", "dotnet.exe")
FILES = ("attributes.bin", "fe_attrib.bin", "gameplay.bin")


def _attribulator(*args):
    p = subprocess.run([DOTNET_X86, "exec", "--roll-forward", "Major", ATTRIBULATOR] + list(args),
                       cwd=os.path.dirname(ATTRIBULATOR), capture_output=True, text=True)
    if p.returncode != 0 or " ERR] " in p.stdout:
        raise RuntimeError("Attribulator %s failed:\n%s%s" % (args[0], p.stdout, p.stderr))
    return p.stdout


def _copy_inputs(global_dir, dest):
    os.makedirs(dest, exist_ok=True)
    names = {n.lower(): n for n in os.listdir(global_dir)}
    for f in FILES:
        shutil.copy(os.path.join(global_dir, names[f]), os.path.join(dest, f))


def unpack(bin_dir, out_dir):
    _attribulator("unpack", "-i", bin_dir, "-o", out_dir, "-p", "MOST_WANTED", "-f", "yml")
    return out_dir


def run(global_dir, pack_root, options, work_dir):
    src = os.path.join(work_dir, "in")
    _copy_inputs(global_dir, src)
    db, _actions, _opts = nfsms.expand(os.path.join(pack_root, "Install-Part-1.nfsms"), pack_root, options)
    classes = {l.split()[1] for l in db if l.split()[0] in nfsms.DB_COMMANDS}
    ours = unpack(src, os.path.join(work_dir, "in-yml"))
    kept, dropped = nfsms.resolve(db, nfsms.load_collections(ours, classes))
    script = os.path.join(work_dir, "part1.nfsms")
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(kept) + "\n")
    out = os.path.join(work_dir, "out")
    os.makedirs(out, exist_ok=True)
    log = _attribulator("apply-script-bin", "-i", src, "-o", out, "-p", "MOST_WANTED", "-s", script)
    applied = int(log.split("Applied ")[1].split(" command")[0])
    final = os.path.join(work_dir, "result")
    os.makedirs(final, exist_ok=True)
    shutil.copy(os.path.join(out, "main", "attributes.bin"), os.path.join(final, "attributes.bin"))
    for f in ("fe_attrib.bin", "gameplay.bin"):  # unchanged inputs beside it, so the result can be unpacked
        shutil.copy(os.path.join(src, f), os.path.join(final, f))
    return {"attributes_bin": os.path.join(final, "attributes.bin"), "dropped": dropped, "applied": applied, "log": log}


if __name__ == "__main__":
    opts = {k: v == "1" for k, v in (a.split("=") for a in sys.argv[4:])}
    r = run(sys.argv[1], sys.argv[2], opts, sys.argv[3])
    print("applied %d, dropped %s\n%s" % (r["applied"], r["dropped"], r["attributes_bin"]))
