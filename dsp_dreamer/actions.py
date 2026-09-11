"""Shared model action codec; identities never use Unity enum ordinals."""
import numpy as np
from typing import Any

from .contract import CATALOG, CONTROLS, require


SCANCODES = [0x01, 0x02, 0x03, 0x0F, 0x11, 0x13, 0x14, 0x1D,
             0x1E, 0x1F, 0x20, 0x21, 0x2A, 0x2D, 0x2E, None, None, None, 0x39, 0x12]
ACTION_CODEC: dict[str, Any] = dict(version="dsp-action/1", catalog=CATALOG, controls=CONTROLS,
                    binary_width=20, scan_codes=SCANCODES,
                    unity_names=["Alpha1" if k == "Digit1" else "Alpha2" if k == "Digit2" else k for k in CONTROLS],
                    observed_to_pixel_scale=[20.0, 20.0], maxval=10, binsize=2, mu=5,
                    mouse_classes=121, mouse_order="x*11+y", wheel_classes=[-1, 0, 1],
                    rounding="numpy.rint", noop=dict(binary=[0] * 20, mouse=60, wheel=1))


def validate_action_contract(contract):
    require(contract == ACTION_CODEC,
            "Incompatible action codec/catalog. Recompile evidence; legacy checkpoints require retraining.")


def forbidden_buttons(binary):
    active = {key for key, value in zip(CONTROLS, binary) if value}
    return any(set(pair) <= active for pair in [("W", "S"), ("A", "D"), ("LeftControl", "LeftShift"),
               ("MouseLeft", "MouseRight"), ("MouseLeft", "MouseMiddle"), ("MouseRight", "MouseMiddle")])


def encode_action(action):
    require(not any(action[k] for k in ("ambiguous", "unsupported", "forbidden")), "Action is not trainable")
    xy = np.asarray(action["delta"], dtype=np.float64) * ACTION_CODEC["observed_to_pixel_scale"]
    require(xy.shape == (2,) and np.isfinite(xy).all() and np.isfinite(action["wheel"]), "Invalid action number")
    xy = np.clip(xy, -10, 10) / 10
    bins = np.rint((np.sign(xy) * np.log1p(5 * np.abs(xy)) / np.log(6) * 10 + 10) / 2).astype(int)
    result = dict(binary=list(action["binary"]), mouse=int(bins[0] * 11 + bins[1]), wheel=int(np.sign(action["wheel"])) + 1)
    decode_action(result)
    return result


def decode_action(action):
    binary = action.get("binary")
    require(isinstance(binary, list) and len(binary) == len(CONTROLS)
            and all(type(v) is int and v in (0, 1) for v in binary), "Invalid action width/bits")
    require(not forbidden_buttons(binary), "Forbidden action combination")
    require(type(action.get("mouse")) is int and 0 <= action["mouse"] < 121
            and type(action.get("wheel")) is int and 0 <= action["wheel"] < 3, "Invalid action class")
    xy = (np.asarray(divmod(action["mouse"], 11), dtype=np.float64) * 2 - 10) / 10
    pixels = np.sign(xy) * np.expm1(np.abs(xy) * np.log(6)) * 2
    return dict(held=[k for k, v in zip(CONTROLS, binary) if v], pixel_delta=pixels.tolist(),
                observed_delta=(pixels / ACTION_CODEC["observed_to_pixel_scale"]).tolist(), wheel=action["wheel"] - 1)
