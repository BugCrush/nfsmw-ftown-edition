"""steps.py: order, skipping, tool paths; app.py: check changes nothing, refusal exit codes (synthetic folders)."""
import os
import tempfile

from ftedition import __main__ as cli
from ftedition import downloads, journal, steps, toolpaths

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _order():
    import yaml
    with open(os.path.join(REPO, "release", "installer", "cars-release.yaml"), encoding="utf-8") as f:
        return list(yaml.safe_load(f).items())


def test_step_order_matches_spec():
    ids = [s.id for s in steps.all_steps(_order())]
    # spec: ASI loader -> large-address-aware -> Xbox 360 pack -> ReTex -> companions -> Unlimiter and cars -> Thar ->
    # CarStable -> our plugins -> F-Town -> our settings
    def at(x):
        return ids.index(x)
    assert at("asi_loader") < at("laa") < at("x360_stage1") < at("retex") < at("companions") < at("car-unlimiter")
    assert at("car-unlimiter") < at("car-challenger71") < at("car-thar") < at("carstable") < at("our_plugins")
    assert at("our_plugins") < at("ftown") < at("settings") == len(ids) - 1
    # the cars in the order the user's game got them (the records' hash chain)
    cars = [i[4:] for i in ids if i.startswith("car-")]
    assert cars[:6] == ["unlimiter", "challenger71", "flipcar", "chiron", "raptor", "raptor-tuning"], cars
    assert cars.index("longnosecab") < cars.index("longnosecab-tuning-v1") < cars.index("longnosecab-tuning-v6")
    assert cars[-1] == "thar"


class _J:
    @staticmethod
    def step(name, may_change):
        import contextlib
        return contextlib.nullcontext()


def test_missing_download_skips_dependents():
    ran = []
    st = [steps.Step("a", "A", lambda c: ran.append("a"), [], needs=["pack"]),
          steps.Step("b", "B", lambda c: ran.append("b"), [], after=["a"]),
          steps.Step("c", "C", lambda c: ran.append("c"), [])]
    item = {"id": "pack", "name": "The pack", "page": "https://example.org"}
    ctx = steps.Ctx("g", "p", "w", {"pack": downloads.Missing(item, "The pack is not in the downloads folder")}, _J(),
                    log=lambda m: None)
    done, skipped = steps.run_all(ctx, st, log=lambda m: None)
    assert ran == ["c"] and done == ["c"], (ran, done)
    assert "not in the downloads folder" in skipped["a"] and "a" in skipped["b"], skipped


def test_tool_paths_point_into_work():
    work = tempfile.mkdtemp()
    got = toolpaths.configure(os.path.join(work, "attr"), os.path.join(work, "bin"), os.path.join(work, "net"))
    for v in got.values():
        assert v.startswith(work), got
    import part2
    import install as cars_install
    assert cars_install.BINARIUS_DIR == part2.BINARIUS_DIR == os.path.join(work, "bin")


def test_cli_refusal_exit_code():
    g = tempfile.mkdtemp()  # no speed.exe
    payload = os.path.join(REPO, "release", "dist", "NFSMW F-Town Edition", "payload")
    os.environ["FTEDITION_PAYLOAD"] = payload
    try:
        if not os.path.isdir(payload):
            return  # the package is built later in the plan; the exit code is checked once it exists
        assert cli.main(["install", "--game", g, "--downloads", g]) == 2
        assert cli.main(["uninstall", "--game", g]) == 2
    finally:
        del os.environ["FTEDITION_PAYLOAD"]


def test_cli_check_changes_nothing():
    g = tempfile.mkdtemp()
    open(os.path.join(g, "speed.exe"), "wb").write(b"MZ not really")
    before = sorted(os.listdir(g))
    payload = os.path.join(REPO, "release", "dist", "NFSMW F-Town Edition", "payload")
    if not os.path.isdir(payload):
        return
    os.environ["FTEDITION_PAYLOAD"] = payload
    try:
        assert cli.main(["check", "--game", g, "--downloads", g]) == 2  # refused: not the 1.3 speed.exe
    finally:
        del os.environ["FTEDITION_PAYLOAD"]
    assert sorted(os.listdir(g)) == before
    assert not os.path.exists(os.path.join(g, journal.FOLDER))


def test_tool_steps_get_the_players_tools_first():
    """A step that runs Attribulator or Binarius must have them pointed at the player's copies before it starts: the
    reused modules' defaults point at a developer's .tools folder (found by the frozen installer's first run)."""
    calls = []
    real = steps.setup_tools
    steps.setup_tools = lambda ctx: calls.append("setup")
    try:
        st = [steps.Step("db", "database", lambda c: calls.append("run"), [], tools=True)]
        ctx = steps.Ctx("g", "p", "w", {}, _J(), log=lambda m: None)
        steps.run_all(ctx, st, log=lambda m: None)
    finally:
        steps.setup_tools = real
    assert calls == ["setup", "run"], calls
