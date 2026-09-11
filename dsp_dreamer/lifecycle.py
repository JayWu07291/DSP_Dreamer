"""Request-time episode boundaries shared by evidence validation and compilation."""
import math
import re

from .contract import require


OUTCOMES = (None, "success", "death", "timeout", "unrecoverable")
REASONS = ("stopped", "focus_loss", "human_intervention", "injection_failure", "recorder_fault",
           "schema_error", "unknown_control", "fingerprint_mismatch", "reset", "world_unloaded")


def validate_lifecycle(metadata, frames, prefix=False):
    if "lifecycle_version" not in metadata:
        return
    require(metadata["lifecycle_version"] == 1, "Unknown lifecycle version")
    trial = metadata["trial_manifest"]
    require(all(trial.get(k) for k in ("manifest_id", "split_group_id")), "Missing trial identity")
    require(all(type(trial.get(k)) is int for k in ("mecha_seed", "camera_seed", "policy_seed")), "Missing seeds")
    if metadata["source_kind"] == "live":
        require(isinstance(trial.get("baseline_save"), str) and bool(trial["baseline_save"]), "Missing baseline save")
        require(all(isinstance(trial.get(k), str) and re.fullmatch("[0-9a-f]{64}", trial[k])
                    for k in ("baseline_sha256", "input_settings_sha256", "manifest_id", "split_group_id")),
                "Invalid trial fingerprint")
        require(type(trial.get("world_seed")) is int and trial["world_seed"] >= 0, "Missing world seed")
        require(trial.get("rng") == "System.Random/net472" and all(
                    type(trial.get(k)) in (int, float) and math.isfinite(trial[k]) and -15 <= trial[k] <= 15
                    for k in ("mecha_yaw", "camera_yaw")), "Invalid perturbation")
        require(trial.get("peace_mode") is True and trial.get("sandbox_mode") is False and
                trial.get("resource_multiplier") == 1 and trial.get("speed") == 1, "Invalid trial settings")
        require(all(trial.get(k) == metadata["runtime"][k] for k in
                    ("screen_width", "screen_height", "input_settings_sha256")), "Trial/runtime mismatch")
    episodes = metadata["episodes"]
    require(bool(episodes), "Missing attempts")
    ids, attempts = set(), set()
    previous_end = -1
    for episode in episodes:
        eid, aid = episode["episode_id"], episode["attempt_id"]
        require(bool(eid) and eid not in ids and bool(aid) and aid not in attempts, "Duplicate episode/attempt identity")
        ids.add(eid)
        attempts.add(aid)
        require(episode["episode_outcome"] in OUTCOMES, "Unknown outcome")
        reasons = episode["validity_reasons"]
        require(isinstance(reasons, list) and all(r in REASONS for r in reasons), "Unknown validity reason")
        selected = [f for f in frames if f.get("episode_id") == eid]
        require(all(f.get("attempt_id") == aid for f in selected), "Frame attempt mismatch")
        start, end = episode["start_ticks"], episode["end_ticks"]
        open_end = end is None
        if open_end:
            require(prefix and episode is episodes[-1] and episode["episode_outcome"] is None
                    and episode["final_capture_id"] is None, "Unclosed episode")
            end = selected[-1]["requested_ticks"] if selected else max(0, previous_end)
        require(type(end) is int and end >= 0, "Unclosed episode")
        require(start is None or type(start) is int and previous_end < start <= end, "Overlapping episode")
        previous_end = max(end, selected[-1]["requested_ticks"] if selected else end)
        require((not selected and start is None) or bool(selected) and start == selected[0]["requested_ticks"],
                "Episode must start at its first valid observation")
        final = episode["final_capture_id"]
        require(final is None or type(final) is int and bool(selected) and (
                final == selected[-1]["capture_id"] and selected[-1]["requested_ticks"] >= end or
                prefix and episode is episodes[-1] and final > selected[-1]["capture_id"]
                and end >= selected[-1]["requested_ticks"]),
                "Invalid final observation")
        require(all(f["requested_ticks"] <= end or f["capture_id"] == final for f in selected), "Frame after episode end")
        expected = "incomplete" if final is None else "invalid" if reasons else "valid"
        require(episode["validity_status"] == expected, "Inconsistent validity status")
        require(episode["episode_outcome"] is not None or bool(reasons) or open_end, "Missing end reason")
    require(all(f.get("episode_id") in ids for f in frames), "Unknown frame episode")


def transition_lifecycle(metadata, first, second):
    if "lifecycle_version" not in metadata:
        return dict(episode_id=metadata["episode_id"], attempt_id=metadata["attempt_id"],
                    episode_outcome=None, validity_status="incomplete", validity_reasons=[],
                    is_terminal=False, truncation=False, bootstrap_mask=0, lifecycle_valid=True)
    episode = next(e for e in metadata["episodes"] if e["episode_id"] == first["episode_id"])
    same = first["episode_id"] == second["episode_id"]
    final = same and second["capture_id"] == episode["final_capture_id"]
    outcome = episode["episode_outcome"]
    valid = same and first["requested_ticks"] < episode["end_ticks"]
    if episode["validity_reasons"]:
        valid &= second["requested_ticks"] < episode["end_ticks"]
    terminal = final and outcome in ("success", "death", "unrecoverable")
    tail = final or not same or second["requested_ticks"] >= episode["end_ticks"]
    return dict(episode_id=episode["episode_id"], attempt_id=episode["attempt_id"],
                episode_outcome=outcome, validity_status=episode["validity_status"],
                validity_reasons=episode["validity_reasons"], is_terminal=terminal,
                truncation=final and outcome == "timeout", bootstrap_mask=int(valid and not terminal and
                    not (tail and episode["validity_status"] != "valid")), lifecycle_valid=valid)
