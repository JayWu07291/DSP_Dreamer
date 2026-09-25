using BepInEx.Configuration;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using UnityEngine;

namespace DSPDreamer.Recorder
{
    public sealed partial class RecorderPlugin
    {
        private ConfigEntry<string> policyCheckpoint, policyDevice;
        private ConfigEntry<int> policyDelay;
        private Process policyWorker;
        private readonly object policyGate = new object();
        private readonly Queue<Dictionary<string, object>> policyInputs = new Queue<Dictionary<string, object>>();
        private readonly List<double> policyLatencies = new List<double>();
        private string policyReply, policyError;
        private bool policyBusy, runnerStarting;
        private long policyCapture, policyCaptureId, policyNext, policyStep, policyMisses, policyStreak;
        private long policyClockOffset;
        private PolicyReply runnerIdentity, runnerAction;
        private IntPtr policyKeyboardHook, policyMouseHook;
        private HookCallback policyKeyboardCallback, policyMouseCallback;
        private volatile bool humanInput, watchHumanInput;
        private Thread policyHookThread;
        private ManualResetEvent policyHookStop;
        private delegate IntPtr HookCallback(int code, IntPtr message, IntPtr data);
        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr SetWindowsHookEx(int kind, HookCallback callback, IntPtr module, uint thread);
        [DllImport("user32.dll")]
        private static extern bool UnhookWindowsHookEx(IntPtr hook);
        [DllImport("user32.dll")]
        private static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr message, IntPtr data);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr GetModuleHandle(string name);
        [DllImport("kernel32.dll")]
        private static extern bool QueryPerformanceCounter(out long ticks);
        [DllImport("kernel32.dll")]
        private static extern bool QueryPerformanceFrequency(out long frequency);
        [StructLayout(LayoutKind.Sequential)]
        private struct HookMessage
        {
            public IntPtr Window;
            public uint Message;
            public UIntPtr WParam;
            public IntPtr LParam;
            public uint Time;
            public int X, Y;
            public uint Private;
        }
        [DllImport("user32.dll")]
        private static extern bool PeekMessage(out HookMessage message, IntPtr window, uint min, uint max, uint remove);
        [DllImport("user32.dll")]
        private static extern IntPtr DispatchMessage(ref HookMessage message);

        private void WatchHumanInput()
        {
            humanInput = false;
            policyKeyboardCallback = (code, message, data) => {
                if (code >= 0 && watchHumanInput && ((Marshal.ReadInt32(data, 8) & 0x10) == 0 ||
                    Marshal.ReadInt64(data, 16) != (long)ControlTag.ToUInt64())) humanInput = true;
                return CallNextHookEx(IntPtr.Zero, code, message, data);
            };
            policyMouseCallback = (code, message, data) => {
                if (code >= 0 && watchHumanInput && ((Marshal.ReadInt32(data, 12) & 1) == 0 ||
                    Marshal.ReadInt64(data, 24) != (long)ControlTag.ToUInt64())) humanInput = true;
                return CallNextHookEx(IntPtr.Zero, code, message, data);
            };
            policyHookStop = new ManualResetEvent(false);
            // Low-level callbacks are delivered to the installing thread. Never block its pump in SendInput.
            using (var ready = new ManualResetEvent(false))
            {
                Exception failure = null;
                policyHookThread = new Thread(() => {
                    try
                    {
                        policyKeyboardHook = SetWindowsHookEx(13, policyKeyboardCallback, GetModuleHandle(null), 0);
                        policyMouseHook = SetWindowsHookEx(14, policyMouseCallback, GetModuleHandle(null), 0);
                        if (policyKeyboardHook == IntPtr.Zero || policyMouseHook == IntPtr.Zero)
                            throw new IOException("Cannot monitor human intervention");
                    }
                    catch (Exception error) { failure = error; }
                    finally { ready.Set(); }
                    try
                    {
                        if (failure == null)
                            do
                            {
                                while (!policyHookStop.WaitOne(0) && PeekMessage(out HookMessage message, IntPtr.Zero, 0, 0, 1))
                                    DispatchMessage(ref message);
                            } while (!policyHookStop.WaitOne(1));
                    }
                    finally
                    {
                        if (policyKeyboardHook != IntPtr.Zero) UnhookWindowsHookEx(policyKeyboardHook);
                        if (policyMouseHook != IntPtr.Zero) UnhookWindowsHookEx(policyMouseHook);
                        policyKeyboardHook = policyMouseHook = IntPtr.Zero;
                    }
                }) { IsBackground = true, Name = "DSP input monitor" };
                policyHookThread.Start();
                ready.WaitOne();
                if (failure != null) throw failure;
            }
        }

        private void StopHumanInputWatch()
        {
            watchHumanInput = false;
            if (policyHookThread == null) return;
            policyHookStop.Set();
            policyHookThread.Join();
            policyHookThread = null;
            policyHookStop.Dispose();
            policyHookStop = null;
        }

