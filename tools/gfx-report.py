"""One readable summary of what GfxProbe recorded.

    python tools/gfx-report.py <GfxProbe.log> [--all | --from S --to S] [--json]

By default only the periodic reports recorded while driving (at least 90% of their frames) are averaged;
if there are none, all are used and the output says so. --all uses every report; --from/--to pick reports
by log time in seconds. Dissections and screenshots are found through the paths in the log.

The stage table: one row per (target, nth visit in the frame), in drawing order. "seen" is the share of
frames in which the stage occurred; draws and triangles are per frame in which it occurred. "in" is
processor time inside the Direct3D calls the probe times (draws, clears, copies, target switches,
creations); "between" is everything else in that stage: the game's own work, the effect library, and the
device calls the probe does not time. Both are per timed frame ("timed" says how many frames that was;
n/a if none) and both are inflated by the clock reads (the last line of that block says by how much).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gfxlog


def pick(reps, args):
    if args.all:
        return reps, "all reports"
    if args.from_s is not None or args.to_s is not None:
        lo = args.from_s if args.from_s is not None else 0
        hi = args.to_s if args.to_s is not None else 1e12
        return [r for r in reps if lo <= r["t"] <= hi], "reports from %g s to %g s" % (lo, hi)
    driving = [r for r in reps if float(r["FRAMEMAP"]["driving"]) >= 0.9]
    if driving:
        return driving, "reports recorded while driving"
    return reps, "all reports (none was recorded while driving)"


def merge(reps):
    frames = sum(int(r["FRAMEMAP"]["frames"]) for r in reps)
    stages, shapes, copies = {}, {}, {}
    time = {"timed_frames": 0, "frame_ms": 0.0, "present_ms": 0.0, "loose_in_ms": 0.0, "loose_out_ms": 0.0, "calls": 0.0, "clock_ns": 0.0}
    for r in reps:
        n = int(r["FRAMEMAP"]["frames"])
        weight = {}
        for s in r["STAGE"]:
            key = (s["target"], s["visit"])
            e = stages.setdefault(key, {"target": s["target"], "visit": int(s["visit"]), "kind": s["kind"], "size": s["size"],
                                        "fmt": s["fmt"], "ms": int(s["ms"]), "w": 0.0, "order": 0.0, "draws": 0.0, "tris": 0.0,
                                        "clears": 0.0, "copies": 0.0, "timed": 0, "in_ms": 0.0, "out_ms": 0.0, "labels": {}})
            w = n * float(s["seen"]) / 100.0
            weight[key] = w
            e["w"] += w
            for field in ("order", "draws", "tris", "clears", "copies"):
                e[field] += float(s[field]) * w
            timed = int(s["timed"])
            e["timed"] += timed
            e["in_ms"] += float(s["in_ms"]) * timed
            e["out_ms"] += float(s["out_ms"]) * timed
        for l in r["LABEL"]:
            key = (l["target"], l["visit"])
            if key in stages:
                name = l["fx"] + "/" + l["tech"]
                stages[key]["labels"][name] = stages[key]["labels"].get(name, 0.0) + float(l["draws"]) * weight.get(key, 0.0)
        for s in r["SHAPE"]:
            shapes[s["seq"]] = shapes.get(s["seq"], 0.0) + float(s["share"]) * n
        for c in r["COPY"]:
            key = (c["src"], c["dst"])
            copies[key] = copies.get(key, 0.0) + float(c["per_frame"]) * n
        for t in r["TIME"]:
            timed = int(t["timed_frames"])
            time["timed_frames"] += timed
            for field in ("frame_ms", "present_ms", "loose_in_ms", "loose_out_ms", "calls"):
                time[field] += float(t[field]) * timed
            time["clock_ns"] = float(t["clock_ns"])
    out = []
    for e in stages.values():
        w = e.pop("w") or 1.0
        for field in ("order", "draws", "tris", "clears", "copies"):
            e[field] = round(e[field] / w, 3)
        e["seen"] = round(100.0 * w / frames, 1) if frames else 0.0
        # A stage that was in no timed frame has no time: None, shown as n/a (not 0 ms).
        e["in_ms"] = round(e["in_ms"] / e["timed"], 4) if e["timed"] else None
        e["out_ms"] = round(e["out_ms"] / e["timed"], 4) if e["timed"] else None
        e["labels"] = {k: round(v / w, 2) for k, v in sorted(e["labels"].items(), key=lambda kv: -kv[1])}
        out.append(e)
    out.sort(key=lambda e: e["order"])
    timed = time["timed_frames"] or 1
    for field in ("frame_ms", "present_ms", "loose_in_ms", "loose_out_ms", "calls"):
        time[field] = round(time[field] / timed, 4)
    return {
        "frames": frames,
        "stages": out,
        "draws_per_frame": round(sum(e["draws"] * e["seen"] / 100.0 for e in out), 2),
        "tris_per_frame": round(sum(e["tris"] * e["seen"] / 100.0 for e in out), 1),
        "shapes": [{"seq": k, "share": round(v / frames, 1)} for k, v in sorted(shapes.items(), key=lambda kv: -kv[1])][:8] if frames else [],
        "copies": [{"src": k[0], "dst": k[1], "per_frame": round(v / frames, 2)} for k, v in sorted(copies.items())] if frames else [],
        "time": time,
    }


def dissection(fields, targets):
    calls = gfxlog.parse_calls(os.path.join(fields["dir"], "calls.txt"))
    current, by_stage, draws, not16 = None, {}, 0, 0
    for call, f in calls:
        if call == "target" and f.get("index") == "0":
            current = f["target"]
        elif call == "draw":
            draws += 1
            parts = f["filt0"].split("/")
            if not (parts[0] == "anisotropic" and parts[3] == "16"):
                not16 += 1
                key = (current, f["fx"] + "/" + f["tech"], f["filt0"])
                by_stage[key] = by_stage.get(key, 0) + 1
    rows = [{"target": k[0], "size": targets.get(k[0], {}).get("size", "?"), "kind": targets.get(k[0], {}).get("kind", "?"),
             "label": k[1], "filter": k[2], "draws": v} for k, v in sorted(by_stage.items(), key=lambda kv: -kv[1])]
    return {"n": int(fields["n"]), "t": float(fields["t"]), "dir": fields["dir"], "lines": len(calls), "draws": draws,
            "images": int(fields["images"]), "ms": float(fields["ms"]), "not_16x": not16, "not_16x_by_stage": rows}


def build(path, args):
    lines = gfxlog.parse(path)
    chosen, basis = pick(gfxlog.reports(lines), args)
    report = merge(chosen)
    report["basis"] = "%s (%d reports, %d frames)" % (basis, len(chosen), report["frames"])
    targets = {f["id"]: f for t, tag, f in lines if tag == "TARGET"}
    report["targets"] = targets
    effects = {}
    for t, tag, f in lines:
        if tag == "EFFECT" and "params" in f:
            effects[f["name"]] = {"params": int(f["params"]), "techniques": []}
        elif tag == "TECH" and f["fx"] in effects and f["name"] not in effects[f["fx"]]["techniques"]:
            effects[f["fx"]]["techniques"].append(f["name"])
    report["effects"] = effects
    changes = {}
    for r in chosen:
        for f in r["FXCHANGE"]:
            entry = changes.setdefault((f["fx"], f["name"]), {"fx": f["fx"], "name": f["name"], "changes": 0, "last": ""})
            entry["changes"] += int(f["changes"])
            entry["last"] = f["last"]
    report["fxchanges"] = sorted(changes.values(), key=lambda c: (c["changes"], c["fx"], c["name"]))
    warnings = []
    for r in chosen:
        if r["FRAMEMAP"].get("overflow", "0") != "0":
            warnings.append("report at %.0f s: %s frames had more stages than the probe keeps (48); later stages are merged" % (r["t"], r["FRAMEMAP"]["overflow"]))
        if r["FRAMEMAP"].get("stages") == "96":
            warnings.append("report at %.0f s: the stage table was full (96); some stages may be missing" % r["t"])
    for t, tag, f in lines:
        if tag == "OVERFLOW":
            full = ["%s=%s" % (k, v) for k, v in f.items() if k != "note" and v != "0"]
            warnings.append("at %.0f s a table was full: %s%s" % (t, ", ".join(full), " (" + f["note"] + ")" if "note" in f else ""))
    report["warnings"] = warnings
    report["fxvalues"] = [{"t": t, "fx": f["fx"], "name": f["name"], "value": f["value"]} for t, tag, f in lines if tag == "FXVALUE"]
    report["created"] = [f for t, tag, f in lines if tag == "CREATE"]
    textures = [f for t, tag, f in lines if tag == "TEXTURES"]
    report["textures"] = textures[-1] if textures else {}
    report["shaders"] = len([1 for t, tag, f in lines if tag == "SHADER"])
    report["watch"] = [{"t": t, "name": f["name"], "value": f["value"], "was": f.get("was", "-")} for t, tag, f in lines
                       if tag == "WATCH" and "value" in f]
    report["shots"] = len([1 for t, tag, f in lines if tag == "SHOT" and f.get("ok") == "1"])
    report["dissections"] = [dissection(f, targets) for t, tag, f in lines if tag == "DISSECT" and "dir" in f
                             and os.path.isfile(os.path.join(f["dir"], "calls.txt"))]
    msaa = [f for r in chosen for f in r["MSAA"]]
    report["msaa_state_writes"] = {"on": sum(int(f["on"]) for f in msaa), "off": sum(int(f["off"]) for f in msaa)}
    return report


def show(r):
    print("GfxProbe report: " + r["basis"])
    for w in r["warnings"]:
        print("WARNING: " + w)
    print("%.0f draws and %.0f triangles per frame\n" % (r["draws_per_frame"], r["tris_per_frame"]))
    print("Stages of a frame, in drawing order")
    print("%5s  %-5s %-10s %-11s %-14s %2s %6s %8s %9s %6s %7s %8s %8s %5s" % (
        "order", "id", "kind", "size", "format", "aa", "seen%", "draws", "triangles", "clears", "copies", "in ms", "betw ms", "timed"))
    ms = lambda v: "%8s" % "n/a" if v is None else "%8.3f" % v
    for s in r["stages"]:
        print("%5.1f  %-5s %-10s %-11s %-14s %2d %6.1f %8.1f %9.0f %6.1f %7.1f %s %s %5d" % (
            s["order"], s["target"] + ("#%d" % s["visit"] if s["visit"] > 1 else ""), s["kind"], s["size"], s["fmt"], s["ms"],
            s["seen"], s["draws"], s["tris"], s["clears"], s["copies"], ms(s["in_ms"]), ms(s["out_ms"]), s["timed"]))
        for name, draws in s["labels"].items():
            print("%8s %-44s %8.1f draws" % ("", name, draws))
    t = r["time"]
    if t["timed_frames"]:
        print("\nProcessor time per frame (%d timed frames): %.2f ms before Present, %.2f ms inside Present" % (
            t["timed_frames"], t["frame_ms"], t["present_ms"]))
        print("  outside any stage: %.3f ms in calls, %.3f ms between" % (t["loose_in_ms"], t["loose_out_ms"]))
        print("  measuring cost: about %.3f ms per timed frame (%.0f intercepted calls x 2 clock reads x %.0f ns)" % (
            t["calls"] * 2 * t["clock_ns"] / 1e6, t["calls"], t["clock_ns"]))
    print("\nFrame shapes (sequence of targets)")
    for s in r["shapes"]:
        print("  %5.1f%%  %s" % (s["share"], s["seq"]))
    if r["copies"]:
        print("\nCopies between targets (per frame)")
        for c in r["copies"]:
            src, dst = r["targets"].get(c["src"], {}), r["targets"].get(c["dst"], {})
            print("  %-5s %-11s aa=%-2s -> %-5s %-11s aa=%-2s  %.2f" % (c["src"], src.get("size", "?"), src.get("ms", "?"),
                                                                    c["dst"], dst.get("size", "?"), dst.get("ms", "?"), c["per_frame"]))
    print("\nAnti-aliasing switch writes in these reports: on x%d, off x%d" % (r["msaa_state_writes"]["on"], r["msaa_state_writes"]["off"]))
    print("\nEffects loaded: %d" % len(r["effects"]))
    for name, e in sorted(r["effects"].items()):
        print("  %-32s %3d settings; techniques: %s" % (name, e["params"], ", ".join(e["techniques"])))
    print("\nEffect settings that changed in these reports: %d (fewest changes first; counted once a second)" % len(r["fxchanges"]))
    for c in r["fxchanges"][:300]:
        print("  %6d x  %-28s %-28s last: %s" % (c["changes"], c["fx"], c["name"], c["last"]))
    print("\nFirst changes of each setting, in full (at most three per setting; %d lines)" % len(r["fxvalues"]))
    for c in r["fxvalues"][:200]:
        print("  %8.1f s  %-28s %-28s %s" % (c["t"], c["fx"], c["name"], c["value"]))
    print("\nTargets and depth buffers created: %d" % len(r["created"]))
    for c in r["created"][:60]:
        print("  %-15s %-11s %-14s levels=%s aa=%s" % (c["kind"], c["size"], c["fmt"], c["levels"], c["ms"]))
    if r["textures"]:
        print("Ordinary textures: %s in %s kinds; commonest: %s" % (r["textures"]["total"], r["textures"]["kinds"], r["textures"]["top"]))
    print("Distinct shaders saved: %d" % r["shaders"])
    print("\nGame values (%d changes)" % len(r["watch"]))
    for w in r["watch"][:200]:
        print("  %8.1f s  %-24s %s (was %s)" % (w["t"], w["name"], w["value"], w["was"]))
    print("\nScreenshots saved: %d" % r["shots"])
    for d in r["dissections"]:
        print("\nDissected frame %d at %.0f s of driving: %d draws, %d images, took %.0f ms\n  %s" % (
            d["n"], d["t"], d["draws"], d["images"], d["ms"], d["dir"]))
        print("  draws not 16x-filtered: %d of %d" % (d["not_16x"], d["draws"]))
        for row in d["not_16x_by_stage"][:30]:
            print("    %5d  %-5s %-10s %-11s %-40s %s" % (row["draws"], row["target"], row["kind"], row["size"], row["label"], row["filter"]))


def main():
    parser = argparse.ArgumentParser(description="Summary of a GfxProbe log")
    parser.add_argument("log")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--from", dest="from_s", type=float)
    parser.add_argument("--to", dest="to_s", type=float)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build(args.log, args)
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        show(report)


main()
