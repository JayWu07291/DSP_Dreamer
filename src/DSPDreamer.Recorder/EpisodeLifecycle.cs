using BepInEx.Configuration;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using UnityEngine;

namespace DSPDreamer.Recorder
{
    public sealed partial class RecorderPlugin
    {
        private ConfigEntry<string> baseline;
        private ConfigEntry<int> mechaSeed, cameraSeed, policySeed;
        private ConfigEntry<bool> diagnostics;
        private bool diagnosticMode, failNextRelease, failNextReadback;
        private Dictionary<string, object> trial, episode;
        private List<Dictionary<string, object>> episodes;
        private bool worldReady, perturbed, firstPending, finalPending, resetPending, stopPending;
        private int perturbFrame;
        private long finalDeadline;

        private void ConfigureEpisodes()
        {
            baseline = Config.Bind("Trial", "BaselineSave", "Starting Save", "登陸後尚未操作的基準存檔名稱。");
            mechaSeed = Config.Bind("Trial", "MechaSeed", 17);
            cameraSeed = Config.Bind("Trial", "CameraSeed", 29);
            policySeed = Config.Bind("Trial", "PolicySeed", 41);
            diagnostics = Config.Bind("Diagnostics", "Enabled", false, "受控故障測試；此模式的錄製不供訓練。");
        }

        private void DiagnosticUpdate()
        {
            if (!diagnosticMode || !active || episode == null || episode["start_ticks"] == null || episode["end_ticks"] != null) return;
            string test = Input.GetKeyDown(KeyCode.F10) ?
                (Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift) ? "injection_failure" : "human_intervention") :
                Input.GetKeyDown(KeyCode.F7) ? "gpu_readback_error" : null;
            if (test == null) return;
            Emit("control_request", Json.Fields("operation", "diagnostic_fault", "case", test, "simulated", true));
            if (test == "gpu_readback_error") failNextReadback = true;
            else
            {
                failNextRelease = test == "injection_failure";
                EndEpisode(reason: test);
            }
        }

