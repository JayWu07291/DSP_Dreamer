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
        private ConfigEntry<string> calibrationFile, calibrationApproval;
        private ConfigEntry<double> nativeScaleX, nativeScaleY;
        private string controlMode = "human", frozenSettings;
        private long lastAction, requestId;
        private int[] injected = new int[20];
        private int probe = -1;
        private bool probeRelease;
        private long nextProbe;
        private int mainThread, processId;
        private PendingAction pendingAction;
        private bool policyStarted;

        private sealed class PendingAction
        {
            internal int[] Binary;
            internal int Mouse, Wheel;
            internal long CaptureTicks, InferenceTicks;
        }

        [Serializable]
        private sealed class Calibration
        {
            public string schema = "", catalog = "", fingerprint = "";
            public bool gate_passed = false;
            public float[] observed_to_pixel_scale = null;
        }

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool SystemParametersInfo(uint action, uint parameter, int[] value, uint flags);
        [DllImport("user32.dll")]
        private static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);

        private bool HasControlFocus
        {
            get { GetWindowThreadProcessId(GetForegroundWindow(), out uint pid); return Application.isFocused && pid == processId; }
        }

        private static int[] MouseSettings()
        {
            var speed = new int[1];
            var acceleration = new int[3];
            if (!SystemParametersInfo(0x70, 0, speed, 0) || !SystemParametersInfo(3, 0, acceleration, 0))
                throw new IOException("Cannot read Windows mouse settings");
            return new[] { speed[0], acceleration[0], acceleration[1], acceleration[2] };
        }

        private void ConfigureControl()
        {
            mainThread = System.Threading.Thread.CurrentThread.ManagedThreadId;
            processId = Process.GetCurrentProcess().Id;
            calibrationFile = Config.Bind("Control", "CalibrationFile", "", "正式證據讀回後產生的校正 JSON。");
            calibrationApproval = Config.Bind("Control", "ApprovedCalibration", "", "已核對校正檔的 SHA-256。");
            nativeScaleX = Config.Bind("Control", "NativeScaleX", 1.0, "X 軸原生位移倍率；變更後必須重新校正。");
            nativeScaleY = Config.Bind("Control", "NativeScaleY", -1.0, "Y 軸原生位移倍率；Windows 向下為正，變更後必須重新校正。");
        }

        private string InputSettingsIdentity() => SegmentWriter.Hash(Encoding.UTF8.GetBytes(Json.Encode(Json.Fields(
            "dsp", SegmentWriter.HashFile(GameConfig.gameXMLOptionPath), "windows", MouseSettings(),
            "native_scale", NativeScale(), "width", Screen.width, "height", Screen.height))));

        private double[] NativeScale()
        {
            var values = new[] { nativeScaleX.Value, nativeScaleY.Value };
            if (values.Any(v => double.IsNaN(v) || double.IsInfinity(v) || Math.Abs(v) < 0.01 || Math.Abs(v) > 100))
                throw new InvalidOperationException("Native mouse scale out of range");
            return values;
        }

        private void CheckCalibration(string fingerprint)
        {
            if (string.IsNullOrEmpty(calibrationApproval.Value) ||
                SegmentWriter.HashFile(calibrationFile.Value) != calibrationApproval.Value)
                throw new InvalidOperationException("Missing or unapproved calibration");
            var value = JsonUtility.FromJson<Calibration>(File.ReadAllText(calibrationFile.Value));
            if (value == null || value.schema != "dsp-control-calibration/1" || value.catalog != ModelAction.Catalog ||
                !value.gate_passed || value.fingerprint != fingerprint || value.observed_to_pixel_scale == null ||
                !value.observed_to_pixel_scale.SequenceEqual(new[] { 20f, 20f }))
                throw new InvalidOperationException("Stale/incompatible calibration; revalidate before recording or evaluation");
        }

        // Called on Unity's main thread by the future inference runner. Human sessions cannot switch mode.
        public void StartPolicyRecording()
        {
            RequireMainThread();
            if (active || writer != null) throw new InvalidOperationException("Recording already active");
            StartRecording("policy");
        }

        private void RequireMainThread()
        {
            if (System.Threading.Thread.CurrentThread.ManagedThreadId != mainThread)
                throw new InvalidOperationException("Control must run on Unity main thread");
        }

        public void SubmitAction(string catalog, int[] binary, int mouse, int wheel, long captureTicks, long inferenceTicks)
        {
            RequireMainThread();
            try
            {
                if (controlMode != "policy" || !ControlReady) throw new InvalidOperationException("No active policy episode");
                ModelAction.Validate(catalog, binary, mouse, wheel);
                long now = Stopwatch.GetTimestamp();
                if (captureTicks > 0 && now - captureTicks > Stopwatch.Frequency / 10)
                    Emit("control_request", Json.Fields("operation", "deadline_miss", "capture_ticks", captureTicks,
                        "inference_ticks", inferenceTicks, "previous_request_id", requestId));
                if (captureTicks <= 0 || captureTicks > inferenceTicks || inferenceTicks > now ||
                    now - captureTicks > Stopwatch.Frequency / 10)
                    throw new InvalidOperationException("Action deadline missed");
                if (!policyStarted && (binary.Any(v => v != 0) || mouse != 60 || wheel != 1))
                    throw new InvalidOperationException("First action must be no-op");
                if (pendingAction != null) throw new InvalidOperationException("Action queue full");
                if (InputSettingsIdentity() != frozenSettings) throw new InvalidOperationException("Input settings changed");
                pendingAction = new PendingAction { Binary = (int[])binary.Clone(), Mouse = mouse, Wheel = wheel,
                    CaptureTicks = captureTicks, InferenceTicks = inferenceTicks };
            }
            catch (Exception error)
            {
                // Rejection never leaves a previous action held.
                Emit("control_request", Json.Fields("operation", "rejected", "reason", error.Message,
                    "catalog", catalog, "binary", binary, "mouse", mouse, "wheel", wheel));
                if (controlMode == "policy") { pendingAction = null; EndEpisode(reason: "injection_failure"); ReleaseControls(); }
                throw;
            }
        }

        private bool ControlReady => active && episode != null && episode["start_ticks"] != null &&
            episode["end_ticks"] == null && HasControlFocus && GameMain.isRunning && !GameMain.isLoading;

        private NativeInput Button(int index, bool down)
        {
            if (ModelAction.ScanCodes[index] != 0)
                return new NativeInput { Type = 1, Data = new InputUnion { Keyboard = new KeyboardInput {
                    Scan = ModelAction.ScanCodes[index], Flags = (uint)(8 | (down ? 0 : 2)) } } };
            uint flag = new uint[] { 2, 8, 32 }[index - 15];
            return new NativeInput { Type = 0, Data = new InputUnion { Mouse = new MouseInput { Flags = down ? flag : flag * 2 } } };
        }

        private void InjectAction(int[] binary, int mouse, int wheel, long captureTicks = 0, long inferenceTicks = 0)
        {
            if (!HasControlFocus) { EndEpisode(reason: "focus_loss"); throw new InvalidOperationException("Game lost foreground focus"); }
            ModelAction.Validate(ModelAction.Catalog, binary, mouse, wheel);
            var inputs = new List<NativeInput>();
            // Releases precede presses, including switching between mouse buttons or opposing keys.
            for (int i = 0; i < 20; i++) if (injected[i] == 1 && binary[i] == 0) inputs.Add(Button(i, false));
            for (int i = 0; i < 20; i++) if (injected[i] == 0 && binary[i] == 1) inputs.Add(Button(i, true));
            var scale = NativeScale();
            int dx = (int)Math.Round(ModelAction.Pixel(mouse / 11) * scale[0]);
            int dy = (int)Math.Round(ModelAction.Pixel(mouse % 11) * scale[1]);
            if (dx != 0 || dy != 0) inputs.Add(new NativeInput { Type = 0, Data = new InputUnion {
                Mouse = new MouseInput { X = dx, Y = dy, Flags = 1 } } });
            if (wheel != 1) inputs.Add(new NativeInput { Type = 0, Data = new InputUnion {
                Mouse = new MouseInput { Data = unchecked((uint)((wheel - 1) * 120)), Flags = 0x800 } } });
            long now = Stopwatch.GetTimestamp();
            uint sent = inputs.Count == 0 ? 0 : SendInput((uint)inputs.Count, inputs.ToArray(), Marshal.SizeOf(typeof(NativeInput)));
            int error = sent == inputs.Count ? 0 : Marshal.GetLastWin32Error();
            lastAction = now;
            injected = (int[])binary.Clone();
            Emit("control_request", Json.Fields("operation", "model_action", "request_id", ++requestId,
                "catalog", ModelAction.Catalog, "binary", binary, "mouse", mouse, "wheel", wheel,
                "native_delta", new[] { dx, dy }, "requested_ticks", now, "capture_ticks", captureTicks,
                "inference_ticks", inferenceTicks, "requested_count", inputs.Count, "sent_count", sent,
                "succeeded", sent == inputs.Count, "win32_error", error, "mode", controlMode));
            if (sent != inputs.Count) { EndEpisode(reason: "injection_failure"); throw new IOException("SendInput incomplete"); }
        }

        private void ControlUpdate()
        {
            if (!active) return;
            if (!HasControlFocus) { EndEpisode(reason: "focus_loss"); return; }
            if (!ControlReady) return;
            if (InputSettingsIdentity() != frozenSettings) { EndEpisode(reason: "fingerprint_mismatch"); return; }
            if (controlMode == "human") return;
            if (selectedDiagnostic != "full") { RunDiagnostic(); return; }
            long now = Stopwatch.GetTimestamp();
            if (controlMode == "policy")
            {
                if (lastAction != 0 && now - lastAction < Stopwatch.Frequency / 10) return;
                if (pendingAction != null && now - pendingAction.CaptureTicks <= Stopwatch.Frequency / 10)
                {
                    var action = pendingAction;
                    pendingAction = null;
                    InjectAction(action.Binary, action.Mouse, action.Wheel, action.CaptureTicks, action.InferenceTicks);
                    policyStarted = true;
                }
                else if (lastAction != 0 || pendingAction != null)
                {
                    Emit("control_request", Json.Fields("operation", "deadline_miss", "previous_request_id", requestId));
                    EndEpisode(reason: "injection_failure");
                }
                return;
            }
            if (nextProbe == 0) nextProbe = now + Stopwatch.Frequency;
            if (now < nextProbe) return;
            if (probeRelease)
            {
                if (!ReleaseControls()) { EndEpisode(reason: "injection_failure"); return; }
                probeRelease = false;
            }
            else
            {
                probe++;
                if (probe >= 45) { stopPending = true; EndEpisode(reason: "stopped"); return; }
                if (probe == 44)
                {
                    // Diagnostic identity probe only; Numpad1 is never accepted by SubmitAction.
                    var input = new NativeInput { Type = 1, Data = new InputUnion {
                        Keyboard = new KeyboardInput { Scan = 0x4F, Flags = 8 } } };
                    long requested = Stopwatch.GetTimestamp();
                    uint sent = SendInput(1, new[] { input }, Marshal.SizeOf(typeof(NativeInput)));
                    Emit("control_request", Json.Fields("operation", "identity_probe", "scan_code", 0x4F,
                        "allowed_held", new[] { "Keypad1", "End" }, "requested_ticks", requested, "requested_count", 1,
                        "sent_count", sent, "succeeded", sent == 1, "mode", controlMode));
                    if (sent != 1) { EndEpisode(reason: "injection_failure"); return; }
                    probeRelease = true;
                    nextProbe = Stopwatch.GetTimestamp() + Stopwatch.Frequency / 5;
                    return;
                }
                var binary = new int[20];
                int mouse = 60, wheel = 1;
                // Escape runs after all clicks so the probe never clicks the pause menu.
                if (probe < 20) binary[(probe + 1) % 20] = 1;
                else if (probe < 31) mouse = (probe - 20) * 11 + 5;
                else if (probe < 42) mouse = 55 + probe - 31;
                else wheel = probe == 42 ? 2 : 0;
                InjectAction(binary, mouse, wheel);
                probeRelease = true;
            }
            nextProbe = Stopwatch.GetTimestamp() + Stopwatch.Frequency / 5;
        }

        private void OnApplicationFocus(bool focused)
        {
            if (focused || !active) return;
            EndEpisode(reason: "focus_loss");
            ReleaseControls();
        }

        private void OnDisable()
        {
            if (Current != this) return;
            diagnosticObserver?.Record("callback", Json.Fields("name", "OnDisable"));
            EndEpisode(reason: "stopped");
            StopRecording();
            ReleaseControls();
            diagnosticObserver?.Record("callback_completed", Json.Fields("name", "OnDisable"));
        }
    }
}
