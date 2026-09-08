using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using UnityEngine;
using UnityEngine.Rendering;

namespace DSPDreamer.Recorder
{
    [BepInPlugin("tw.jaywu.dspdreamer.recorder", "DSP Dreamer Recorder", "0.1.0")]
    public sealed class RecorderPlugin : BaseUnityPlugin
    {
        internal static RecorderPlugin Current;
        private ConfigEntry<string> output, ffmpeg, approved, python, repository;
        private Harmony harmony;
        private Slot[] slots;
        private readonly BlockingCollection<Slot> frames = new BlockingCollection<Slot>(12);
        private readonly BlockingCollection<string> events = new BlockingCollection<string>(4096);
        private readonly Dictionary<int, CursorGlyph> glyphs = new Dictionary<int, CursorGlyph>();
        private SegmentWriter storage;
        private Thread writer;
        private volatile bool active, failed, drained;
        private bool stopping;
        private long sequence, capture, nextDue, startTicks;
        private int pending;
        private int lastInputFrame = -1;
        private string source;
        private Dictionary<string, object> metadata;
        private GameHistoryData history;
        private readonly string session = Guid.NewGuid().ToString();
        private readonly Dictionary<string, int> dismantles = new Dictionary<string, int>();
        private static readonly KeyCode[] Keys = Enum.GetValues(typeof(KeyCode)).Cast<KeyCode>()
            .Where(k => (int)k > 0 && (int)k < (int)KeyCode.JoystickButton0).Distinct().ToArray();

        private sealed class Slot
        {
            internal readonly byte[] Pixels = new byte[640 * 360 * 4];
            internal RenderTexture Full, Small;
            internal int Busy;
            internal Dictionary<string, object> Identity;
        }

        private void Awake()
        {
            Current = this;
            output = Config.Bind("Recording", "Output", Path.Combine(Paths.PluginPath, "DSPDreamer", "runs"));
            ffmpeg = Config.Bind("Recording", "FFmpeg", "", "Exact pinned FFmpeg 6.1.1 executable.");
            approved = Config.Bind("Recording", "ApprovedFingerprint", "", "Reviewed runtime candidate SHA-256. Unknown fingerprints refuse capture.");
            python = Config.Bind("Recording", "Python", "", "Python with dsp-dreamer dependencies.");
            repository = Config.Bind("Recording", "Repository", "", "Production dsp_dreamer package directory.");
            harmony = new Harmony("tw.jaywu.dspdreamer.recorder");
            harmony.PatchAll(typeof(RecorderPlugin).Assembly);
            StartCoroutine(CaptureLoop());
        }

        private Dictionary<string, object> Runtime()
        {
            var hashes = Json.Fields();
            foreach (var assembly in new[] { typeof(GameMain).Assembly, typeof(BaseUnityPlugin).Assembly,
                     typeof(Harmony).Assembly, typeof(RecorderPlugin).Assembly, typeof(Input).Assembly,
                     typeof(ScreenCapture).Assembly, typeof(RenderTexture).Assembly })
                hashes[assembly.GetName().Name] = SegmentWriter.HashFile(assembly.Location);
            hashes["UnityPlayer"] = SegmentWriter.HashFile(Path.Combine(Paths.GameRootPath, "UnityPlayer.dll"));
            hashes["DSPGAME"] = SegmentWriter.HashFile(Path.Combine(Paths.GameRootPath, "DSPGAME.exe"));
            if ((string)hashes["Assembly-CSharp"] != "ae0ba95f75bd879a62aa4ce253b2ab78eaa4fb3c7c595f5e1fee75ebe0e0ef85")
                throw new InvalidOperationException("Unknown game binary fingerprint");
            if (typeof(BaseUnityPlugin).Assembly.GetName().Version.ToString() != "5.4.23.5" ||
                typeof(Harmony).Assembly.GetName().Version.ToString() != "2.9.0.0" || IntPtr.Size != 8 ||
                Application.platform != RuntimePlatform.WindowsPlayer)
                throw new InvalidOperationException("Unsupported runtime");
            return Json.Fields("bepinex_version", "5.4.23.5", "harmonyx_version", "2.9.0",
                "platform", "Windows x64 Unity Mono", "target_framework", "net472",
                "game_version", GameConfig.gameVersion + "." + GameConfig.build, "unity_version", Application.unityVersion,
                "plugin_version", "0.1.0", "binary_hashes", hashes,
                "input_settings_sha256", SegmentWriter.HashFile(GameConfig.gameXMLOptionPath),
                "screen_width", Screen.width, "screen_height", Screen.height,
                "graphics_device", SystemInfo.graphicsDeviceType.ToString());
        }

