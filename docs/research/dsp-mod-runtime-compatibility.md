# DSP mod runtime and integration-point decision

Research date: 2026-08-31

## Decision

Build the recorder and controller as a Windows x64 Unity Mono plugin for **BepInEx 5.4.23.5**. Use the **HarmonyX 2.9.0** assembly bundled with that release. Do not package another `0Harmony.dll`.

Target **.NET Framework 4.7.2** (`net472`) and compile against copied, compile-only references from the installed game: `Assembly-CSharp.dll`, `UnityEngine.CoreModule.dll`, `UnityEngine.InputLegacyModule.dll`, `UnityEngine.ImageConversionModule.dll`, and any other Unity modules the implementation actually imports. Deploy only project-owned assemblies under:

```text
<DSP root>/BepInEx/plugins/DSPDreamer/
```

Use these integration points:

| Need | Selected integration point |
| --- | --- |
| Full RGB frame including UI | Persistent plugin coroutine, `WaitForEndOfFrame`, `ScreenCapture.CaptureScreenshotIntoRenderTexture`, then `AsyncGPUReadback` |
| Human action recording | Harmony postfix on `VFInput.OnUpdate`; record the low-level keyboard and mouse state that DSP consumed that frame |
| Policy action injection | Win32 `SendInput`, using scan-code key transitions plus mouse motion, buttons, and wheel events |
| Episode ready | Harmony postfix on `GameMain.Begin` |
| Episode stop | Prefix on `GameMain.End`, with `GameMain.onGameEnded` or an `End` postfix for final status |
| World reset | Call `DSPGame.StartGame(benchmarkSaveName)` on Unity's main thread, then wait for the next `GameMain.Begin` |
| Tech label | Subscribe to the current world's `GameMain.history.onTechUnlocked`; confirm with `TechUnlocked(id)` |
| Valid building placement | Subscribe to `PlanetFactory.onFactoryBuildEntity`, then inspect the new entity and its `PrefabDesc` |
| Landing-capsule removal | Pair `PlanetFactory.beforeFactoryDismantleObject` with `onFactoryDismantleObject` |
| Action-to-state alignment | Optional prefix/postfix around `PlayerController.GameTick`, not `PlayerController.FixedUpdate` |

This design keeps privileged game state out of the model observation. The plugin may write it to label, reward, reset, prompt-switching, and evaluation channels.

## Why this runtime

The current DSP install is a 64-bit Unity Mono game. Its `globalgamemanagers` contains Unity `2022.3.62f3`, its managed directory contains `mscorlib` 4.0 and `netstandard` 2.1, and the decompiled `GameConfig` reports the `0.10.34` release line. The local version list ends at `0.10.34.28529` dated 2026-05-06. The inspected `Assembly-CSharp.dll` has SHA-256 `AE0BA95F75BD879A62AA4CE253B2AB78EAA4FB3C7C595F5E1FEE75EBE0E0EF85` and decompiler MVID `ECE4A40E-5E73-43F4-A9F8-4E74970B5942`.

