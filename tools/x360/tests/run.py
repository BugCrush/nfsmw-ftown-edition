"""Runs every test_*.py in this folder; each test is a function named test_* that raises on failure.

Usage: python tools/x360/tests/run.py [filter]   (filter matches "<file>.<function>")
"""
import importlib.util
import os
import sys
import traceback

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
failed = passed = 0
for name in sorted(os.listdir(here)):
    if not (name.startswith("test_") and name.endswith(".py")):
        continue
    if len(sys.argv) > 1 and sys.argv[1] not in name:
        continue
    spec = importlib.util.spec_from_file_location(name[:-3], os.path.join(here, name))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        failed += 1
        print("FAIL", name, "(import)")
        traceback.print_exc()
        continue
    for fn in sorted(n for n in dir(mod) if n.startswith("test_")):
        try:
            getattr(mod, fn)()
            passed += 1
            print("PASS", name, fn)
        except Exception:
            failed += 1
            print("FAIL", name, fn)
            traceback.print_exc()
print("%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