        private void StartRecording()
        {
            if (writer != null || failed || !GameMain.isRunning || !Application.isFocused) return;
            Config.Reload();
            var runtime = Runtime();
            string candidate = Json.Encode(runtime);
            string digest = SegmentWriter.Hash(Encoding.UTF8.GetBytes(candidate));
            Directory.CreateDirectory(output.Value);
            File.WriteAllText(Path.Combine(output.Value, "runtime-candidate.json"), candidate, new UTF8Encoding(false));
            if (digest != approved.Value)
                throw new InvalidOperationException("Unknown fingerprint. Review runtime-candidate.json; SHA-256=" + digest);
            runtime["fingerprint_verified"] = true;
            runtime["approved_fingerprint"] = digest;
            source = Path.Combine(output.Value, Guid.NewGuid().ToString() + ".source");
            Directory.CreateDirectory(source);
            metadata = Json.Fields("schema", "dsp-recording/1", "catalog", "action_catalog_v2", "source_kind", "live",
                "recording_session_id", session, "attempt_id", Guid.NewGuid().ToString(), "episode_id", Guid.NewGuid().ToString(),
                "ticks_frequency", Stopwatch.Frequency, "runtime", runtime);
            slots = Enumerable.Range(0, 12).Select(_ => new Slot {
                Full = new RenderTexture(Screen.width, Screen.height, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB),
                Small = new RenderTexture(640, 360, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB)
            }).ToArray();
            foreach (var slot in slots) { slot.Full.Create(); slot.Small.Create(); }
            storage = new SegmentWriter(source, ffmpeg.Value);
            sequence = capture = 0;
            lastInputFrame = -1;
            failed = drained = stopping = false;
            startTicks = nextDue = Stopwatch.GetTimestamp();
            writer = new Thread(Write) { IsBackground = true, Name = "DSP recording writer" };
            writer.Start();
            active = true;
            BindWorld();
            Logger.LogInfo("Recording started: " + source);
        }

        private Dictionary<string, object> Identity(long ticks)
        {
            return Json.Fields("ticks", ticks, "sequence_number", sequence++);
        }

        private void Emit(string type, Dictionary<string, object> fields)
        {
            if (!active) return;
            var row = Identity(Stopwatch.GetTimestamp());
            row["type"] = type;
            row["unity_frame"] = Time.frameCount;
            row["game_tick"] = GameMain.gameTick;
            foreach (var pair in fields) row[pair.Key] = pair.Value;
            if (!events.TryAdd(Json.Encode(row))) { failed = true; active = false; }
        }

        internal void RecordInput()
        {
            if (!active || lastInputFrame == Time.frameCount) return;
            lastInputFrame = Time.frameCount;
            Func<KeyCode, string> name = key => key == KeyCode.Alpha1 ? "Digit1" : key == KeyCode.Alpha2 ? "Digit2" :
                key == KeyCode.Mouse0 ? "MouseLeft" : key == KeyCode.Mouse1 ? "MouseRight" : key == KeyCode.Mouse2 ? "MouseMiddle" : key.ToString();
            Emit("input", Json.Fields("held", Keys.Where(Input.GetKey).Select(name).ToArray(),
                "down", Keys.Where(Input.GetKeyDown).Select(name).ToArray(), "up", Keys.Where(Input.GetKeyUp).Select(name).ToArray(),
                "delta", new[] { VFInput.mouseMoveAxis.x, VFInput.mouseMoveAxis.y }, "wheel", VFInput.mouseWheel,
                "horizontal_wheel", Input.mouseScrollDelta.x, "mouse_x", Input.mousePosition.x, "mouse_y", Input.mousePosition.y,
                "focused", Application.isFocused, "paused", GameMain.isPaused, "inputing", VFInput.inputing,
                "in_screen", VFInput.inScreen, "fullscreen_ui", VFInput.inFullscreenGUI));
        }

        private IEnumerator CaptureLoop()
        {
            var end = new WaitForEndOfFrame();
            while (true)
            {
                yield return end;
                if (!active) continue;
                if (lastInputFrame != Time.frameCount) continue;
                long now = Stopwatch.GetTimestamp();
                if (now < nextDue) continue;
                long period = Stopwatch.Frequency / 20;
                if (now >= nextDue + period) Emit("gap", Json.Fields("reason", "scheduler", "missed", (now - nextDue) / period,
                    "gap_start_ticks", nextDue, "gap_end_ticks", now));
                nextDue += ((now - nextDue) / period + 1) * period;
                Slot slot = slots.FirstOrDefault(s => Interlocked.CompareExchange(ref s.Busy, 1, 0) == 0);
                if (slot == null) { Emit("gap", Json.Fields("reason", "no_free_buffer")); continue; }
                try
                {
                    var cursor = SnapshotCursor();
                    slot.Identity = Identity(now);
                    slot.Identity["requested_ticks"] = now;
                    slot.Identity["capture_id"] = capture++;
                    slot.Identity["unity_frame"] = Time.frameCount;
                    slot.Identity["game_tick"] = GameMain.gameTick;
                    slot.Identity["cursor"] = cursor.Item1;
                    ScreenCapture.CaptureScreenshotIntoRenderTexture(slot.Full);
                    Graphics.Blit(slot.Full, slot.Small);
                    pending++;
                    try { AsyncGPUReadback.Request(slot.Small, 0, TextureFormat.RGBA32, request =>
                    {
                        try
                        {
                            if (request.hasError) throw new IOException("GPU readback failed");
                            request.GetData<byte>().CopyTo(slot.Pixels);
                            cursor.Item2(slot.Pixels);
                            if (!frames.TryAdd(slot)) throw new IOException("Writer queue full");
                        }
                        catch (Exception ex) { failed = true; active = false; Logger.LogError(ex); }
                        finally { pending--; }
                    }); }
                    catch { pending--; throw; }
                }
                catch (Exception ex) { failed = true; active = false; slot.Busy = 0; Logger.LogError(ex); }
            }
        }