        private string BaselinePath(string name)
        {
            if (string.IsNullOrWhiteSpace(name) || name != Path.GetFileName(name) || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                throw new InvalidOperationException("Invalid baseline save name");
            return Path.Combine(GameConfig.gameSaveFolder, name + GameSave.saveExt);
        }

        private Dictionary<string, object> TrialManifest()
        {
            var result = Json.Fields("baseline_save", baseline.Value,
                "baseline_sha256", SegmentWriter.HashFile(BaselinePath(baseline.Value)),
                "world_seed", GameMain.data.gameDesc.galaxySeed,
                "mecha_seed", mechaSeed.Value, "camera_seed", cameraSeed.Value, "policy_seed", policySeed.Value,
                "rng", "System.Random/net472", "mecha_yaw", new System.Random(mechaSeed.Value).NextDouble() * 30 - 15,
                "camera_yaw", new System.Random(cameraSeed.Value).NextDouble() * 30 - 15,
                "input_settings_sha256", SegmentWriter.HashFile(GameConfig.gameXMLOptionPath),
                "screen_width", Screen.width, "screen_height", Screen.height,
                "resource_multiplier", 1, "peace_mode", true, "sandbox_mode", false, "speed", 1);
            string id = SegmentWriter.Hash(Encoding.UTF8.GetBytes(Json.Encode(result)));
            result["manifest_id"] = id;
            result["split_group_id"] = id;
            return result;
        }

        private void CheckWorld()
        {
            var desc = GameMain.data.gameDesc;
            if (desc.galaxySeed != (int)trial["world_seed"] || desc.isSandboxMode || !desc.isPeaceMode ||
                desc.resourceMultiplier != 1f || Time.timeScale != 1f ||
                Screen.width != (int)trial["screen_width"] || Screen.height != (int)trial["screen_height"] ||
                SegmentWriter.HashFile(GameConfig.gameXMLOptionPath) != (string)trial["input_settings_sha256"])
                throw new InvalidOperationException("Baseline world/settings mismatch");
        }

        private void ReloadBaseline()
        {
            string name = (string)trial["baseline_save"];
            if (SegmentWriter.HashFile(BaselinePath(name)) != (string)trial["baseline_sha256"])
                throw new InvalidOperationException("Baseline save changed; retry refused");
            if (!ReleaseControls()) throw new IOException("Cannot release controls before reset");
            worldReady = perturbed = firstPending = finalPending = false;
            DSPGame.StartGame(name);
            // A retry retains the immutable trial identity but receives fresh attempt and episode IDs.
            episode = Json.Fields("attempt_id", Guid.NewGuid().ToString(), "episode_id", Guid.NewGuid().ToString(),
                "start_ticks", null, "end_ticks", null, "final_capture_id", null, "episode_outcome", null,
                "validity_status", "incomplete", "validity_reasons", new List<string>());
            episodes.Add(episode);
            if (episodes.Count == 1)
            {
                metadata["attempt_id"] = episode["attempt_id"];
                metadata["episode_id"] = episode["episode_id"];
            }
        }

        private bool CanStartEpisode => worldReady && GameMain.isRunning && !GameMain.isLoading &&
            GameMain.mainPlayer != null && GameMain.mainPlayer.isAlive && GameMain.localPlanet != null &&
            !GameMain.data.disableController && !GameMain.isPaused && !VFInput.inFullscreenGUI &&
            !VFInput.inputing && Application.isFocused && GameCamera.instance != null;

        private void PrepareEpisode()
        {
            try { CheckWorld(); }
            catch { EndEpisode(reason: "fingerprint_mismatch"); throw; }
            if (!ReleaseControls())
            {
                EndEpisode(reason: "injection_failure");
                return;
            }
            var player = GameMain.mainPlayer;
            PrepareProgress();
            var rotation = Quaternion.AngleAxis((float)(double)trial["mecha_yaw"], player.position.normalized);
            player.controller.model.rotation = rotation * player.controller.model.rotation;
            player.uRotation = GameMain.localPlanet.runtimeRotation * player.controller.model.rotation;
            var camera = GameCamera.instance.rtsPoser;
            camera.yaw = camera.yawWanted = camera.yaw + (float)(double)trial["camera_yaw"];
            perturbed = true;
            perturbFrame = Time.frameCount;
            Emit("game_event", Json.Fields("name", "perturbation_applied", "episode_id", episode["episode_id"],
                "mecha_yaw", trial["mecha_yaw"], "camera_yaw", trial["camera_yaw"]));
        }

        // The task predicate module reports success; inability to continue is an explicit outcome, never a stuck timer.
        public void EndEpisode(string outcome = null, string reason = null)
        {
            if (outcome != null && outcome != "success" && outcome != "death" && outcome != "timeout" && outcome != "unrecoverable")
                throw new ArgumentException("Unknown episode outcome");
            string[] allowed = { "stopped", "focus_loss", "human_intervention", "injection_failure", "recorder_fault",
                "schema_error", "unknown_control", "fingerprint_mismatch", "reset", "world_unloaded" };
            if (reason != null && !allowed.Contains(reason)) throw new ArgumentException("Unknown validity reason");
            if (outcome == null && reason == null) throw new ArgumentException("Missing episode end reason");
            if (!active || episode == null || episode["end_ticks"] != null) return;
            long now;
            lock (progressGate)
            {
                DrainProgress();
                now = Math.Max(Stopwatch.GetTimestamp(), progressBoundary);
                episode["end_ticks"] = now;
            }
            episode["episode_outcome"] = outcome;
            var reasons = (List<string>)episode["validity_reasons"];
            if (reason != null && !reasons.Contains(reason)) reasons.Add(reason);
            Emit("game_event", Json.Fields("name", "episode_ended", "episode_id", episode["episode_id"],
                "outcome", outcome, "reason", reason));
            if (!ReleaseControls()) ReleaseControls();
            finalPending = (episode["start_ticks"] != null || firstPending) && GameMain.isRunning && !GameMain.isLoading;
            finalDeadline = now + 2 * Stopwatch.Frequency;
            nextDue = now;
        }

        private void EpisodeUpdate()
        {
            if (!active || episode == null) return;
            if (!Application.isFocused) EndEpisode(reason: "focus_loss");
            if (episode["end_ticks"] == null && episode["start_ticks"] != null)
            {
                if (GameMain.mainPlayer != null && !GameMain.mainPlayer.isAlive) EndEpisode("death");
                else if (Stopwatch.GetTimestamp() - (long)episode["start_ticks"] >= 1800L * Stopwatch.Frequency)
                    EndEpisode("timeout");
            }
            if (finalPending && Stopwatch.GetTimestamp() >= finalDeadline) finalPending = false;
            if (episode["end_ticks"] != null && !finalPending && pending == 0)
            {
                if (stopPending) { stopPending = false; StopRecording(); }
                else if (resetPending) { resetPending = false; ReloadBaseline(); }
            }
        }

        internal void WorldEnded()
        {
            EndEpisode(reason: "world_unloaded");
            worldReady = false;
            finalPending = false;
            ReleaseControls();
            UnbindWorld();
        }

        private void CaptureCompleted(Dictionary<string, object> identity)
        {
            if (failed || episode == null || (string)identity["episode_id"] != (string)episode["episode_id"]) return;
            long ticks = (long)identity["requested_ticks"];
            if (episode["start_ticks"] == null && (episode["end_ticks"] == null || ticks <= (long)episode["end_ticks"]))
            {
                episode["start_ticks"] = ticks;
                firstPending = false;
                Emit("game_event", Json.Fields("name", "episode_started", "episode_id", episode["episode_id"],
                    "start_ticks", ticks, "capture_id", identity["capture_id"]));
            }
            if (episode["end_ticks"] != null && ticks >= (long)episode["end_ticks"])
            {
                episode["final_capture_id"] = identity["capture_id"];
                episode["validity_status"] = ((List<string>)episode["validity_reasons"]).Count == 0 ? "valid" : "invalid";
                finalPending = false;
            }
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct NativeInput { public uint Type; public InputUnion Data; }
        [StructLayout(LayoutKind.Explicit)]
        private struct InputUnion
        {
            [FieldOffset(0)] public MouseInput Mouse;
            [FieldOffset(0)] public KeyboardInput Keyboard;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct MouseInput { public int X, Y; public uint Data, Flags, Time; public UIntPtr Extra; }
        [StructLayout(LayoutKind.Sequential)]
        private struct KeyboardInput { public ushort Key, Scan; public uint Flags, Time; public UIntPtr Extra; }
        [DllImport("user32.dll", SetLastError = true)]
        private static extern uint SendInput(uint count, NativeInput[] inputs, int size);
        [DllImport("user32.dll")]
        private static extern short GetAsyncKeyState(int key);

        private bool ReleaseControls()
        {
            var inputs = new List<NativeInput>();
            for (ushort key = 8; key < 255; key++)
                if ((GetAsyncKeyState(key) & 0x8000) != 0)
                    inputs.Add(new NativeInput { Type = 1, Data = new InputUnion {
                        Keyboard = new KeyboardInput { Key = key, Flags = 2 } } });
            inputs.Add(new NativeInput { Type = 0, Data = new InputUnion { Mouse = new MouseInput { Flags = 4 | 16 | 64 } } });
            inputs.Add(new NativeInput { Type = 0, Data = new InputUnion { Mouse = new MouseInput { Flags = 256, Data = 1 } } });
            inputs.Add(new NativeInput { Type = 0, Data = new InputUnion { Mouse = new MouseInput { Flags = 256, Data = 2 } } });
            bool simulated = failNextRelease;
            failNextRelease = false;
            bool ok = !simulated && SendInput((uint)inputs.Count, inputs.ToArray(), Marshal.SizeOf(typeof(NativeInput))) == inputs.Count;
            Emit("control_request", Json.Fields("operation", "release_all", "succeeded", ok, "simulated", simulated));
            if (!ok)
            {
                if (episode != null)
                {
                    var reasons = (List<string>)episode["validity_reasons"];
                    if (!reasons.Contains("injection_failure")) reasons.Add("injection_failure");
                    if (episode["final_capture_id"] != null) episode["validity_status"] = "invalid";
                }
                Logger.LogError(simulated ? "Controlled injection failure; retrying release" : "Control release failed: " + Marshal.GetLastWin32Error());
            }
            return ok;
        }
    }
}