        [Serializable]
        private sealed class PolicyReply
        {
            public bool ready = false, qualified = false;
            public string status = "", checkpoint_sha256 = "", action_codec_sha256 = "", episode_id = "";
            public long frequency = 0, capture_id = 0, capture_ticks = 0, inference_started_ticks = 0, inference_ticks = 0;
            public int[] binary = null;
            public int mouse = 60, wheel = 1;
        }

        private void ConfigureRunner()
        {
            policyCheckpoint = Config.Bind("Policy", "Checkpoint", "", "F5 啟動的 engineering_only checkpoint；正式候選另驗收。");
            policyDevice = Config.Bind("Policy", "Device", "cuda", "cuda 或 cpu。");
            policyDelay = Config.Bind("Policy", "DelayMs", 0, "工程逾時測試；推理後延遲 0–1000 ms。");
        }

        private void StartRunner()
        {
            if (active || writer != null || policyWorker != null) throw new InvalidOperationException("Recording/runner already active");
            Config.Reload();
            if (!File.Exists(policyCheckpoint.Value) || policyCheckpoint.Value.Contains('"') ||
                (policyDevice.Value != "cuda" && policyDevice.Value != "cpu") || policyDelay.Value < 0 || policyDelay.Value > 1000)
                throw new InvalidOperationException("Invalid engineering policy configuration");
            // Unity Mono's Stopwatch has a process-relative origin; Python uses raw Windows QPC.
            if (!QueryPerformanceCounter(out long counter) || !QueryPerformanceFrequency(out long frequency) ||
                frequency != Stopwatch.Frequency) throw new InvalidOperationException("Incompatible control clock");
            long before = Stopwatch.GetTimestamp();
            if (!QueryPerformanceCounter(out counter)) throw new InvalidOperationException("Control clock unavailable");
            policyClockOffset = counter - (before + (Stopwatch.GetTimestamp() - before) / 2);
            var start = new ProcessStartInfo(python.Value, "-m dsp_dreamer.runner --engineering-only --checkpoint \"" +
                policyCheckpoint.Value + "\" --device " + policyDevice.Value + " --delay-ms " + policyDelay.Value +
                " --clock-offset-ticks " + policyClockOffset)
            { WorkingDirectory = repository.Value, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
            policyWorker = Process.Start(start);
            policyWorker.ErrorDataReceived += (_, args) => { if (args.Data != null) Logger.LogWarning(args.Data); };
            policyWorker.BeginErrorReadLine();
            runnerStarting = true;
            ExchangePolicy(null, null);
        }

        // A single in-flight exchange bounds memory. Pipe I/O and inference never block Unity's watchdog.
        private void ExchangePolicy(string header, byte[] pixels)
        {
            lock (policyGate)
            {
                if (policyBusy || policyReply != null) return;
                policyBusy = true;
            }
            var worker = policyWorker;
            new Thread(() => {
                try
                {
                    if (header != null)
                    {
                        byte[] bytes = Encoding.UTF8.GetBytes(header + "\n");
                        var stream = worker.StandardInput.BaseStream;
                        stream.Write(bytes, 0, bytes.Length);
                        stream.Write(pixels, 0, pixels.Length);
                        stream.Flush();
                    }
                    string reply = worker.StandardOutput.ReadLine();
                    if (reply == null || reply.Length > 16384) throw new IOException("Policy worker closed or invalid response");
                    lock (policyGate) { if (policyWorker == worker) policyReply = reply; }
                }
                catch (Exception ex) { lock (policyGate) { if (policyWorker == worker) policyError = ex.Message; } }
                finally { lock (policyGate) { if (policyWorker == worker) policyBusy = false; } }
            }) { IsBackground = true, Name = "DSP policy pipe" }.Start();
        }

        private void CloseRunner()
        {
            StopHumanInputWatch();
            var worker = policyWorker;
            lock (policyGate) { policyWorker = null; policyReply = policyError = null; policyBusy = false; }
            runnerStarting = false;
            runnerAction = runnerIdentity = null;
            policyInputs.Clear();
            if (worker == null) return;
            try { if (!worker.HasExited) worker.Kill(); }
            catch (Exception error) { Logger.LogWarning("Policy worker cleanup: " + error.Message); }
            finally { worker.Dispose(); }
        }

        private void RunnerCapture(Slot slot)
        {
            if (runnerIdentity == null || !ControlReady || slot.Identity["episode_id"].ToString() != episode["episode_id"].ToString()) return;
            long ticks = (long)slot.Identity["requested_ticks"];
            if (policyNext == 0) policyNext = ticks;
            if (ticks < policyNext || policyCapture != 0) return;
            // The nominal 10 Hz clock continues even when a capture or inference is missing.
            if (ticks >= policyNext + Stopwatch.Frequency / 10) return;
            policyCapture = ticks;
            policyCaptureId = (long)slot.Identity["capture_id"];
            string header = Json.Encode(Json.Fields("episode_id", episode["episode_id"], "capture_id", policyCaptureId,
                "capture_ticks", ticks, "task_id", slot.Identity["task_id"], "policy_seed", trial["policy_seed"],
                "inputs", policyInputs.ToArray()));
            ExchangePolicy(header, (byte[])slot.Pixels.Clone());
        }

        private void RunnerUpdate()
        {
            if (policyWorker == null) return;
            watchHumanInput = ProgressEnabled;
            string response, error;
            lock (policyGate) { response = policyReply; policyReply = null; error = policyError; policyError = null; }
            if (error != null)
            {
                // Update owns shutdown so a worker fault still captures the final observation.
                throw new IOException(error);
            }
            if (response != null)
            {
                var value = JsonUtility.FromJson<PolicyReply>(response);
                if (runnerStarting)
                {
                    if (!value.ready || value.qualified || value.status != "engineering_only" || value.frequency != Stopwatch.Frequency ||
                        value.checkpoint_sha256 != SegmentWriter.HashFile(policyCheckpoint.Value) || value.action_codec_sha256 != ModelAction.CodecSha256)
                        throw new InvalidOperationException("Unqualified or incompatible policy worker");
                    runnerIdentity = value;
                    runnerStarting = false;
                    policyNext = policyCapture = policyStep = policyMisses = policyStreak = 0;
                    policyLatencies.Clear();
                    policyInputs.Clear();
                    StartPolicyRecording();
                    if (!active) throw new InvalidOperationException("Policy recording did not start");
                    metadata["runner"] = Json.Fields("status", value.status, "qualified", false,
                        "checkpoint_sha256", value.checkpoint_sha256, "action_codec_sha256", value.action_codec_sha256,
                        "delay_ms", policyDelay.Value, "history_steps", 64, "signal", .1,
                        "qpc_offset_ticks", policyClockOffset);
                    WatchHumanInput();
                }
                else if (ControlReady && value.episode_id == (string)episode["episode_id"] &&
                         value.capture_ticks == policyCapture && value.capture_id == policyCaptureId)
                {
                    ModelAction.Validate(ModelAction.Catalog, value.binary, value.mouse, value.wheel);
                    if (value.inference_started_ticks < policyCapture || value.inference_ticks < value.inference_started_ticks ||
                        value.inference_ticks > Stopwatch.GetTimestamp()) throw new InvalidOperationException("Invalid inference timestamps");
                    runnerAction = value;
                }
                else Emit("control_request", Json.Fields("operation", "stale_policy_response", "capture_ticks", value.capture_ticks,
                    "inference_started_ticks", value.inference_started_ticks, "inference_ticks", value.inference_ticks));
            }
            if (!ControlReady || runnerIdentity == null || policyNext == 0) return;
            if (humanInput) { EndEpisode(reason: "human_intervention"); return; }
            long now = Stopwatch.GetTimestamp(), period = Stopwatch.Frequency / 10;
            long start = policyCapture != 0 ? policyCapture : policyNext;
            if (now - start > period)
            {
                if (!ReleaseControls()) { EndEpisode(reason: "injection_failure"); return; }
                InjectAction(new int[ModelAction.Controls.Length], 60, 1, start);
                CompletePolicyStep(true, start);
            }
            else if (runnerAction != null && (injected[15] == 0 || runnerAction.binary[15] == 1 || now - leftDownTicks >= period))
            {
                var action = runnerAction;
                if (!policyStarted && (action.binary.Any(v => v != 0) || action.mouse != 60 || action.wheel != 1))
                    throw new InvalidOperationException("First action must be no-op");
                InjectAction(action.binary, action.mouse, action.wheel, start, action.inference_ticks);
                CompletePolicyStep(false, start);
            }
        }

        private void CompletePolicyStep(bool missed, long start)
        {
            policyStarted = true;
            double latency = (lastAction - start) * 1000.0 / Stopwatch.Frequency;
            missed |= latency > 100;
            policyLatencies.Add(latency);
            policyStreak = missed ? policyStreak + 1 : 0;
            if (missed) policyMisses++;
            Emit("control_request", Json.Fields("operation", "runner_step", "step", policyStep++, "capture_ticks", start,
                "capture_id", policyCapture == 0 ? (object)null : policyCaptureId,
                "inference_started_ticks", runnerAction == null ? (object)null : runnerAction.inference_started_ticks,
                "inference_ticks", runnerAction == null ? (object)null : runnerAction.inference_ticks,
                "requested_ticks", lastAction, "request_id", requestId, "missed", missed));
            policyNext += Stopwatch.Frequency / 10;
            policyCapture = 0;
            runnerAction = null;
            if (policyStreak >= 5) EndEpisode(reason: "system_latency");
        }

        private bool RunnerTimingPassed()
        {
            return PolicyTiming.Passed(policyLatencies.ToArray(), policyMisses, policyStreak);
        }
    }
}