        private Tuple<Dictionary<string, object>, Action<byte[]>> SnapshotCursor()
        {
            bool visible = Cursor.visible;
            Vector3 mouse = Input.mousePosition;
            float sx = 640f / Screen.width, sy = 360f / Screen.height;
            var info = Json.Fields("visible", visible, "x", mouse.x * sx, "y", (Screen.height - mouse.y) * sy,
                                  "index", UICursor.cursorIndexApply);
            if (!visible) return Tuple.Create(info, new Action<byte[]>(_ => { }));
            int index = UICursor.cursorIndexApply;
            var textures = (Texture2D[])AccessTools.Field(typeof(UICursor), "cursorTexs").GetValue(null);
            var hotspots = (Vector2[])AccessTools.Field(typeof(UICursor), "cursorHots").GetValue(null);
            Texture2D texture = textures[index];
            if (!glyphs.TryGetValue(texture.GetInstanceID(), out CursorGlyph glyph))
            {
                Color32[] pixels = texture.GetPixels32();
                byte[] bytes = new byte[pixels.Length * 4];
                for (int y = 0; y < texture.height; y++)
                    for (int x = 0; x < texture.width; x++)
                    {
                        Color32 pixel = pixels[(texture.height - y - 1) * texture.width + x];
                        int offset = (y * texture.width + x) * 4;
                        bytes[offset] = pixel.r; bytes[offset + 1] = pixel.g; bytes[offset + 2] = pixel.b; bytes[offset + 3] = pixel.a;
                    }
                glyph = new CursorGlyph(texture.width, texture.height, bytes);
                glyphs.Add(texture.GetInstanceID(), glyph);
            }
            int left = (int)Math.Round((mouse.x - hotspots[index].x) * sx);
            int top = (int)Math.Round((Screen.height - mouse.y - hotspots[index].y) * sy);
            int width = Math.Max(1, (int)Math.Round(glyph.Width * sx));
            int height = Math.Max(1, (int)Math.Round(glyph.Height * sy));
            return Tuple.Create(info, new Action<byte[]>(bytes => CursorCompositor.Composite(bytes, 640, 360, glyph, left, top, width, height)));
        }