[BepInEx 5.4.23.5](https://github.com/BepInEx/BepInEx/releases/tag/v5.4.23.5) is the current stable BepInEx 5 release as of the research date. Its release notes explicitly include a fix for Unity `2022.3.62f3` missing `get_graphicsDeviceID`, the exact Unity patch line used by this DSP build. BepInEx 5 is in long-term-support mode, while the BepInEx 6 release page tells BepInEx 5 users to stay on 5 because the prerelease does not yet load BepInEx 5 plugins. That makes 5.4.23.5 the conservative choice, not merely the newest version.

The official `BepInEx_win_x64_5.4.23.5.zip` release asset contains `BepInEx.dll` 5.4.23.5 and `0Harmony.dll` 2.9.0. The source project also pins [HarmonyX 2.9.0](https://github.com/BepInEx/BepInEx/blob/v5.4.23.5/BepInEx/BepInEx.csproj), and BepInEx documents that it [ships HarmonyX for runtime patching](https://github.com/BepInEx/bepinex-docs/blob/master/articles/dev_guide/runtime_patching.md). Mixing a second Harmony build into the plugin would add an avoidable assembly-resolution and patch-ownership risk.

There is a DSP-specific [Thunderstore BepInEx package](https://thunderstore.io/c/dyson-sphere-program/p/xiaoye97/BepInEx/versions/) at version 5.4.17. It was uploaded in 2021. The published archive contains HarmonyX 2.5.5 and predates the Unity 2022.3.62f3 fix. It remains evidence that DSP's mod ecosystem uses BepInEx 5 and the `BepInEx/plugins` layout, but it should not be the pinned runtime for this project.

This machine already runs the selected combination. `BepInEx/LogOutput.log` records BepInEx 5.4.23.5 starting under Unity `2022.3.62.1451004`, CLR `4.0.30319.42000`, Windows x64, then loading the capture-probe plugin successfully on 2026-08-30. This proves loader compatibility on the target machine. It does not by itself prove every capture and control path below.

## Build and deployment contract

Use an SDK-style class-library project with `TargetFramework` set to `net472` and `PlatformTarget` set to `x64` or `AnyCPU` with 64-bit execution required by the host. BepInEx's current [framework-selection guide](https://docs.bepinex.dev/master/articles/dev_guide/plugin_tutorial/2_plugin_start.html?tabs=tabid-netfw) says Unity 2021.2 or later with `netstandard.dll` can use `netstandard2.1`, with `net472` as the fallback when references fail. `net472` is the lower-risk project target here because the game runs a CLR 4 Mono profile and active DSP projects already use it. The [Nebula multiplayer mod](https://github.com/NebulaModTeam/nebula/blob/master/Directory.Build.props) targets `net472` and deploys into DSP's BepInEx plugin directory. The current [soarqin DSP mod collection](https://github.com/soarqin/DSP_Mods/blob/master/Directory.Build.props) also targets `net472` and pins Unity modules from the `2022.3.62` line.

Copy game references into a project-local, ignored `lib` directory or resolve them through an explicit DSP installation property. Mark them `Private=false` so builds do not copy game or Unity assemblies into the plugin package. BepInEx's guide also warns against referencing the game's `mscorlib.dll`, `netstandard.dll`, or broad `System.*` set directly.

Install the upstream Windows x64 package beside `DSPGAME.exe`, following BepInEx's [Unity Mono installation layout](https://github.com/BepInEx/bepinex-docs/blob/master/articles/user_guide/installation/unity_mono.md). Put the project DLLs in `BepInEx/plugins/DSPDreamer/`. BepInEx identifies a normal plugin through a class derived from `BaseUnityPlugin` and annotated with `BepInPlugin`; the [plugin guide](https://docs.bepinex.dev/master/articles/dev_guide/plugin_tutorial/index.html) documents the same deployment directory.

Keep the selected runtime and game build in every dataset manifest:

```text
game_version
unity_version
assembly_csharp_sha256
bepinex_version
harmonyx_version
plugin_version
screen_width
screen_height
ui_scale
input_settings_fingerprint
```

A DSP update can change private methods, event timing, proto IDs, or field layouts without changing the plugin ABI. Refuse to record when the `Assembly-CSharp.dll` hash is unknown until a smoke test approves the new build.

## Frame capture

Run capture from a coroutine owned by the long-lived `BaseUnityPlugin`. Yield `WaitForEndOfFrame` before copying the screen. Unity defines this point as after every camera and GUI has rendered, immediately before display, which matters because the agent must see the tech tree and other UI: [Unity 2022.3 `WaitForEndOfFrame`](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/WaitForEndOfFrame.html).

Call `ScreenCapture.CaptureScreenshotIntoRenderTexture` and submit an `AsyncGPUReadback.Request` for `RGBA32`. Unity's [screen-capture API](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/ScreenCapture.CaptureScreenshotIntoRenderTexture.html) presents this exact combination as the lower-main-thread-cost alternative to synchronous pixel reads. [`AsyncGPUReadback`](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Rendering.AsyncGPUReadback.html) avoids a CPU or GPU stall at the cost of a few frames of latency.

The request must carry its request-time identity into the callback:

```text
episode_id
frame_id
Time.frameCount
GameMain.gameTick
monotonic_timestamp
requested_action_id
```

Use a bounded ring of persistent render targets and outstanding requests. On completion, reject `hasError`, copy bytes promptly to a pooled CPU buffer, and enqueue compression or file writing off the Unity main thread. Never call Unity object APIs from the writer thread.

Do not use DSP's `MainCamera.onPostRender` as the only dataset capture boundary. Local `MainCamera.OnPostRender` invokes its callbacks after that camera, while Unity's [`OnPostRender`](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/MonoBehaviour.OnPostRender.html) is camera-specific. It is useful for scene-only probes, but it does not provide the same full-frame and UI guarantee as `WaitForEndOfFrame`.

## Keyboard and mouse recording

The dataset's "raw" action is the low-level action that DSP consumes, not USB packets. Record it in a Harmony postfix on `VFInput.OnUpdate`.

Local code establishes the timing:

- `DSPGame.Update` calls `VFInput.OnUpdate` once per rendered frame.
- `VFInput.OnUpdate` reads `Horizontal`, `Vertical`, `Mouse X`, `Mouse Y`, `Mouse Wheel`, modifier keys, its simple-key array, and mouse position through Unity's legacy `Input` API.
- `VFInput.OnFixedUpdate` converts held state into fixed-tick `down`, `up`, and `value` fields.
- `PlayerController.GameTick` later reads those fields and advances player actions.

Unity's [legacy Input documentation](https://docs.unity3d.com/2022.3/Documentation/ScriptReference/Input.html) states that mouse X and Y are deltas and that key and button transitions should be read in `Update`. A postfix records the same frame after DSP has sampled it and avoids relying on unspecified execution order among unrelated `MonoBehaviour.Update` methods.

Persist, at minimum:

- held, down, and up bits for every desktop keyboard `KeyCode` and mouse button supported by the recorder schema, not only `VFInput.simple_buttons` or the first model's smaller action view;
- `Input.mousePosition` for absolute UI targeting;
- `Mouse X` and `Mouse Y` as observed by DSP;
- vertical and horizontal wheel delta when available;
- the corresponding `VFInput` values, `Time.frameCount`, `GameMain.gameTick`, and a monotonic host timestamp;
- focus, pause, fullscreen-UI, text-input, and in-screen flags for filtering.

Do not call Win32 `RegisterRawInputDevices` from this plugin. True Windows Raw Input requires `WM_INPUT` and `GetRawInputData`, but Microsoft states that only one window per raw-input device class may be registered per process and explicitly warns libraries not to register because they may interfere with their host: [`RegisterRawInputDevices`](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerrawinputdevices). USB-rate packets are also not what DSP's Unity input layer consumes. They would create a second synchronization problem without improving the first model baseline.

## Keyboard and mouse injection

Use the Windows [`SendInput`](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput) API during closed-loop inference. It inserts keyboard and mouse events into the system input stream, so DSP's direct `UnityEngine.Input` calls, UI `EventSystem`, and `VFInput` all observe the same controls. Replacing only `VFInput` is incomplete because the inspected game has hundreds of direct `Input` call sites outside that wrapper, including UI and building tools.

Send keyboard events by hardware scan code with `KEYEVENTF_SCANCODE`, and send a matching `KEYEVENTF_KEYUP` transition. Microsoft's [`KEYBDINPUT`](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput) documentation explains that scan codes represent physical keys independent of the active keyboard layout. Use [`MOUSEINPUT`](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput) for relative mouse motion, button transitions, and wheel units. Absolute pointer placement is acceptable only as part of benchmark reset or calibration, not as a model macro action.

The actuator must enforce these constraints:

- DSP is the foreground window.
- The injector and DSP run at the same integrity level; `SendInput` is limited by Windows User Interface Privilege Isolation.
- Human recording and policy injection are mutually exclusive modes.
- Every held key and mouse button receives an up event on stop, reset, focus loss, exception, or plugin unload.
- A human emergency-abort hotkey remains outside the model action set.
- The plugin checks that `SendInput` returned the requested event count.
- The dataset records what `VFInput.OnUpdate` actually observed, not merely what the actuator requested.

Windows applies pointer speed and acceleration thresholds to relative `MOUSEINPUT`. Freeze those settings for the benchmark or calibrate each mouse action bin against observed Unity `Mouse X/Y` values. This is also why the action record needs both requested and observed fields.

## Episode lifecycle, reset, and privileged labels

Install patches and allocate long-lived worker resources in the plugin's `Awake`. Prefer narrow Harmony prefixes, postfixes, and existing game events. Harmony's documentation confirms that a [postfix runs after the original method](https://harmony.pardeike.net/articles/patching-postfix.html), while a prefix runs before it. Avoid transpilers unless a stable method or event cannot express the integration.

Use a postfix on `GameMain.Begin` as the episode-ready signal. In the inspected build, `Begin` sets loading false and running true, creates game logic, initializes achievement, UI, universe, scenario, and assistance state, then initializes logic. This is the point to bind per-world event handlers and enable capture.

Use a prefix on `GameMain.End` to stop accepting actions and frame requests before teardown. `GameMain.End` raises `GameMain.onGameEnded` before freeing game logic. Its event or an `End` postfix can finalize episode status; `GameMain.OnDestroy` is only last-resort cleanup.

Reset by calling `DSPGame.StartGame(benchmarkSaveName)` on the Unity main thread. The inspected implementation first ends any existing game, stores the load-file name, selects skip-prologue mode, and starts `GameLoader`. The ordinary load-game UI calls this same method. Wait for the next `GameMain.Begin`, then verify an initial-state fingerprint before sending an action. Do not call `GameSave.LoadCurrentGame` directly inside a live world and do not hand-reset the many mutable game systems.

Bind privileged labels after every `GameMain.Begin`:

- `GameMain.history.onTechUnlocked` reports technology ID, level, and direct-unlock status. Confirm persistent state through `GameMain.history.TechUnlocked(id)`.
- `PlanetFactory.onFactoryBuildEntity` fires after `BuildFinally` has created the entity and components. Inspect `factory.entityPool[newEntityId].protoId` and `LDB.items.Select(protoId).prefabDesc.minerType` to distinguish a valid vein miner from an attempted placement.
- `PlanetFactory.beforeFactoryDismantleObject` fires while the old entity or prebuild still exists. Cache its proto and identity, then use `onFactoryDismantleObject` as completion. The after-event alone is too late to inspect a removed entity.

`PlanetFactory.ClearStaticEvents` clears the static factory events during world teardown, and each load creates a new `GameHistoryData`. Subscribing only once in plugin `Awake` will silently lose labels after the first reset. Unsubscribe old instance handlers on `GameMain.End` where possible and subscribe again after every `Begin`.

If fixed-tick alignment is needed, patch `PlayerController.GameTick`. It reads command state and input before advancing the player actions. Do not use `PlayerController.FixedUpdate` as the action boundary; in this build it only advances the death timer.

## What remains to prove with a smoke test

The selected runtime already loads a BepInEx plugin on the target machine. The owner documentation and local code establish that the APIs and hook bodies exist. The next prototype must still test these end-to-end properties on the exact benchmark setup:

1. Captured frames contain world pixels, tech-tree UI, cursor, and overlays at the chosen resolution and UI scale.
2. `AsyncGPUReadback` returns the expected channel order and vertical orientation without dropped or overwritten buffers.
3. `SendInput` controls movement, camera, click, drag, scroll, hotkeys, and the tech UI while DSP is focused.
4. Requested actions match the next observed `VFInput` sample, including one-frame latency and mouse scaling.
5. Focus loss, abort, reset, and exceptions release every held input.
6. Repeated `DSPGame.StartGame` cycles do not modify the immutable benchmark save and restore the same initial fingerprint.
7. Tech, build, and dismantle event subscriptions survive repeated world teardown and rebind.

These are prototype acceptance checks, not reasons to keep the runtime decision open.

## Source boundary

Version and API claims above use owner-maintained BepInEx, Harmony, Unity, Microsoft, and published package sources. The DSP-specific lifecycle and event claims come from the local `Assembly-CSharp` decompilation of the exact installed binary, not a public API promise. Any game update can invalidate them, which is why the assembly hash and smoke-test gate are part of the decision.
