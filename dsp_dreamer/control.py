"""Reconcile submitted controls against immutable, compiled DSP input samples."""
import numpy as np
from bisect import bisect_right, bisect_left
from typing import Any

from .actions import ACTION_CODEC, decode_action, encode_action
from .contract import CATALOG, CONTROLS, atomic_save, file_info, require
from .dataset import aggregate


def inspect_control(dataset):
    events = sorted(dataset.events, key=lambda e: (e["ticks"], e["sequence_number"]))
    commands = [e for e in events if e["type"] == "control_request"
                and e.get("operation") in ("model_action", "identity_probe", "release_all")]
    failures = [e for e in events if e["type"] == "control_request"
                and e.get("operation") in ("rejected", "deadline_miss", "diagnostic_fault")
                or e["type"] == "game_event" and e.get("name") == "episode_ended"
                and e.get("reason") not in (None, "stopped")]
    frequency = dataset.metadata["ticks_frequency"]
    inputs = [e for e in events if e["type"] == "input"]
    input_ticks = [e["ticks"] for e in inputs]
    final_ticks = max((e["ticks"] for e in events), default=0) + 1
    requests: list[dict[str, Any]] = []
    releases = []
    needs_release = False
    identity_probes = []
    for index, command in enumerate(commands):
        start = command.get("requested_ticks", command["ticks"])
        end = commands[index + 1].get("requested_ticks", commands[index + 1]["ticks"]) if index + 1 < len(commands) else final_ticks
        first = bisect_left(input_ticks, start)
        samples = inputs[first:bisect_left(input_ticks, end)]
        submitted = (command.get("succeeded") is True and type(command.get("sent_count")) is int
                     and type(command.get("requested_count")) is int
                     and command["sent_count"] == command["requested_count"] >= 0)
        if command["operation"] == "release_all":
            if not requests:
                continue  # Baseline preparation releases precede the first controllable observation.
            end = next((c.get("requested_ticks", c["ticks"]) for c in commands[index + 1:]
                        if c["operation"] != "release_all"), final_ticks)
            samples = inputs[first:bisect_left(input_ticks, end)]
            empty = next((s for s in samples if not s["held"]), None)
            releases.append(dict(sequence_number=command["sequence_number"], submitted=submitted,
                required=needs_release,
                released=bool(submitted and empty and all(not s["held"] for s in samples if s["ticks"] >= empty["ticks"])),
                sample_ref=empty["sequence_number"] if empty else None))
            needs_release = False
            continue
        needs_release = True
        if command["operation"] == "identity_probe":
            names = {key for s in samples for key in (*s["held"], *s["down"])}
            distinct_numpad = names in ({"Keypad1"}, {"End"})
            identity_probes.append(dict(sequence_number=command["sequence_number"],
                observed=bool(submitted and command.get("requested_count") == 1 and command.get("scan_code") == 0x4F
                              and distinct_numpad and any(set(s["held"]) & set(s["down"]) == names for s in samples)),
                observed_names=sorted(names),
                sample_refs=[s["sequence_number"] for s in samples]))
            continue
        require(command.get("catalog") == CATALOG, "Incompatible control request catalog")
        decoded = decode_action(command)
        matching = next((s for s in samples if set(s["held"]) == set(decoded["held"])), None)
        previous = inputs[first - 1] if first else None
        before = set(previous["held"]) if previous is not None else set()
        action = aggregate(samples, start, end, sorted(before))
        delta, wheel = action["delta"], action["wheel"]
        actual = encode_action(dict(binary=[0] * 20, delta=delta, wheel=wheel,
                                    ambiguous=False, unsupported=False, forbidden=False))
        downs = {key for s in samples for key in s["down"]}
        ups = {key for s in samples for key in s["up"]}
        hold_end = next((s["ticks"] for s in samples if matching is not None
                        and s["ticks"] > matching["ticks"] and set(s["held"]) != set(decoded["held"])), end)
        # A game reset may consume a confirmed press. It never repairs the training action.
        reset_refs = []
        if matching is not None and decoded["held"] and hold_end < end:
            for reset in events:
                if (reset["type"] != "control_request" or reset.get("operation") != "game_input_reset"
                        or reset.get("source") != "VFInput.ResetAllAxes"
                        or not matching["ticks"] < reset["ticks"] <= hold_end):
                    continue
                prefix = [s for s in samples if s["ticks"] < reset["ticks"]]
                suffix = [s for s in samples if s["ticks"] >= reset["ticks"]]
                if (not aggregate(prefix, start, reset["ticks"], sorted(before))["ambiguous"]
                        and all(set(s["held"]) == set(decoded["held"]) for s in prefix if s["ticks"] >= matching["ticks"])
                        and suffix and all(not s["held"] and not s["down"] and not s["up"] for s in suffix)):
                    reset_refs.append(reset["sequence_number"])
                    break
        held_ms = (hold_end - matching["ticks"]) * 1000 / frequency if matching is not None else 0
        if command["binary"][15] and matching is not None:
            left_up = next((e for e in inputs[bisect_right(input_ticks, matching["ticks"]):]
                            if "MouseLeft" not in e["held"]), None)
            held_ms = (left_up["ticks"] - matching["ticks"]) * 1000 / frequency if left_up is not None else 0
        responses = [matching]
        if any(decoded["pixel_delta"]):
            responses.append(next((s for s in samples if any(s["delta"])), None))
        if decoded["wheel"]:
            responses.append(next((s for s in samples if np.sign(s["wheel"]) == decoded["wheel"]), None))
        observed_ticks = max(s["ticks"] for s in responses if s is not None) if all(s is not None for s in responses) else None
        checks = dict(incomplete_send=submitted, observed_state_missing=matching is not None,
            mouse_bin_mismatch=actual["mouse"] == command["mouse"], wheel_class_mismatch=actual["wheel"] == command["wheel"],
            missing_down=set(decoded["held"]) - before <= downs, missing_up=before - set(decoded["held"]) <= ups,
            unsupported_input=not action["unsupported"], ambiguous_input=not action["ambiguous"] or bool(reset_refs),
            held_state_changed=matching is not None and (hold_end == end or bool(reset_refs)),
            ui_hold_too_short=not command["binary"][15] or held_ms >= 100,
            observation_late=observed_ticks is not None and (observed_ticks - start) * 1000 / frequency <= 100)
        reasons = [name for name, passed in checks.items() if not passed]
        observed = not reasons
        requests.append(dict(request_id=command["request_id"], binary=command["binary"], mouse=command["mouse"],
            wheel=command["wheel"], submitted=submitted, observed=observed, failure_reasons=reasons,
            game_reset_refs=reset_refs, observed_delta=delta,
            observed_wheel=wheel, sample_refs=[s["sequence_number"] for s in samples],
            latency_ms=(observed_ticks - start) * 1000 / frequency if observed and observed_ticks is not None else None,
            held_ms=held_ms))
    return dict(requests=requests, releases=releases, identity_probes=identity_probes, failures=failures,
                gate_passed=bool(requests and releases and not failures and not needs_release and all(r["observed"] for r in requests)
                                 and all(r["submitted"] and (not r["required"] or r["released"]) for r in releases)
                                 and all(r["observed"] for r in identity_probes)))


