# DSP Dreamer

Issue [#13](https://github.com/JayWu07291/DSP_Dreamer/issues/13) implements the first single-episode recording path. The Windows Unity plugin records human input and full-screen frames. The Python entry point verifies and publishes four-file recording evidence, compiles adjacent observations and actual actions, and reads the resulting dataset.

## Setup

Use Python 3.12 and the installed game's compile-only references. Install dependencies in a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install numpy==2.2.6 zarr==3.1.2 pyarrow==21.0.0 pytest==8.4.2 mypy==1.18.2
dotnet build src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj
```

The plugin targets net472, Windows x64 Unity Mono, BepInEx 5.4.23.5 and its bundled HarmonyX 2.9.0. Set the `DSPRoot` MSBuild property for a different install location. Game, Unity and BepInEx assemblies are references only and are never packaged.

FFmpeg must match SHA-256 `04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00`, the FFmpeg 6.1.1 executable selected in #11. The encoder preserves RGBA through reversible BGRA conversion with FFV1 level 3, coder 1, context 0, GOP 1, slice CRC, four slices and four threads.

## Record a short episode

1. Exit DSP and run `tools/deploy-recorder.ps1`. It builds Release, backs up this recorder's existing DLL/config, and deploys the project DLL. It leaves runtime approval blank.
2. Start DSP, load the intended baseline, and press **F8**. The recorder writes `runs/live/runtime-candidate.json` and refuses capture until its fingerprint is approved. Review game/Unity versions, binary hashes, input settings hash, display dimensions and graphics API. The supported Assembly-CSharp hash is fixed in both the plugin and verifier.
3. Set `ApprovedFingerprint` in `BepInEx/config/tw.jaywu.dspdreamer.recorder.cfg` to the reviewed candidate file's SHA-256. The plugin reloads this config on the next start. Any plugin rebuild changes the fingerprint and requires another review.
4. Press **F8** to start. Move, use Digit1, open a UI panel, and move the cursor for at least 15 seconds. Press **F8** to stop. Do not hold Ctrl, which belongs to the old prototype's shortcut.
5. Wait for `Recording, compilation, and readback completed` in `BepInEx/LogOutput.log`. Sibling `.evidence` and `.dataset` directories appear beside the `.source` directory. Preserve the log and directories as live acceptance evidence.

Capture uses 12 reusable buffers and a bounded writer queue. The encoder is ready before timing starts. Input is sampled after `VFInput.OnUpdate`; screenshots use `WaitForEndOfFrame`, including UI and the DSP cursor texture. Each request fixes its ticks, sequence, capture ID, Unity frame, game tick and cursor before its GPU callback. The writer restores request order across callbacks.

The recorder stops on F8, focus loss, world teardown or 30 minutes. Capture/writer faults retain source files and withhold the completion marker. Restart DSP after a fault. Recording never injects controls. Full lifecycle, final terminal observations, fault-prefix recovery and source cleanup belong to subsequent tickets.

## Verify, compile and read

The same commands consume synthetic and live sources. Source metadata explicitly distinguishes them; synthetic evidence cannot stand in for a live acceptance run.

```powershell
.\.venv\Scripts\python.exe -m dsp_dreamer finish --source runs/example.source --ffmpeg 'PATH\ffmpeg.exe'
.\.venv\Scripts\python.exe -m dsp_dreamer verify --source runs/example.source.evidence --ffmpeg 'PATH\ffmpeg.exe'
.\.venv\Scripts\python.exe -m dsp_dreamer compile --source runs/example.source.evidence --out runs/recompiled --ffmpeg 'PATH\ffmpeg.exe'
.\.venv\Scripts\python.exe -m dsp_dreamer inspect --source runs/example.source.dataset
```

Publication creates `recording.mkv`, `frames.ndjson`, `events.ndjson`, then atomically publishes `manifest.json`. It fully decodes source segments and the merged film, compares every RGBA SHA-256 and ordinal, checks both sides of every segment boundary by seek, and compares event bytes. It rechecks files after publication. Destinations must be new; retries cannot overwrite existing artifacts.

The compiler accepts only verified four-file evidence. Actions use `[requested_ticks_t, requested_ticks_next)` and event order is `(ticks, sequence_number)`. It retains held state, fractions, edge counts, observed delta/wheel totals and raw sample references. It marks unsupported, ambiguous and forbidden actions, and gaps, as invalid. Digit1 is index 1 in the 18-control `action_catalog_v2` order. Keyboard identity never uses Unity enum numbers as hardware scan codes.

RGB is stored once in Zarr v3 as uint8 HWC, with one frame per chunk and Blosc/Zstd compression. Parquet tables use Zstd and 1,024-row groups. Adjacent observation indices avoid duplicate RGB storage. File checksums, array layout, source IDs and tool versions are saved before atomic `COMPLETED` publication. The loader checks the inventory and checksums before returning data.

```python
from dsp_dreamer import open_dataset

dataset = open_dataset("runs/example.source.dataset")
transition = dataset[0]
rgb = transition["observation"]
next_rgb = transition["next_observation"]
actual_action = transition["action"]
source_identity = transition["source"]
```

This minimal compiler does not yet emit task/reward/terminal labels or a 10 Hz model view. It stores all recording events for later compilers. Metadata is currently loaded in memory; frame decoding is streamed. Longer-recording memory, full recovery and training gates remain separate acceptance work.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m mypy dsp_dreamer
dotnet build src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj --no-restore
```

The public-interface tests exercise out-of-order callbacks, 200-frame segments, a short tail, varying alpha, boundary seeks, same-tick ordering, half-open events, checksum rejection and unknown fingerprints/events. Tests require the pinned FFmpeg at the path in `tests/test_roundtrip.py`.

Cursor composition is adapted from the #4 prototype on `codex/prototype-issue-11-lossless`. Other production code is separate from the prototype. Existing prototype recordings remain unchanged.
