using BepInEx.Configuration;
using HarmonyLib;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;

namespace DSPDreamer.Recorder
{
    public sealed partial class RecorderPlugin
    {
        private ConfigEntry<string> diagnosticCase;
        private string selectedDiagnostic = "full";
        private bool diagnosticSent, failFinalReadback;
        private long diagnosticStarted;
        private DiagnosticObserver diagnosticObserver;

        private void ValidateDiagnosticCase(string mode)
        {
            selectedDiagnostic = mode == "calibration" ? diagnosticCase.Value : "full";
            if (!new[] { "full", "focus_hold", "final_readback", "disable", "destroy" }.Contains(selectedDiagnostic))
                throw new InvalidOperationException("Unknown Diagnostics.Case");
        }

        private void StartDiagnosticObserver()
        {
            var host = new GameObject("DSP diagnostic observer");
            DontDestroyOnLoad(host);
            diagnosticObserver = host.AddComponent<DiagnosticObserver>();
            try { diagnosticObserver.Initialize(this, source, selectedDiagnostic, metadata); }
            catch { Destroy(host); throw; }
        }

        private void RunDiagnostic()
        {
            long now = Stopwatch.GetTimestamp();
            if (diagnosticStarted == 0) diagnosticStarted = now;
            if (now - diagnosticStarted < Stopwatch.Frequency) return;
            if (!diagnosticSent)
            {
                var binary = new int[20]; binary[4] = 1;
                InjectAction(binary, 60, 1);
                diagnosticSent = true;
                Logger.LogInfo("Diagnostic W held: " + selectedDiagnostic + "; focus_hold: Alt+Tab now (30 second limit)");
                return;
            }
            if (now - diagnosticStarted > 30 * Stopwatch.Frequency)
            {
                EndEpisode(reason: "stopped");
                return;
            }
            if (selectedDiagnostic == "focus_hold" || now - diagnosticStarted < 2 * Stopwatch.Frequency) return;
            // Require actual DSP input evidence before invoking a lifecycle callback.
            if (!Input.GetKey(KeyCode.W)) { EndEpisode(reason: "recorder_fault"); return; }
            Emit("control_request", Json.Fields("operation", "diagnostic_fault", "case", selectedDiagnostic, "simulated", true));
            if (selectedDiagnostic == "final_readback")
            {
                failFinalReadback = true;
                EndEpisode(reason: "stopped");
            }
            else if (selectedDiagnostic == "disable") enabled = false;
            else Destroy(this);
        }

        internal bool DiagnosticPublicationFinished => writer == null;
        internal bool DiagnosticPublicationFailed => failed;
    }

    // Separate Unity object and Harmony owner survive disabling/destroying the recorder component.
    public sealed class DiagnosticObserver : MonoBehaviour
    {
        private static DiagnosticObserver current;
        private RecorderPlugin recorder;
        private Harmony observerHarmony;
        private StreamWriter journal;
        private string path;
        private long started, ended, index;
        private bool complete, journalFailed;
        internal bool Running => !complete;

        internal void Initialize(RecorderPlugin target, string source, string test, Dictionary<string, object> metadata)
        {
            if (current != null) throw new InvalidOperationException("Diagnostic observer already active");
            recorder = target;
            path = source + ".diagnostic.ndjson";
            journal = new StreamWriter(new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read), new UTF8Encoding(false)) { AutoFlush = true };
            current = this;
            started = Stopwatch.GetTimestamp();
            Record("header", Json.Fields("schema", "dsp-diagnostic/1", "case", test, "source", source,
                "runtime", metadata["runtime"], "recording_session_id", metadata["recording_session_id"],
                "ticks_frequency", Stopwatch.Frequency));
            observerHarmony = new Harmony("tw.jaywu.dspdreamer.diagnostic");
            observerHarmony.Patch(AccessTools.Method(typeof(VFInput), nameof(VFInput.OnUpdate)),
                postfix: new HarmonyMethod(typeof(DiagnosticObserver), nameof(ObserveInput)));
        }

        internal void Record(string type, Dictionary<string, object> fields)
        {
            if (complete || journal == null) return;
            var row = Json.Fields("index", index++, "ticks", Stopwatch.GetTimestamp(), "type", type);
            foreach (var pair in fields) row[pair.Key] = pair.Value;
            // Evidence I/O must never prevent the recorder's safety release.
            if (!journalFailed)
                try { journal.WriteLine(Json.Encode(row)); }
                catch (Exception error) { journalFailed = true; UnityEngine.Debug.LogException(error); }
            if (type == "game_event" && fields.TryGetValue("name", out object name) && (string)name == "episode_ended")
                ended = Stopwatch.GetTimestamp();
        }

        private static void ObserveInput()
        {
            if (current == null || current.complete) return;
            if (current.ended != 0 && Stopwatch.GetTimestamp() - current.ended > 3 * Stopwatch.Frequency) return;
            current.Record("input", Json.Fields("held", RecorderPlugin.Keys.Where(Input.GetKey).Select(k => k.ToString()).ToArray(),
                "down", RecorderPlugin.Keys.Where(Input.GetKeyDown).Select(k => k.ToString()).ToArray(),
                "up", RecorderPlugin.Keys.Where(Input.GetKeyUp).Select(k => k.ToString()).ToArray(), "focused", Application.isFocused,
                "unity_frame", Time.frameCount));
        }

        private void Update()
        {
            if (complete) return;
            // Calling a managed finalization method remains valid after Unity destroys its component.
            recorder.PumpFinalization();
            long now = Stopwatch.GetTimestamp();
            if (ended != 0 && now - ended >= 3 * Stopwatch.Frequency && recorder.DiagnosticPublicationFinished)
                Finish(!recorder.DiagnosticPublicationFailed);
            else if (now - started > 180 * Stopwatch.Frequency) Finish(false);
        }

        private void Finish(bool published)
        {
            Record("completed", Json.Fields("published", published));
            complete = true;
            try { journal.Dispose(); }
            catch (Exception error) { journalFailed = true; UnityEngine.Debug.LogException(error); }
            observerHarmony.UnpatchSelf();
            if (!journalFailed)
                try { File.WriteAllText(path + ".complete.json", Json.Encode(Json.Fields("sha256", SegmentWriter.HashFile(path))), new UTF8Encoding(false)); }
                catch (Exception error) { journalFailed = true; UnityEngine.Debug.LogException(error); }
            current = null;
            UnityEngine.Debug.Log("DSP diagnostic evidence " + (journalFailed ? "FAILED: " : "completed: ") + path);
            Destroy(gameObject);
        }

        private void OnDestroy()
        {
            if (complete) return;
            try { journal?.Dispose(); }
            finally
            {
                observerHarmony?.UnpatchSelf();
                if (current == this) current = null;
            }
        }
    }
}
