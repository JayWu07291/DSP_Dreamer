"""核對獨立診斷觀察與正式 dataset；不發布校正或訓練資格。"""
import json
from pathlib import Path

from .contract import file_info, require


def inspect_diagnostic(dataset, journal):
    journal = Path(journal)
    seal = json.loads(journal.with_name(journal.name + ".complete.json").read_text(encoding="utf-8"))
    require(file_info(journal)["sha256"] == seal["sha256"], "Diagnostic journal checksum mismatch")
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    require(len(rows) >= 2 and rows[0].get("schema") == "dsp-diagnostic/1", "Unknown diagnostic journal")
    require([r["index"] for r in rows] == list(range(len(rows))) and
            all(a["ticks"] <= b["ticks"] for a, b in zip(rows, rows[1:])), "Unordered diagnostic journal")
    header, metadata = rows[0], dataset.metadata
    require(metadata["source_kind"] == "live" and metadata["diagnostic_mode"], "Live diagnostic dataset required")
    require(header["runtime"] == metadata["runtime"] and
            header["recording_session_id"] == metadata["recording_session_id"] and
            header["ticks_frequency"] == metadata["ticks_frequency"], "Diagnostic identity mismatch")
    require(Path(header["source"] + ".dataset").resolve() == dataset.path.resolve(), "Different diagnostic recording")
    case = header["case"]
    require(case in ("focus_hold", "final_readback", "disable", "destroy"), "Unknown diagnostic case")
    checks = {"published": rows[-1].get("type") == "completed" and rows[-1].get("published") is True}
    ends = [r for r in rows if r["type"] == "game_event" and r.get("name") == "episode_ended"]
    checks["one_episode"] = len(ends) == 1 and len(metadata["episodes"]) == 1
    if not ends or not metadata["episodes"]:
        return dict(gate_passed=False, case=case, checks=checks)
    end, episode = ends[0], metadata["episodes"][0]
    before = [r for r in rows if r["type"] == "input" and r["index"] < end["index"]]
    requests = [r for r in rows if r.get("operation") == "model_action"]
    relevant = [r for r in before if r["focused"]] if case == "focus_hold" else before
    presses = [r for r in requests if r.get("succeeded") is True and r.get("binary") == [0]*4+[1]+[0]*15
               and r.get("requested_count") == r.get("sent_count") == 1]
    checks["held_model_key"] = bool(relevant and "W" in relevant[-1]["held"] and any(
        any(p["index"] < s["index"] <= relevant[-1]["index"] and "W" in s["held"] and "W" in s.get("down", [])
            for s in relevant) for p in presses))
    checks["no_later_model_requests"] = not any(r["index"] > end["index"] for r in requests)
    releases = [r for r in rows if r.get("operation") == "release_all" and r["index"] > end["index"]]
    checks["released"] = bool(releases and all(r.get("succeeded") is True and
        r.get("sent_count", 0) == r.get("requested_count", -1) and r.get("sent_count", 0) > 0 for r in releases))
    boundary = end["index"]
    if case in ("disable", "destroy"):
        names = ["OnDisable"] if case == "disable" else ["OnDisable", "OnDestroy"]
        for name in names:
            started = [r for r in rows if r["type"] == "callback" and r.get("name") == name]
            finished = [r for r in rows if r["type"] == "callback_completed" and r.get("name") == name]
            checks[name] = bool(len(started) == len(finished) == 1 and started[0]["index"] < finished[0]["index"] and
                any(started[0]["index"] < r["index"] < finished[0]["index"] for r in releases))
            if finished:
                boundary = max(boundary, finished[0]["index"])
    after = [r for r in rows if r["type"] == "input" and r["index"] > boundary]
    empty = next((r for r in after if not r["held"]), None)
    stable = [r for r in after if empty and r["index"] >= empty["index"]]
    checks["observed_release"] = bool(empty and len(stable) >= 3 and all(not r["held"] for r in stable))
    if case == "focus_hold":
        checks["focus_loss"] = end.get("reason") == "focus_loss" and "focus_loss" in episode["validity_reasons"]
        unfocused = next((r for r in after if not r["focused"]), None)
        checks["refocused_empty"] = bool(unfocused and any(r["focused"] and not r["held"] and
            r["index"] > unfocused["index"] for r in after))
    elif case == "final_readback":
        faults = [r for r in dataset.events if r.get("operation") == "readback_fault_triggered"]
        dataset_end = next((r for r in dataset.events if r.get("name") == "episode_ended"), None)
        captures = {r[k] for r in dataset.rows for k in ("capture_id", "next_capture_id")}
        checks["final_readback_failed"] = bool(len(faults) == 1 and dataset_end and faults[0].get("simulated") is True and
            faults[0]["requested_ticks"] >= dataset_end["ticks"] and faults[0]["capture_id"] not in captures)
        checks["incomplete"] = episode["final_capture_id"] is None and episode["validity_status"] == "incomplete" and "recorder_fault" in episode["validity_reasons"]
    return dict(gate_passed=all(checks.values()), case=case, checks=checks,
                first_empty_ms=None if empty is None else (empty["ticks"]-end["ticks"])*1000/header["ticks_frequency"],
                journal=file_info(journal), episode=episode)