def publish_calibration(dataset, destination):
    """Only live diagnostic evidence can authorize this runtime's fixed mouse codec."""
    report = inspect_control(dataset)
    requests = report["requests"]
    require(dataset.metadata["source_kind"] == "live" and dataset.metadata["diagnostic_mode"],
            "Calibration requires live diagnostic evidence")
    require(report["gate_passed"], "Control observations/releases did not pass")
    require(bool(report["identity_probes"]), "Missing Numpad1 distinction probe")
    require({i for r in requests for i, bit in enumerate(r["binary"]) if bit} == set(range(20)),
            "Incomplete control coverage")
    require({r["mouse"] // 11 for r in requests if r["mouse"] % 11 == 5} == set(range(11))
            and {r["mouse"] % 11 for r in requests if r["mouse"] // 11 == 5} == set(range(11))
            and {r["wheel"] for r in requests} == {0, 1, 2}, "Incomplete mouse/wheel coverage")
    require(all(r["held_ms"] >= 100 for r in requests if r["binary"][15]), "UI left click shorter than 100 ms")
    require(all(r["latency_ms"] <= 100 for r in requests), "Observed input latency exceeds 100 ms")
    # Fixed codec scale is a contract. A changed response must fail, never silently fit a new codec.
    for request in requests:
        decoded = decode_action(request)
        pixels = np.rint(decoded["pixel_delta"])
        require(np.allclose(np.asarray(request["observed_delta"]) * 20, pixels, atol=0.05, rtol=0),
                "Observed mouse scale differs from 20.0")
    result = dict(schema="dsp-control-calibration/1", catalog=CATALOG, gate_passed=True,
                  fingerprint=dataset.metadata["runtime"]["approved_fingerprint"],
                  observed_to_pixel_scale=ACTION_CODEC["observed_to_pixel_scale"],
                  dataset_id=dataset.metadata["artifact_id"], source_manifest=dataset.metadata["source_manifest"],
                  dataset_completed=file_info(dataset.path / "COMPLETED"), report=report)
    atomic_save(destination, result)
    return result