        private void Write()
        {
            var ordered = new SortedDictionary<long, Slot>();
            long next = 0;
            try
            {
                using (var stream = new StreamWriter(new FileStream(Path.Combine(source, "events.ndjson"), FileMode.CreateNew), new UTF8Encoding(false)))
                {
                    while (!drained || frames.Count > 0 || events.Count > 0)
                    {
                        while (events.TryTake(out string row)) stream.WriteLine(row);
                        if (frames.TryTake(out Slot frame, 5)) ordered.Add((long)frame.Identity["capture_id"], frame);
                        while (ordered.TryGetValue(next, out Slot slot))
                        {
                            storage.Write(slot.Pixels, slot.Identity);
                            ordered.Remove(next++);
                            Interlocked.Exchange(ref slot.Busy, 0);
                        }
                    }
                    if (failed || ordered.Count != 0) throw new IOException("Incomplete capture; no SOURCE marker published");
                    storage.Finish();
                    stream.Flush();
                    ((FileStream)stream.BaseStream).Flush(true);
                }
                string partial = Path.Combine(source, "SOURCE.json.partial");
                using (var file = new FileStream(partial, FileMode.CreateNew))
                {
                    byte[] bytes = Encoding.UTF8.GetBytes(Json.Encode(metadata));
                    file.Write(bytes, 0, bytes.Length); file.Flush(true);
                }
                File.Move(partial, Path.Combine(source, "SOURCE.json"));
                var process = new ProcessStartInfo(python.Value, "-m dsp_dreamer finish --source \"" + source + "\" --ffmpeg \"" + ffmpeg.Value + "\"")
                { WorkingDirectory = repository.Value, UseShellExecute = false, CreateNoWindow = true,
                  RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
                using (var worker = Process.Start(process))
                {
                    worker.StandardInput.Close();
                    worker.OutputDataReceived += (_, args) => { if (args.Data != null) Logger.LogInfo(args.Data); };
                    worker.ErrorDataReceived += (_, args) => { if (args.Data != null) Logger.LogError(args.Data); };
                    worker.BeginOutputReadLine(); worker.BeginErrorReadLine(); worker.WaitForExit();
                    if (worker.ExitCode != 0) throw new IOException("Finalize worker failed; source retained");
                }
                Logger.LogInfo("Recording, compilation, and readback completed: " + source);
            }
            catch (Exception ex) { failed = true; active = false; Logger.LogError(ex); }
            finally { storage.Dispose(); }
        }

        private void Update()
        {
            if (Input.GetKeyDown(KeyCode.F8))
            {
                try { if (active) StopRecording(); else if (!stopping) StartRecording(); }
                catch (Exception ex) { Logger.LogError(ex); }
            }
            if (active && (!Application.isFocused || Stopwatch.GetTimestamp() - startTicks > 1800L * Stopwatch.Frequency)) StopRecording();
            if (failed && !stopping && writer != null) StopRecording();
            if (stopping && pending == 0) drained = true;
            if (stopping && writer != null && !writer.IsAlive)
            {
                foreach (var slot in slots) { slot.Full.Release(); slot.Small.Release(); Destroy(slot.Full); Destroy(slot.Small); }
                writer = null; stopping = false;
                Logger.LogInfo(failed ? "Recording failed; source retained" : "Ready for next recording");
            }
        }

        internal void StopRecording()
        {
            if (writer == null || stopping) return;
            try
            {
                var expected = (Dictionary<string, object>)metadata["runtime"];
                if (SegmentWriter.HashFile(GameConfig.gameXMLOptionPath) != (string)expected["input_settings_sha256"] ||
                    Screen.width != (int)expected["screen_width"] || Screen.height != (int)expected["screen_height"])
                    failed = true;
            }
            catch (Exception ex) { failed = true; Logger.LogError(ex); }
            Emit("game_event", Json.Fields("name", "recording_stopped"));
            active = false; stopping = true; UnbindWorld();
        }

        internal void BindWorld()
        {
            UnbindWorld();
            history = GameMain.history;
            if (history != null) history.onTechUnlocked += Tech;
            PlanetFactory.onFactoryBuildEntity += Build;
            PlanetFactory.beforeFactoryDismantleObject += BeforeDismantle;
            PlanetFactory.onFactoryDismantleObject += Dismantle;
        }
        private void UnbindWorld()
        {
            if (history != null) history.onTechUnlocked -= Tech;
            history = null;
            PlanetFactory.onFactoryBuildEntity -= Build;
            PlanetFactory.beforeFactoryDismantleObject -= BeforeDismantle;
            PlanetFactory.onFactoryDismantleObject -= Dismantle;
            dismantles.Clear();
        }
        private void Tech(int id, int level, bool direct) { Emit("game_event", Json.Fields("name", "tech_unlocked", "tech_id", id, "level", level, "direct", direct)); }
        private void Build(PlanetFactory factory, int id, int prebuild) { Emit("game_event", Json.Fields("name", "factory_build", "factory_index", factory.index, "entity_id", id, "proto_id", factory.entityPool[id].protoId)); }
        private void BeforeDismantle(PlanetFactory factory, int id) { dismantles[factory.index + ":" + id] = id > 0 ? factory.entityPool[id].protoId : factory.prebuildPool[-id].protoId; }
        private void Dismantle(PlanetFactory factory, int id)
        {
            string key = factory.index + ":" + id;
            if (dismantles.TryGetValue(key, out int proto))
            {
                Emit("game_event", Json.Fields("name", "factory_dismantled", "factory_index", factory.index, "object_id", id, "proto_id", proto));
                dismantles.Remove(key);
            }
        }
        private void OnDestroy()
        {
            StopRecording();
            if (pending != 0) AsyncGPUReadback.WaitAllRequests();
            drained = true;
            harmony?.UnpatchSelf(); Current = null;
        }
    }

    [HarmonyPatch(typeof(VFInput), nameof(VFInput.OnUpdate))]
    internal static class InputPatch { private static void Postfix() { RecorderPlugin.Current?.RecordInput(); } }
    [HarmonyPatch(typeof(GameMain), nameof(GameMain.Begin))]
    internal static class BeginPatch { private static void Postfix() { RecorderPlugin.Current?.BindWorld(); } }
    [HarmonyPatch(typeof(GameMain), nameof(GameMain.End))]
    internal static class EndPatch { private static void Prefix() { RecorderPlugin.Current?.StopRecording(); } }
}
