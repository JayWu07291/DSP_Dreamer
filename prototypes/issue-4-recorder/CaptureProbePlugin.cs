using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using Unity.Collections;
using UnityEngine;
using UnityEngine.Rendering;

namespace DSPDreamer.CaptureProbe
{
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public sealed class CaptureProbePlugin : BaseUnityPlugin
    {
        public const string PluginGuid = "tw.jaywu.dspdreamer.capture-probe";
        public const string PluginName = "DSP Dreamer capture probe";
        public const string PluginVersion = "0.1.13";

        private const int SlotCount = 12;
        private const int SpaceCapsuleProtoId = 9999;
        private const int IronOreItemId = 1001;
        private const int CopperOreItemId = 1002;
        private const int IronIngotItemId = 1101;
        private const int MagnetItemId = 1102;
        private const int CopperIngotItemId = 1104;
        private const int MagneticCoilItemId = 1202;
        private const int CircuitBoardItemId = 1301;
        private const int ElectromagneticMatrixItemId = 6001;
        private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
        private static readonly string[] RequiredTaskEventKinds =
        {
            "landing_capsule_dismantled",
            "tech_enqueued",
            "craft_enqueued",
            "craft_completed",
            "tech_unlocked",
            "manual_mining_yield",
            "factory_build",
            "factory_dismantled",
            "item_acquired",
            "panel_opened",
            "panel_closed"
        };
        private static readonly HashSet<string> TrackedPanelTypeNames = new HashSet<string>(StringComparer.Ordinal)
        {
            "UIInventoryWindow",
            "UIMechaWindow",
            "UIReplicatorWindow",
            "UITechTree",
        };
        private static readonly FieldInfo CursorTexturesField = AccessTools.Field(typeof(UICursor), "cursorTexs");
        private static readonly FieldInfo CursorHotspotsField = AccessTools.Field(typeof(UICursor), "cursorHots");
        private static readonly CursorGlyph FallbackCursorGlyph = CreateFallbackCursorGlyph();
        internal static CaptureProbePlugin Current;

        private readonly object eventLock = new object();
        private readonly Stopwatch clock = new Stopwatch();
        private readonly Dictionary<KeyCode, bool> keyState = new Dictionary<KeyCode, bool>();
        private readonly Queue<PendingAction> pendingActions = new Queue<PendingAction>();
        private readonly List<PendingAcquisition> pendingAcquisitions = new List<PendingAcquisition>();
        private readonly HashSet<string> semanticAcquisitionKeys = new HashSet<string>(StringComparer.Ordinal);
        private readonly HashSet<string> taskEventKinds = new HashSet<string>(StringComparer.Ordinal);
        private readonly Dictionary<int, Dictionary<string, object>> openPanelFields = new Dictionary<int, Dictionary<string, object>>();
        private readonly Dictionary<int, CursorGlyph> cursorGlyphCache = new Dictionary<int, CursorGlyph>();
        private readonly HashSet<int> unreadableCursorTextureIds = new HashSet<int>();
        private ConfigEntry<int> captureHz;
        private ConfigEntry<int> captureWidth;
        private ConfigEntry<int> captureHeight;
        private ConfigEntry<int> durationSeconds;
        private ConfigEntry<string> outputRoot;
        private Harmony harmony;
        private CaptureSlot[] slots;
        private BlockingCollection<FramePacket> writeQueue;
        private Thread writerThread;
        private StreamWriter eventWriter;
        private FileStream frameWriter;
        private Player boundPlayer;
        private string runDirectory;
        private bool recording;
        private bool stopping;
        private bool writerFinished;
        private long nextCaptureTicks;
        private long capturePeriodTicks;
        private long stopAtTicks;
        private long nextCaptureId;
        private long expectedFrames;
        private long requestedFrames;
        private long writtenFrames;
        private long schedulerDrops;
        private long inFlightDrops;
        private long readbackErrors;
        private long writerDrops;
        private long writerBytes;
        private long maxWriterQueue;
        private long sessionStartedTicks;
        private long injectedActions;
        private long observedActions;
        private long actionLatencyTicksTotal;
        private long actionLatencyTicksMax;
        private long taskEventCount;
        private long suppressedAcquisitionDuplicates;
        private long cursorVisibleFrames;
        private long cursorCompositedFrames;
        private long cursorFallbackFrames;
        private int pendingDismantleObjectId;
        private int pendingDismantleProtoId;
        private string pendingDismantleProtoName;
        private long lastObservedActionId;
        private int lastObservedActionFrame = -1;
        private long inputSamples;
        private int sourceWidth;
        private int sourceHeight;
        private string sourceDisplayMode;
        private int electromagnetismTechId;
        private int automaticMetallurgyTechId;
        private int basicLogisticsTechId;
        private int basicManufacturingTechId;
        private int electromagneticMatrixTechId;
        private int outstandingReadbacks;
        private long releaseWAtTicks;
        private bool injectedWHeld;
        private string lastBuildMode;
        private string lastMessage = "Ctrl+F8 開始 10 Hz 擷取";
        private GUIStyle overlayStyle;

        internal bool IsRecording { get { return recording; } }

        private void Awake()
        {
            Current = this;
            captureHz = Config.Bind("Probe", "CaptureHz", 10, "Capture requests per second.");
            captureWidth = Config.Bind("Probe", "Width", 640, "RGB frame width.");
            captureHeight = Config.Bind("Probe", "Height", 360, "RGB frame height.");
            durationSeconds = Config.Bind("Probe", "DurationSeconds", 600, "Automatic stop time.");
            outputRoot = Config.Bind("Probe", "OutputRoot", Path.Combine(Paths.PluginPath, "DSPDreamerCaptureProbe", "runs"), "Probe output directory.");
            harmony = new Harmony(PluginGuid);
            harmony.PatchAll(typeof(CaptureProbePlugin).Assembly);
            StartCoroutine(CaptureLoop());
            Logger.LogInfo("Capture probe loaded. Ctrl+F8 starts/stops; Ctrl+F9 injects a W pulse and mouse move; Ctrl+Shift+F11 aborts.");
        }

        private void Update()
        {
            if (recording)
            {
                FlushPendingAcquisitions(SafeGameTick());
                RecordBuildModeTransition();
            }

            bool control = Input.GetKey(KeyCode.LeftControl) || Input.GetKey(KeyCode.RightControl);
            bool shift = Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift);
            if (control && shift && Input.GetKeyDown(KeyCode.F11))
            {
                Abort("Ctrl+Shift+F11 emergency abort");
            }

            if (control && Input.GetKeyDown(KeyCode.F8))
            {
                if (recording || stopping) StopProbe("manual stop"); else StartProbe();
            }

            if (control && Input.GetKeyDown(KeyCode.F9))
            {
                InjectSelfTest();
            }

            if (injectedWHeld && clock.IsRunning && clock.ElapsedTicks >= releaseWAtTicks)
            {
                ReleaseInjectedW("scheduled release");
            }

            if (recording && clock.ElapsedTicks >= stopAtTicks)
            {
                StopProbe("duration reached");
            }

            if (stopping && Volatile.Read(ref outstandingReadbacks) == 0 && writeQueue != null && !writeQueue.IsAddingCompleted)
            {
                writeQueue.CompleteAdding();
            }

            if (stopping && writerFinished)
            {
                FinishProbe();
            }
        }

        private IEnumerator CaptureLoop()
        {
            WaitForEndOfFrame endOfFrame = new WaitForEndOfFrame();
            while (true)
            {
                yield return endOfFrame;
                if (!recording) continue;

                long now = clock.ElapsedTicks;
                if (now < nextCaptureTicks) continue;

                long due = 1L + (now - nextCaptureTicks) / capturePeriodTicks;
                expectedFrames += due;
                if (due > 1) schedulerDrops += due - 1;
                nextCaptureTicks += due * capturePeriodTicks;
                RequestFrame(now);
            }
        }

        private void StartProbe()
        {
            if (captureHz.Value <= 0 || captureWidth.Value <= 0 || captureHeight.Value <= 0 || durationSeconds.Value <= 0)
            {
                lastMessage = "設定錯誤：Hz、尺寸與時間必須大於零";
                return;
            }

            sourceWidth = Screen.width;
            sourceHeight = Screen.height;
            sourceDisplayMode = Screen.fullScreenMode.ToString();
            if ((long)sourceWidth * captureHeight.Value != (long)sourceHeight * captureWidth.Value)
            {
                lastMessage = "拒絕擷取：來源與輸出長寬比不同。請使用 1280×720";
                return;
            }

            ResetCounters();
            Directory.CreateDirectory(outputRoot.Value);
            runDirectory = Path.Combine(outputRoot.Value, DateTime.UtcNow.ToString("yyyyMMddTHHmmssZ", Invariant));
            Directory.CreateDirectory(runDirectory);
            eventWriter = new StreamWriter(new FileStream(Path.Combine(runDirectory, "events.ndjson"), FileMode.CreateNew, FileAccess.Write, FileShare.Read), new UTF8Encoding(false));
            frameWriter = new FileStream(Path.Combine(runDirectory, "frames.rgba"), FileMode.CreateNew, FileAccess.Write, FileShare.Read, 1024 * 1024, FileOptions.SequentialScan);
            writeQueue = new BlockingCollection<FramePacket>(SlotCount);
            slots = new CaptureSlot[SlotCount];
            int byteCount = checked(captureWidth.Value * captureHeight.Value * 4);
            for (int i = 0; i < slots.Length; i++)
            {
                slots[i] = new CaptureSlot
                {
                    Index = i,
                    Buffer = new byte[byteCount],
                    SourceTarget = new RenderTexture(sourceWidth, sourceHeight, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB),
                    Target = new RenderTexture(captureWidth.Value, captureHeight.Value, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB)
                };
                slots[i].SourceTarget.filterMode = FilterMode.Bilinear;
                slots[i].SourceTarget.Create();
                slots[i].Target.Create();
            }

            writerFinished = false;
            writerThread = new Thread(WriterLoop) { IsBackground = true, Name = "DSPDreamer capture writer" };
            writerThread.Start();
            clock.Restart();
            sessionStartedTicks = clock.ElapsedTicks;
            capturePeriodTicks = Math.Max(1L, Stopwatch.Frequency / captureHz.Value);
            nextCaptureTicks = sessionStartedTicks;
            stopAtTicks = sessionStartedTicks + durationSeconds.Value * Stopwatch.Frequency;
            BindTaskEvents();
            WriteEvent("session_start", Fields(
                "capture_hz", captureHz.Value,
                "width", captureWidth.Value,
                "height", captureHeight.Value,
                "duration_seconds", durationSeconds.Value,
                "source_width", sourceWidth,
                "source_height", sourceHeight,
                "source_display_mode", sourceDisplayMode,
                "capture_strategy", "full_frame_then_bilinear_gpu_scale_then_cursor_composite",
                "unity_frame", Time.frameCount,
                "game_tick", SafeGameTick()));
            recording = true;
            RecordPanelSnapshot();
            RecordBuildModeSnapshot();
            ResolveMicrotaskCatalog();
            RecordMicrotaskStateSnapshot("session_start");
            lastMessage = "擷取中：" + runDirectory;
        }

        private void RequestFrame(long requestedTicks)
        {
            CaptureSlot slot = null;
            for (int i = 0; i < slots.Length; i++)
            {
                if (Interlocked.CompareExchange(ref slots[i].Busy, 1, 0) == 0)
                {
                    slot = slots[i];
                    break;
                }
            }

            if (slot == null)
            {
                inFlightDrops++;
                WriteEvent("capture_drop", Fields("reason", "no_free_slot", "unity_frame", Time.frameCount, "game_tick", SafeGameTick()));
                return;
            }

            long captureId = ++nextCaptureId;
            int unityFrame = Time.frameCount;
            long gameTick = SafeGameTick();
            long actionId = lastObservedActionFrame == unityFrame
                ? lastObservedActionId
                : pendingActions.Count == 0 ? 0 : pendingActions.Peek().Id;
            CursorSnapshot cursor = CaptureCursorSnapshot();
            requestedFrames++;
            Interlocked.Increment(ref outstandingReadbacks);
            WriteEvent("capture_requested", Fields(
                "capture_id", captureId,
                "slot", slot.Index,
                "requested_ticks", requestedTicks,
                "unity_frame", unityFrame,
                "game_tick", gameTick,
                "pending_action_id", actionId,
                "cursor_visible", cursor.Visible,
                "cursor_x", cursor.HotspotX,
                "cursor_y", cursor.HotspotY,
                "cursor_index", cursor.Index,
                "cursor_glyph_source", cursor.GlyphSource));

            try
            {
                ScreenCapture.CaptureScreenshotIntoRenderTexture(slot.SourceTarget);
                Graphics.Blit(slot.SourceTarget, slot.Target);
                AsyncGPUReadback.Request(slot.Target, 0, TextureFormat.RGBA32, request => CompleteReadback(request, slot, captureId, requestedTicks, unityFrame, gameTick, actionId, cursor));
            }
            catch (Exception exception)
            {
                readbackErrors++;
                Interlocked.Exchange(ref slot.Busy, 0);
                Interlocked.Decrement(ref outstandingReadbacks);
                WriteEvent("capture_drop", Fields("reason", "request_exception", "capture_id", captureId, "error", exception.Message));
            }
        }

        private CursorSnapshot CaptureCursorSnapshot()
        {
            bool visible;
            try { visible = Cursor.visible && Application.isFocused; }
            catch { visible = false; }
            if (!visible) return CursorSnapshot.Hidden;

            Vector3 mouse = Input.mousePosition;
            float scaleX = captureWidth.Value / (float)sourceWidth;
            float scaleY = captureHeight.Value / (float)sourceHeight;
            int hotspotX = (int)Math.Round(mouse.x * scaleX);
            int hotspotY = (int)Math.Round((sourceHeight - mouse.y) * scaleY);
            int cursorIndex = -1;
            CursorGlyph glyph;
            Vector2 hotspot;
            string glyphSource;
            try { cursorIndex = UICursor.cursorIndexApply; }
            catch { cursorIndex = -1; }

            if (TryGetDspCursorGlyph(cursorIndex, out glyph, out hotspot))
            {
                glyphSource = "dsp_texture";
                int left = (int)Math.Round((mouse.x - hotspot.x) * scaleX);
                int top = (int)Math.Round((sourceHeight - mouse.y - hotspot.y) * scaleY);
                int drawWidth = Math.Max(1, (int)Math.Round(glyph.Width * scaleX));
                int drawHeight = Math.Max(1, (int)Math.Round(glyph.Height * scaleY));
                return new CursorSnapshot(true, hotspotX, hotspotY, cursorIndex, glyphSource, glyph, left, top, drawWidth, drawHeight);
            }

            glyphSource = "fallback";
            return new CursorSnapshot(true, hotspotX, hotspotY, cursorIndex, glyphSource, FallbackCursorGlyph, hotspotX, hotspotY, FallbackCursorGlyph.Width, FallbackCursorGlyph.Height);
        }

        private bool TryGetDspCursorGlyph(int cursorIndex, out CursorGlyph glyph, out Vector2 hotspot)
        {
            glyph = null;
            hotspot = Vector2.zero;
            if (cursorIndex < 0 || CursorTexturesField == null || CursorHotspotsField == null) return false;
            int textureId = 0;
            try
            {
                Texture2D[] textures = CursorTexturesField.GetValue(null) as Texture2D[];
                Vector2[] hotspots = CursorHotspotsField.GetValue(null) as Vector2[];
                if (textures == null || hotspots == null || cursorIndex >= textures.Length || cursorIndex >= hotspots.Length) return false;
                Texture2D texture = textures[cursorIndex];
                if (texture == null) return false;
                hotspot = hotspots[cursorIndex];
                textureId = texture.GetInstanceID();
                if (unreadableCursorTextureIds.Contains(textureId)) return false;
                if (cursorGlyphCache.TryGetValue(textureId, out glyph)) return true;

                Color32[] colors = texture.GetPixels32();
                byte[] rgbaTopDown = new byte[checked(texture.width * texture.height * 4)];
                for (int topY = 0; topY < texture.height; topY++)
                {
                    int sourceY = texture.height - 1 - topY;
                    for (int x = 0; x < texture.width; x++)
                    {
                        Color32 color = colors[sourceY * texture.width + x];
                        int offset = 4 * (topY * texture.width + x);
                        rgbaTopDown[offset] = color.r;
                        rgbaTopDown[offset + 1] = color.g;
                        rgbaTopDown[offset + 2] = color.b;
                        rgbaTopDown[offset + 3] = color.a;
                    }
                }
                glyph = new CursorGlyph(texture.width, texture.height, rgbaTopDown);
                cursorGlyphCache[textureId] = glyph;
                return true;
            }
            catch (Exception exception)
            {
                if (textureId != 0 && !unreadableCursorTextureIds.Add(textureId)) return false;
                Logger.LogWarning("Could not read DSP cursor texture; using fallback cursor. " + exception.Message);
                return false;
            }
        }

        private static CursorGlyph CreateFallbackCursorGlyph()
        {
            string[] mask =
            {
                "B...........",
                "BB..........",
                "BWB.........",
                "BWWB........",
                "BWWWB.......",
                "BWWWWB......",
                "BWWWWWB.....",
                "BWWWWWWB....",
                "BWWWWWWWB...",
                "BWWWWBBBB...",
                "BWWBWB......",
                "BWB.BWB.....",
                "BB..BWB.....",
                "B....BWB....",
                ".....BWB....",
                "......BB...."
            };
            int width = mask[0].Length;
            byte[] rgba = new byte[width * mask.Length * 4];
            for (int y = 0; y < mask.Length; y++)
            {
                for (int x = 0; x < width; x++)
                {
                    char pixel = mask[y][x];
                    if (pixel == '.') continue;
                    int offset = 4 * (y * width + x);
                    byte value = pixel == 'W' ? (byte)255 : (byte)0;
                    rgba[offset] = rgba[offset + 1] = rgba[offset + 2] = value;
                    rgba[offset + 3] = 255;
                }
            }
            return new CursorGlyph(width, mask.Length, rgba);
        }

        private void CompleteReadback(AsyncGPUReadbackRequest request, CaptureSlot slot, long captureId, long requestedTicks, int unityFrame, long gameTick, long actionId, CursorSnapshot cursor)
        {
            try
            {
                if (request.hasError)
                {
                    readbackErrors++;
                    Interlocked.Exchange(ref slot.Busy, 0);
                    WriteEvent("capture_drop", Fields("reason", "gpu_readback_error", "capture_id", captureId));
                    return;
                }

                NativeArray<byte> data = request.GetData<byte>();
                if (data.Length != slot.Buffer.Length)
                {
                    readbackErrors++;
                    Interlocked.Exchange(ref slot.Busy, 0);
                    WriteEvent("capture_drop", Fields("reason", "byte_count_mismatch", "capture_id", captureId, "actual_bytes", data.Length, "expected_bytes", slot.Buffer.Length));
                    return;
                }

                data.CopyTo(slot.Buffer);
                cursor.CompositedPixels = cursor.Visible
                    ? CursorCompositor.Composite(slot.Buffer, captureWidth.Value, captureHeight.Value, cursor.Glyph, cursor.Left, cursor.Top, cursor.DrawWidth, cursor.DrawHeight)
                    : 0;
                FramePacket packet = new FramePacket(slot, captureId, requestedTicks, clock.ElapsedTicks, unityFrame, gameTick, actionId, cursor);
                if (!writeQueue.TryAdd(packet))
                {
                    writerDrops++;
                    Interlocked.Exchange(ref slot.Busy, 0);
                    WriteEvent("capture_drop", Fields("reason", "writer_backpressure", "capture_id", captureId));
                }
                else
                {
                    long queueCount = writeQueue.Count;
                    if (queueCount > maxWriterQueue) maxWriterQueue = queueCount;
                }
            }
            catch (Exception exception)
            {
                readbackErrors++;
                Interlocked.Exchange(ref slot.Busy, 0);
                WriteEvent("capture_drop", Fields("reason", "callback_exception", "capture_id", captureId, "error", exception.Message));
            }
            finally
            {
                Interlocked.Decrement(ref outstandingReadbacks);
            }
        }

        private void WriterLoop()
        {
            try
            {
                foreach (FramePacket packet in writeQueue.GetConsumingEnumerable())
                {
                    long offset = frameWriter.Position;
                    frameWriter.Write(packet.Slot.Buffer, 0, packet.Slot.Buffer.Length);
                    writerBytes += packet.Slot.Buffer.Length;
                    writtenFrames++;
                    if (packet.Cursor.Visible) cursorVisibleFrames++;
                    if (packet.Cursor.CompositedPixels > 0) cursorCompositedFrames++;
                    if (packet.Cursor.CompositedPixels > 0 && packet.Cursor.GlyphSource == "fallback") cursorFallbackFrames++;
                    WriteEvent("capture_written", Fields(
                        "capture_id", packet.CaptureId,
                        "file_offset", offset,
                        "byte_count", packet.Slot.Buffer.Length,
                        "requested_ticks", packet.RequestedTicks,
                        "completed_ticks", packet.CompletedTicks,
                        "unity_frame", packet.UnityFrame,
                        "game_tick", packet.GameTick,
                        "pending_action_id", packet.ActionId,
                        "cursor_visible", packet.Cursor.Visible,
                        "cursor_composited", packet.Cursor.CompositedPixels > 0,
                        "cursor_composited_pixels", packet.Cursor.CompositedPixels,
                        "cursor_x", packet.Cursor.HotspotX,
                        "cursor_y", packet.Cursor.HotspotY,
                        "cursor_index", packet.Cursor.Index,
                        "cursor_glyph_source", packet.Cursor.GlyphSource));
                    Interlocked.Exchange(ref packet.Slot.Busy, 0);
                }
                frameWriter.Flush(true);
            }
            catch (Exception exception)
            {
                WriteEvent("writer_error", Fields("error", exception.ToString()));
            }
            finally
            {
                writerFinished = true;
            }
        }

        internal void RecordInputSample()
        {
            if (!recording) return;
            inputSamples++;
            List<string> down = new List<string>();
            List<string> up = new List<string>();
            foreach (KeyCode key in DesktopKeys)
            {
                bool held;
                try { held = Input.GetKey(key); }
                catch { continue; }
                bool previous;
                keyState.TryGetValue(key, out previous);
                if (held && !previous) down.Add(key.ToString());
                if (!held && previous) up.Add(key.ToString());
                keyState[key] = held;
            }

            Vector3 mouse = Input.mousePosition;
            bool observedPending = false;
            if (pendingActions.Count > 0)
            {
                PendingAction action = pendingActions.Peek();
                if (Input.GetKey(KeyCode.W) || Math.Abs(VFInput.mouseMoveAxis.x) > 0.001f || Math.Abs(VFInput.mouseMoveAxis.y) > 0.001f)
                {
                    pendingActions.Dequeue();
                    observedPending = true;
                    observedActions++;
                    lastObservedActionId = action.Id;
                    lastObservedActionFrame = Time.frameCount;
                    long latency = clock.ElapsedTicks - action.RequestedTicks;
                    actionLatencyTicksTotal += latency;
                    if (latency > actionLatencyTicksMax) actionLatencyTicksMax = latency;
                    WriteEvent("action_observed", Fields("action_id", action.Id, "requested_ticks", action.RequestedTicks, "observed_ticks", clock.ElapsedTicks, "latency_ms", TicksToMilliseconds(latency), "unity_frame", Time.frameCount, "game_tick", SafeGameTick()));
                }
            }

            WriteEvent("input_sample", Fields(
                "ticks", clock.ElapsedTicks,
                "unity_frame", Time.frameCount,
                "game_tick", SafeGameTick(),
                "down", string.Join(",", down.ToArray()),
                "up", string.Join(",", up.ToArray()),
                "mouse_x", mouse.x,
                "mouse_y", mouse.y,
                "mouse_dx", VFInput.mouseMoveAxis.x,
                "mouse_dy", VFInput.mouseMoveAxis.y,
                "wheel", VFInput.mouseWheel,
                "mouse0", Input.GetMouseButton(0),
                "mouse1", Input.GetMouseButton(1),
                "mouse2", Input.GetMouseButton(2),
                "focused", Application.isFocused,
                "paused", GameMain.isPaused,
                "inputing", VFInput.inputing,
                "in_screen", VFInput.inScreen,
                "fullscreen_ui", VFInput.inFullscreenGUI,
                "observed_pending_action", observedPending));
        }

        private void InjectSelfTest()
        {
            if (!recording)
            {
                lastMessage = "先用 Ctrl+F8 開始擷取";
                return;
            }
            if (!Application.isFocused)
            {
                lastMessage = "拒絕注入：DSP 沒有焦點";
                return;
            }

            long actionId = ++injectedActions;
            long requestedTicks = clock.ElapsedTicks;
            INPUT[] inputs = { KeyboardInput(0x11, false), MouseMoveInput(16, 0) };
            uint sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT)));
            pendingActions.Enqueue(new PendingAction(actionId, requestedTicks));
            if (sent == inputs.Length)
            {
                injectedWHeld = true;
                releaseWAtTicks = requestedTicks + Stopwatch.Frequency / 10;
            }
            WriteEvent("action_requested", Fields("action_id", actionId, "requested_ticks", requestedTicks, "requested_events", inputs.Length, "sent_events", sent, "unity_frame", Time.frameCount, "game_tick", SafeGameTick()));
            lastMessage = sent == inputs.Length ? "已注入 W 100 ms 與滑鼠 +16 px" : "SendInput 未送出完整事件";
        }

        private void StopProbe(string reason)
        {
            if (!recording) return;
            FlushPendingAcquisitions(long.MaxValue);
            RecordMicrotaskStateSnapshot("session_stop");
            recording = false;
            stopping = true;
            ReleaseInjectedW(reason);
            UnbindTaskEvents();
            WriteEvent("session_stop", Fields("reason", reason, "elapsed_seconds", TicksToSeconds(clock.ElapsedTicks - sessionStartedTicks), "outstanding_readbacks", outstandingReadbacks));
            lastMessage = "正在排空寫入佇列";
        }

        private void FinishProbe()
        {
            stopping = false;
            double elapsed = TicksToSeconds(clock.ElapsedTicks - sessionStartedTicks);
            long totalDrops = schedulerDrops + inFlightDrops + readbackErrors + writerDrops;
            double dropRate = expectedFrames == 0 ? 1.0 : (double)totalDrops / expectedFrames;
            double effectiveHz = elapsed <= 0 ? 0 : writtenFrames / elapsed;
            double measuredRenderedFps = elapsed <= 0 ? 0 : inputSamples / elapsed;
            double averageActionLatencyMs = observedActions == 0 ? 0 : TicksToMilliseconds(actionLatencyTicksTotal / observedActions);
            string[] missingTaskEventKinds = GetMissingTaskEventKinds();
            bool metricsPassed = elapsed >= Math.Min(durationSeconds.Value, 60)
                && dropRate < 0.01
                && effectiveHz >= captureHz.Value * 0.95
                && readbackErrors == 0
                && writerDrops == 0
                && missingTaskEventKinds.Length == 0
                && injectedActions >= 3
                && observedActions == injectedActions
                && TicksToMilliseconds(actionLatencyTicksMax) <= 100.0;
            string metricsVerdict = metricsPassed ? "pass" : "inconclusive_or_fail";
            string verdict = metricsPassed ? "metrics_pass_visual_pending" : "inconclusive_or_fail";

            string summary = JsonObject(Fields(
                "verdict", verdict,
                "metrics_verdict", metricsVerdict,
                "elapsed_seconds", elapsed,
                "configured_hz", captureHz.Value,
                "width", captureWidth.Value,
                "height", captureHeight.Value,
                "source_width", sourceWidth,
                "source_height", sourceHeight,
                "source_display_mode", sourceDisplayMode,
                "capture_strategy", "full_frame_then_bilinear_gpu_scale_then_cursor_composite",
                "measured_rendered_fps", measuredRenderedFps,
                "effective_hz", effectiveHz,
                "expected_frames", expectedFrames,
                "requested_frames", requestedFrames,
                "written_frames", writtenFrames,
                "scheduler_drops", schedulerDrops,
                "in_flight_drops", inFlightDrops,
                "readback_errors", readbackErrors,
                "writer_drops", writerDrops,
                "drop_rate", dropRate,
                "writer_bytes", writerBytes,
                "max_writer_queue", maxWriterQueue,
                "task_events", taskEventCount,
                "task_event_kinds", string.Join(",", SortedTaskEventKinds()),
                "missing_task_event_kinds", string.Join(",", missingTaskEventKinds),
                "suppressed_item_acquisition_duplicates", suppressedAcquisitionDuplicates,
                "cursor_visible_frames", cursorVisibleFrames,
                "cursor_composited_frames", cursorCompositedFrames,
                "cursor_fallback_frames", cursorFallbackFrames,
                "cursor_composite_verdict", cursorCompositedFrames > 0 ? "pass" : "not_observed",
                "injected_actions", injectedActions,
                "observed_actions", observedActions,
                "average_action_latency_ms", averageActionLatencyMs,
                "max_action_latency_ms", TicksToMilliseconds(actionLatencyTicksMax)));
            WriteEvent("session_summary", Fields("verdict", verdict, "metrics_verdict", metricsVerdict, "drop_rate", dropRate, "effective_hz", effectiveHz));
            File.WriteAllText(Path.Combine(runDirectory, "summary.json"), summary + Environment.NewLine, new UTF8Encoding(false));
            eventWriter.Dispose();
            frameWriter.Dispose();
            for (int i = 0; i < slots.Length; i++)
            {
                slots[i].SourceTarget.Release();
                Destroy(slots[i].SourceTarget);
                slots[i].Target.Release();
                Destroy(slots[i].Target);
            }
            lastMessage = "完成：" + verdict + "，掉幀率 " + (dropRate * 100.0).ToString("F2", Invariant) + "%";
            Logger.LogInfo(lastMessage + ". Output: " + runDirectory);
        }

        private void Abort(string reason)
        {
            ReleaseInjectedW(reason);
            if (recording) StopProbe(reason);
            lastMessage = reason;
        }

        private void ReleaseInjectedW(string reason)
        {
            if (!injectedWHeld) return;
            INPUT[] inputs = { KeyboardInput(0x11, true) };
            uint sent = SendInput(1, inputs, Marshal.SizeOf(typeof(INPUT)));
            injectedWHeld = false;
            if (eventWriter != null) WriteEvent("action_release", Fields("reason", reason, "sent_events", sent, "ticks", clock.IsRunning ? clock.ElapsedTicks : 0));
        }

        private void BindTaskEvents()
        {
            UnbindTaskEvents();
            if (GameMain.history != null) GameMain.history.onTechUnlocked += OnTechUnlocked;
            boundPlayer = GameMain.mainPlayer;
            if (boundPlayer != null) boundPlayer.onPackageAddItem += OnPackageAddItem;
            PlanetFactory.onFactoryBuildEntity += OnFactoryBuild;
            PlanetFactory.beforeFactoryDismantleObject += OnBeforeDismantle;
            PlanetFactory.onFactoryDismantleObject += OnAfterDismantle;
        }

        private void UnbindTaskEvents()
        {
            if (GameMain.history != null) GameMain.history.onTechUnlocked -= OnTechUnlocked;
            if (boundPlayer != null) boundPlayer.onPackageAddItem -= OnPackageAddItem;
            boundPlayer = null;
            PlanetFactory.onFactoryBuildEntity -= OnFactoryBuild;
            PlanetFactory.beforeFactoryDismantleObject -= OnBeforeDismantle;
            PlanetFactory.onFactoryDismantleObject -= OnAfterDismantle;
        }

        private void OnTechUnlocked(int techId, int level, bool direct)
        {
            WriteTaskEvent("tech_unlocked", Fields("tech_id", techId, "tech_name", TechName(techId), "level", level, "direct", direct));
        }

        private void OnPackageAddItem(int itemId, int count, int inc)
        {
            if (!recording || count <= 0) return;
            long gameTick = SafeGameTick();
            string key = AcquisitionKey(gameTick, itemId, count);
            if (semanticAcquisitionKeys.Contains(key))
            {
                suppressedAcquisitionDuplicates++;
                return;
            }
            pendingAcquisitions.Add(new PendingAcquisition(itemId, count, inc, gameTick, Time.frameCount, clock.ElapsedTicks));
        }

        private void OnFactoryBuild(PlanetFactory factory, int entityId, int prebuildId)
        {
            int protoId = entityId > 0 && entityId < factory.entityPool.Length ? factory.entityPool[entityId].protoId : 0;
            WriteTaskEvent("factory_build", Fields("entity_id", entityId, "prebuild_id", prebuildId, "proto_id", protoId, "proto_name", ItemName(protoId)));
        }

        private void OnBeforeDismantle(PlanetFactory factory, int objectId)
        {
            pendingDismantleObjectId = objectId;
            pendingDismantleProtoId = FactoryObjectProtoId(factory, objectId);
            pendingDismantleProtoName = ItemName(pendingDismantleProtoId);
        }

        private void OnAfterDismantle(PlanetFactory factory, int objectId)
        {
            if (objectId == pendingDismantleObjectId)
            {
                WriteTaskEvent("factory_dismantled", Fields(
                    "factory_index", factory == null ? -1 : factory.index,
                    "object_id", objectId,
                    "entity_id", objectId > 0 ? objectId : 0,
                    "prebuild_id", objectId < 0 ? -objectId : 0,
                    "proto_id", pendingDismantleProtoId,
                    "proto_name", pendingDismantleProtoName));
            }
            pendingDismantleObjectId = pendingDismantleProtoId = 0;
            pendingDismantleProtoName = string.Empty;
        }

        internal void RecordTechEnqueued(int techId, int queuedCount)
        {
            WriteTaskEvent("tech_enqueued", Fields("tech_id", techId, "tech_name", TechName(techId), "queued_count", queuedCount));
        }

        internal void RecordCraftEnqueued(int recipeId, int count, ForgeTask task)
        {
            WriteTaskEvent("craft_enqueued", Fields(
                "recipe_id", recipeId,
                "recipe_name", RecipeName(recipeId),
                "count", count,
                "product_ids", JoinInts(task == null ? null : task.productIds),
                "product_names", JoinItemNames(task == null ? null : task.productIds),
                "product_counts", JoinInts(task == null ? null : task.productCounts)));
        }

        internal void RecordCraftCompleted(ForgeTask task)
        {
            if (!recording || task == null) return;
            for (int i = 0; i < task.productIds.Length && i < task.productCounts.Length; i++)
            {
                MarkSemanticAcquisition(task.productIds[i], task.productCounts[i]);
            }
            WriteTaskEvent("craft_completed", Fields(
                "recipe_id", task.recipeId,
                "recipe_name", RecipeName(task.recipeId),
                "product_ids", JoinInts(task.productIds),
                "product_names", JoinItemNames(task.productIds),
                "product_counts", JoinInts(task.productCounts)));
        }

        internal void RecordManualMiningYield(PlayerAction_Mine action, int itemId, int itemCount, PlanetFactory factory)
        {
            if (!recording) return;
            MarkSemanticAcquisition(itemId, itemCount);
            WriteTaskEvent("manual_mining_yield", Fields(
                "item_id", itemId,
                "item_name", ItemName(itemId),
                "item_count", itemCount,
                "mining_type", action == null ? "unknown" : action.miningType.ToString(),
                "mining_id", action == null ? 0 : action.miningId,
                "mining_proto_id", action == null ? 0 : action.miningProtoId,
                "mining_proto_name", MiningProtoName(action)));
        }

        internal void RecordMinerProduction(PlanetFactory factory, MinerComponent miner, float power, int itemId, int itemCount)
        {
            if (!recording || itemCount <= 0 || (itemId != IronOreItemId && itemId != CopperOreItemId)) return;
            int protoId = factory != null && miner.entityId > 0 && miner.entityId < factory.entityPool.Length
                ? factory.entityPool[miner.entityId].protoId
                : 0;
            WriteTaskEvent("miner_produced", Fields(
                "factory_index", factory == null ? -1 : factory.index,
                "entity_id", miner.entityId,
                "miner_id", miner.id,
                "proto_id", protoId,
                "proto_name", ItemName(protoId),
                "item_id", itemId,
                "item_name", ItemName(itemId),
                "item_count", itemCount,
                "power", power,
                "powered", power >= 0.1f,
                "vein_count", miner.veinCount));
        }

        internal void RecordMachineBatch(string machineKind, int entityId, int componentId, int recipeId, ERecipeType recipeType, RecipeExecuteData recipe, float power, int normalCycles, int extraCycles)
        {
            if (!recording || recipe == null || normalCycles <= 0 || !ContainsTrackedProduct(recipe.products)) return;
            PlanetFactory factory = GameMain.localPlanet == null ? null : GameMain.localPlanet.factory;
            int protoId = factory != null && entityId > 0 && entityId < factory.entityPool.Length
                ? factory.entityPool[entityId].protoId
                : 0;
            WriteTaskEvent("machine_batch_completed", Fields(
                "machine_kind", machineKind,
                "factory_index", factory == null ? -1 : factory.index,
                "entity_id", entityId,
                "component_id", componentId,
                "proto_id", protoId,
                "proto_name", ItemName(protoId),
                "recipe_id", recipeId,
                "recipe_name", RecipeName(recipeId),
                "recipe_type", recipeType.ToString(),
                "product_ids", JoinInts(recipe.products),
                "product_names", JoinItemNames(recipe.products),
                "product_counts", JoinInts(recipe.productCounts),
                "normal_cycles", normalCycles,
                "extra_cycles", extraCycles,
                "power", power,
                "powered", power >= 0.1f));
        }

        internal void RecordSorterDelivery(PlanetFactory factory, SorterDeliveryState state, int deliveredCount)
        {
            if (!recording || factory == null || state == null || deliveredCount <= 0) return;
            if (state.TargetEntityId <= 0 || state.TargetEntityId >= factory.entityPool.Length) return;
            EntityData target = factory.entityPool[state.TargetEntityId];
            string targetKind;
            int componentId;
            int recipeId;
            ERecipeType recipeType;
            RecipeExecuteData recipe;
            if (target.assemblerId > 0 && target.assemblerId < factory.factorySystem.assemblerPool.Length)
            {
                AssemblerComponent assembler = factory.factorySystem.assemblerPool[target.assemblerId];
                targetKind = "assembler";
                componentId = assembler.id;
                recipeId = assembler.recipeId;
                recipeType = assembler.recipeType;
                recipe = assembler.recipeExecuteData;
            }
            else if (target.labId > 0 && target.labId < factory.factorySystem.labPool.Length)
            {
                LabComponent lab = factory.factorySystem.labPool[target.labId];
                targetKind = "lab";
                componentId = lab.id;
                recipeId = lab.recipeId;
                recipeType = ERecipeType.Research;
                recipe = lab.recipeExecuteData;
                if (lab.researchMode) return;
            }
            else
            {
                return;
            }

            if (recipeId <= 0 || recipe == null || !ContainsTrackedProduct(recipe.products)) return;
            WriteTaskEvent("sorter_delivered", Fields(
                "factory_index", factory.index,
                "inserter_id", state.InserterId,
                "inserter_entity_id", state.InserterEntityId,
                "source_entity_id", state.SourceEntityId,
                "target_entity_id", state.TargetEntityId,
                "target_kind", targetKind,
                "target_component_id", componentId,
                "target_proto_id", target.protoId,
                "target_proto_name", ItemName(target.protoId),
                "target_recipe_id", recipeId,
                "target_recipe_name", RecipeName(recipeId),
                "target_recipe_type", recipeType.ToString(),
                "target_product_ids", JoinInts(recipe.products),
                "target_product_names", JoinItemNames(recipe.products),
                "item_id", state.ItemId,
                "item_name", ItemName(state.ItemId),
                "item_count", deliveredCount,
                "power", state.Power,
                "powered", state.Power >= 0.1f));
        }

        private static bool ContainsTrackedProduct(int[] products)
        {
            if (products == null) return false;
            for (int i = 0; i < products.Length; i++)
            {
                int itemId = products[i];
                if (itemId == IronIngotItemId || itemId == MagnetItemId || itemId == CopperIngotItemId
                    || itemId == MagneticCoilItemId || itemId == CircuitBoardItemId || itemId == ElectromagneticMatrixItemId)
                {
                    return true;
                }
            }
            return false;
        }

        private void ResolveMicrotaskCatalog()
        {
            electromagnetismTechId = FindTechByRewards(2301, 1, 2203, 1);
            automaticMetallurgyTechId = FindTechByRewards(2302, 3);
            basicLogisticsTechId = FindTechByRewards(2001, 20, 2011, 5);
            basicManufacturingTechId = FindTechByRewards(2303, 1);
            electromagneticMatrixTechId = FindTechByRewards(2901, 1);
            WriteEvent("microtask_catalog", Fields(
                "tech_electromagnetism_id", electromagnetismTechId,
                "tech_electromagnetism_name", TechName(electromagnetismTechId),
                "tech_automatic_metallurgy_id", automaticMetallurgyTechId,
                "tech_automatic_metallurgy_name", TechName(automaticMetallurgyTechId),
                "tech_basic_logistics_id", basicLogisticsTechId,
                "tech_basic_logistics_name", TechName(basicLogisticsTechId),
                "tech_basic_manufacturing_id", basicManufacturingTechId,
                "tech_basic_manufacturing_name", TechName(basicManufacturingTechId),
                "tech_electromagnetic_matrix_id", electromagneticMatrixTechId,
                "tech_electromagnetic_matrix_name", TechName(electromagneticMatrixTechId),
                "iron_ore_item_id", IronOreItemId,
                "iron_ore_item_name", ItemName(IronOreItemId),
                "copper_ore_item_id", CopperOreItemId,
                "copper_ore_item_name", ItemName(CopperOreItemId),
                "iron_ingot_item_id", IronIngotItemId,
                "iron_ingot_item_name", ItemName(IronIngotItemId),
                "magnet_item_id", MagnetItemId,
                "magnet_item_name", ItemName(MagnetItemId),
                "copper_ingot_item_id", CopperIngotItemId,
                "copper_ingot_item_name", ItemName(CopperIngotItemId),
                "magnetic_coil_item_id", MagneticCoilItemId,
                "magnetic_coil_item_name", ItemName(MagneticCoilItemId),
                "circuit_board_item_id", CircuitBoardItemId,
                "circuit_board_item_name", ItemName(CircuitBoardItemId),
                "electromagnetic_matrix_item_id", ElectromagneticMatrixItemId,
                "electromagnetic_matrix_item_name", ItemName(ElectromagneticMatrixItemId)));
        }

        private void RecordMicrotaskStateSnapshot(string reason)
        {
            WriteEvent("microtask_state_snapshot", Fields(
                "reason", reason,
                "capsule_count", CountLandingCapsules(),
                "tech_electromagnetism_unlocked", TechUnlocked(electromagnetismTechId),
                "tech_automatic_metallurgy_unlocked", TechUnlocked(automaticMetallurgyTechId),
                "tech_basic_logistics_unlocked", TechUnlocked(basicLogisticsTechId),
                "tech_basic_manufacturing_unlocked", TechUnlocked(basicManufacturingTechId),
                "tech_electromagnetic_matrix_unlocked", TechUnlocked(electromagneticMatrixTechId),
                "unity_frame", Time.frameCount,
                "game_tick", SafeGameTick(),
                "ticks", clock.IsRunning ? clock.ElapsedTicks : 0));
        }

        private static int FindTechByRewards(params int[] itemCountPairs)
        {
            if (itemCountPairs == null || itemCountPairs.Length == 0 || itemCountPairs.Length % 2 != 0 || LDB.techs == null) return 0;
            TechProto[] techs = LDB.techs.dataArray;
            if (techs == null) return 0;
            for (int i = 0; i < techs.Length; i++)
            {
                TechProto tech = techs[i];
                if (tech == null || tech.AddItems == null || tech.AddItemCounts == null) continue;
                bool matched = true;
                for (int pair = 0; pair < itemCountPairs.Length; pair += 2)
                {
                    int expectedItem = itemCountPairs[pair];
                    int expectedCount = itemCountPairs[pair + 1];
                    bool rewardFound = false;
                    for (int reward = 0; reward < tech.AddItems.Length && reward < tech.AddItemCounts.Length; reward++)
                    {
                        if (tech.AddItems[reward] == expectedItem && tech.AddItemCounts[reward] == expectedCount)
                        {
                            rewardFound = true;
                            break;
                        }
                    }
                    if (!rewardFound)
                    {
                        matched = false;
                        break;
                    }
                }
                if (matched) return tech.ID;
            }
            return 0;
        }

        private static bool TechUnlocked(int techId)
        {
            return techId > 0 && GameMain.history != null && GameMain.history.TechUnlocked(techId);
        }

        private static int CountLandingCapsules()
        {
            PlanetFactory factory = GameMain.localPlanet == null ? null : GameMain.localPlanet.factory;
            if (factory == null || factory.vegePool == null) return -1;
            int count = 0;
            int limit = Math.Min(factory.vegeCursor, factory.vegePool.Length);
            for (int i = 1; i < limit; i++)
            {
                if (factory.vegePool[i].id == i && factory.vegePool[i].protoId == SpaceCapsuleProtoId) count++;
            }
            return count;
        }

        internal void RecordLandingCapsuleDismantled(int vegeId)
        {
            WriteTaskEvent("landing_capsule_dismantled", Fields("vege_id", vegeId, "proto_id", SpaceCapsuleProtoId, "proto_name", VegeName(SpaceCapsuleProtoId)));
        }

        internal void RecordPanelOpened(ManualBehaviour panel)
        {
            Dictionary<string, object> fields;
            if (!TryGetPanelFields(panel, out fields)) return;
            openPanelFields[panel.GetInstanceID()] = fields;
            WriteTaskEvent("panel_opened", new Dictionary<string, object>(fields));
        }

        internal void RecordPanelClosed(ManualBehaviour panel)
        {
            if (panel == null) return;
            int instanceId = panel.GetInstanceID();
            Dictionary<string, object> fields;
            if (!openPanelFields.TryGetValue(instanceId, out fields) && !TryGetPanelFields(panel, out fields)) return;
            WriteTaskEvent("panel_closed", new Dictionary<string, object>(fields));
            openPanelFields.Remove(instanceId);
        }

        private void RecordPanelSnapshot()
        {
            ManualBehaviour[] behaviours = Resources.FindObjectsOfTypeAll<ManualBehaviour>();
            HashSet<string> openPanels = new HashSet<string>(StringComparer.Ordinal);
            for (int i = 0; i < behaviours.Length; i++)
            {
                ManualBehaviour behaviour = behaviours[i];
                Dictionary<string, object> fields;
                if (behaviour.active && TryGetPanelFields(behaviour, out fields))
                {
                    openPanels.Add(PanelKey(behaviour));
                    openPanelFields[behaviour.GetInstanceID()] = fields;
                }
            }
            string[] names = new string[openPanels.Count];
            openPanels.CopyTo(names);
            Array.Sort(names, StringComparer.Ordinal);
            WriteEvent("panel_state_snapshot", Fields(
                "open_panels", string.Join(",", names),
                "unity_frame", Time.frameCount,
                "game_tick", SafeGameTick(),
                "ticks", clock.ElapsedTicks));
        }

        private static bool TryGetPanelFields(ManualBehaviour panel, out Dictionary<string, object> fields)
        {
            fields = null;
            if (panel == null) return false;
            string panelType = panel.GetType().Name;
            if (TrackedPanelTypeNames.Contains(panelType))
            {
                fields = Fields("panel", panelType, "panel_instance_id", panel.GetInstanceID());
                return true;
            }

            UIMinerWindow minerWindow = panel as UIMinerWindow;
            if (minerWindow != null)
            {
                PlanetFactory factory = minerWindow.factory;
                int minerId = minerWindow.minerId;
                if (factory == null || factory.factorySystem == null || minerId <= 0 || minerId >= factory.factorySystem.minerPool.Length) return false;
                MinerComponent miner = factory.factorySystem.minerPool[minerId];
                if (miner.id != minerId || miner.entityId <= 0 || miner.entityId >= factory.entityPool.Length) return false;
                int protoId = factory.entityPool[miner.entityId].protoId;
                fields = Fields(
                    "panel", panelType,
                    "panel_instance_id", panel.GetInstanceID(),
                    "machine_kind", "miner",
                    "factory_index", factory.index,
                    "entity_id", miner.entityId,
                    "component_id", minerId,
                    "proto_id", protoId,
                    "proto_name", ItemName(protoId));
                return true;
            }

            UIAssemblerWindow assemblerWindow = panel as UIAssemblerWindow;
            if (assemblerWindow == null) return false;
            PlanetFactory assemblerFactory = assemblerWindow.factory;
            int assemblerId = assemblerWindow.assemblerId;
            if (assemblerFactory == null || assemblerFactory.factorySystem == null || assemblerId <= 0 || assemblerId >= assemblerFactory.factorySystem.assemblerPool.Length) return false;
            AssemblerComponent assembler = assemblerFactory.factorySystem.assemblerPool[assemblerId];
            if (assembler.id != assemblerId || assembler.entityId <= 0 || assembler.entityId >= assemblerFactory.entityPool.Length) return false;
            int assemblerProtoId = assemblerFactory.entityPool[assembler.entityId].protoId;
            ERecipeType recipeType = assembler.recipeType;
            ItemProto assemblerProto = LDB.items.Select(assemblerProtoId);
            if (recipeType == ERecipeType.None && assemblerProto != null && assemblerProto.prefabDesc != null)
            {
                recipeType = assemblerProto.prefabDesc.assemblerRecipeType;
            }
            string machineKind;
            if (recipeType == ERecipeType.Smelt) machineKind = "smelter";
            else if (recipeType == ERecipeType.Assemble) machineKind = "assembler";
            else return false;
            fields = Fields(
                "panel", panelType,
                "panel_instance_id", panel.GetInstanceID(),
                "machine_kind", machineKind,
                "factory_index", assemblerFactory.index,
                "entity_id", assembler.entityId,
                "component_id", assemblerId,
                "proto_id", assemblerProtoId,
                "proto_name", ItemName(assemblerProtoId),
                "recipe_id", assembler.recipeId,
                "recipe_name", RecipeName(assembler.recipeId),
                "recipe_type", recipeType.ToString());
            return true;
        }

        private static string PanelKey(ManualBehaviour panel)
        {
            return panel.GetType().Name + "#" + panel.GetInstanceID().ToString(Invariant);
        }

        private void WriteTaskEvent(string name, IDictionary<string, object> fields)
        {
            if (!recording) return;
            WriteTaskEventAt(name, fields, Time.frameCount, SafeGameTick(), clock.IsRunning ? clock.ElapsedTicks : 0);
        }

        private void WriteTaskEventAt(string name, IDictionary<string, object> fields, int unityFrame, long gameTick, long ticks)
        {
            taskEventCount++;
            taskEventKinds.Add(name);
            fields["name"] = name;
            fields["unity_frame"] = unityFrame;
            fields["game_tick"] = gameTick;
            fields["ticks"] = ticks;
            WriteEvent("task_event", fields);
        }

        private void MarkSemanticAcquisition(int itemId, int count)
        {
            long gameTick = SafeGameTick();
            string key = AcquisitionKey(gameTick, itemId, count);
            semanticAcquisitionKeys.Add(key);
            suppressedAcquisitionDuplicates += pendingAcquisitions.RemoveAll(pending => pending.GameTick == gameTick && pending.ItemId == itemId && pending.Count == count);
        }

        private void FlushPendingAcquisitions(long currentGameTick)
        {
            for (int i = 0; i < pendingAcquisitions.Count;)
            {
                PendingAcquisition pending = pendingAcquisitions[i];
                if (currentGameTick != long.MaxValue && pending.GameTick >= currentGameTick)
                {
                    i++;
                    continue;
                }
                pendingAcquisitions.RemoveAt(i);
                if (semanticAcquisitionKeys.Contains(AcquisitionKey(pending.GameTick, pending.ItemId, pending.Count))) continue;
                WriteTaskEventAt("item_acquired", Fields(
                    "item_id", pending.ItemId,
                    "item_name", ItemName(pending.ItemId),
                    "item_count", pending.Count,
                    "item_inc", pending.Inc,
                    "destination", "player_package"),
                    pending.UnityFrame,
                    pending.GameTick,
                    pending.Ticks);
            }
        }

        private static string AcquisitionKey(long gameTick, int itemId, int count)
        {
            return gameTick.ToString(Invariant) + "|" + itemId.ToString(Invariant) + "|" + count.ToString(Invariant);
        }

        internal void OnGameBegin()
        {
            if (!recording) return;
            cursorGlyphCache.Clear();
            unreadableCursorTextureIds.Clear();
            BindTaskEvents();
            WriteEvent("episode_begin", Fields("ticks", clock.ElapsedTicks, "unity_frame", Time.frameCount, "game_tick", SafeGameTick()));
            ResolveMicrotaskCatalog();
            RecordMicrotaskStateSnapshot("episode_begin");
        }

        private void RecordBuildModeSnapshot()
        {
            lastBuildMode = CurrentBuildMode();
            WriteEvent("build_mode_state_snapshot", Fields(
                "mode", lastBuildMode,
                "unity_frame", Time.frameCount,
                "game_tick", SafeGameTick(),
                "ticks", clock.IsRunning ? clock.ElapsedTicks : 0));
        }

        private void RecordBuildModeTransition()
        {
            string currentMode = CurrentBuildMode();
            if (lastBuildMode == null)
            {
                lastBuildMode = currentMode;
                return;
            }
            if (currentMode == lastBuildMode) return;
            WriteTaskEvent("build_mode_changed", Fields("previous_mode", lastBuildMode, "mode", currentMode));
            lastBuildMode = currentMode;
        }

        private static string CurrentBuildMode()
        {
            Player player = GameMain.mainPlayer;
            if (player == null || player.controller == null || player.controller.cmd.type != ECommand.Build) return "none";
            if (player.controller.cmd.mode == -1) return "dismantle";
            if (player.controller.cmd.mode >= 0) return "construction";
            return "other_build";
        }

        internal void OnGameEnd()
        {
            if (!recording) return;
            RecordMicrotaskStateSnapshot("episode_end");
            WriteEvent("episode_end", Fields("ticks", clock.ElapsedTicks, "unity_frame", Time.frameCount, "game_tick", SafeGameTick()));
            UnbindTaskEvents();
        }

        private void OnGUI()
        {
            if (recording) return;
            if (overlayStyle == null)
            {
                overlayStyle = new GUIStyle(GUI.skin.box) { alignment = TextAnchor.UpperLeft, fontSize = 16, wordWrap = true };
            }
            string status = "DSP Dreamer 擷取原型\n" + lastMessage + "\nCtrl+F8 開始/停止 | Ctrl+F9 注入測試 | Ctrl+Shift+F11 緊急停止";
            if (recording || stopping)
            {
                long drops = schedulerDrops + inFlightDrops + readbackErrors + writerDrops;
                double rate = expectedFrames == 0 ? 0 : 100.0 * drops / expectedFrames;
                status += "\n寫入 " + writtenFrames + " / 預期 " + expectedFrames + " | 掉幀 " + rate.ToString("F2", Invariant) + "% | 佇列 " + (writeQueue == null ? 0 : writeQueue.Count);
            }
            GUI.Box(new Rect(20, 20, 620, 100), status, overlayStyle);
        }

        private void OnDestroy()
        {
            Abort("plugin unload");
            UnbindTaskEvents();
            if (harmony != null) harmony.UnpatchSelf();
            Current = null;
        }

        private void ResetCounters()
        {
            expectedFrames = requestedFrames = writtenFrames = schedulerDrops = inFlightDrops = 0;
            readbackErrors = writerDrops = writerBytes = maxWriterQueue = 0;
            injectedActions = observedActions = actionLatencyTicksTotal = actionLatencyTicksMax = 0;
            taskEventCount = 0;
            suppressedAcquisitionDuplicates = 0;
            cursorVisibleFrames = cursorCompositedFrames = cursorFallbackFrames = 0;
            taskEventKinds.Clear();
            openPanelFields.Clear();
            cursorGlyphCache.Clear();
            unreadableCursorTextureIds.Clear();
            inputSamples = 0;
            outstandingReadbacks = 0;
            nextCaptureId = 0;
            lastObservedActionId = 0;
            lastObservedActionFrame = -1;
            pendingActions.Clear();
            pendingAcquisitions.Clear();
            semanticAcquisitionKeys.Clear();
            keyState.Clear();
            pendingDismantleObjectId = pendingDismantleProtoId = 0;
            pendingDismantleProtoName = string.Empty;
            electromagnetismTechId = automaticMetallurgyTechId = basicLogisticsTechId = 0;
            basicManufacturingTechId = electromagneticMatrixTechId = 0;
            lastBuildMode = null;
            recording = stopping = writerFinished = false;
        }

        private static long SafeGameTick()
        {
            try { return GameMain.gameTick; }
            catch { return -1; }
        }

        private void WriteEvent(string type, IDictionary<string, object> fields)
        {
            if (eventWriter == null) return;
            fields["type"] = type;
            lock (eventLock)
            {
                eventWriter.WriteLine(JsonObject(fields));
                eventWriter.Flush();
            }
        }

        private static Dictionary<string, object> Fields(params object[] values)
        {
            Dictionary<string, object> fields = new Dictionary<string, object>();
            for (int i = 0; i < values.Length; i += 2) fields[(string)values[i]] = values[i + 1];
            return fields;
        }

        private string[] SortedTaskEventKinds()
        {
            string[] result = new string[taskEventKinds.Count];
            taskEventKinds.CopyTo(result);
            Array.Sort(result, StringComparer.Ordinal);
            return result;
        }

        private string[] GetMissingTaskEventKinds()
        {
            List<string> missing = new List<string>();
            for (int i = 0; i < RequiredTaskEventKinds.Length; i++)
            {
                if (!taskEventKinds.Contains(RequiredTaskEventKinds[i])) missing.Add(RequiredTaskEventKinds[i]);
            }
            return missing.ToArray();
        }

        private static string JoinInts(int[] values)
        {
            if (values == null || values.Length == 0) return string.Empty;
            string[] text = new string[values.Length];
            for (int i = 0; i < values.Length; i++) text[i] = values[i].ToString(Invariant);
            return string.Join(",", text);
        }

        private static string JoinItemNames(int[] itemIds)
        {
            if (itemIds == null || itemIds.Length == 0) return string.Empty;
            string[] names = new string[itemIds.Length];
            for (int i = 0; i < itemIds.Length; i++) names[i] = ItemName(itemIds[i]);
            return string.Join(",", names);
        }

        private static int FactoryObjectProtoId(PlanetFactory factory, int objectId)
        {
            if (factory == null) return 0;
            if (objectId > 0 && objectId < factory.entityPool.Length) return factory.entityPool[objectId].protoId;
            int prebuildId = -objectId;
            if (prebuildId > 0 && prebuildId < factory.prebuildPool.Length) return factory.prebuildPool[prebuildId].protoId;
            return 0;
        }

        private static string ItemName(int id)
        {
            ItemProto proto = id > 0 ? LDB.items.Select(id) : null;
            return proto == null ? string.Empty : proto.name;
        }

        private static string TechName(int id)
        {
            TechProto proto = id > 0 ? LDB.techs.Select(id) : null;
            return proto == null ? string.Empty : proto.name;
        }

        private static string RecipeName(int id)
        {
            RecipeProto proto = id > 0 ? LDB.recipes.Select(id) : null;
            return proto == null ? string.Empty : proto.name;
        }

        private static string VegeName(int id)
        {
            VegeProto proto = id > 0 ? LDB.veges.Select(id) : null;
            return proto == null ? string.Empty : proto.name;
        }

        private static string MiningProtoName(PlayerAction_Mine action)
        {
            if (action == null || action.miningProtoId <= 0) return string.Empty;
            if (action.miningType == EObjectType.Vein)
            {
                VeinProto vein = LDB.veins.Select(action.miningProtoId);
                return vein == null ? string.Empty : vein.name;
            }
            if (action.miningType == EObjectType.Vegetable) return VegeName(action.miningProtoId);
            return string.Empty;
        }

        private static string JsonObject(IDictionary<string, object> fields)
        {
            StringBuilder builder = new StringBuilder("{");
            bool first = true;
            foreach (KeyValuePair<string, object> pair in fields)
            {
                if (!first) builder.Append(',');
                first = false;
                builder.Append('"').Append(Escape(pair.Key)).Append("\":").Append(JsonValue(pair.Value));
            }
            return builder.Append('}').ToString();
        }

        private static string JsonValue(object value)
        {
            if (value == null) return "null";
            if (value is bool) return (bool)value ? "true" : "false";
            if (value is string) return "\"" + Escape((string)value) + "\"";
            if (value is float) return ((float)value).ToString("R", Invariant);
            if (value is double) return ((double)value).ToString("R", Invariant);
            if (value is IFormattable) return ((IFormattable)value).ToString(null, Invariant);
            return "\"" + Escape(value.ToString()) + "\"";
        }

        private static string Escape(string value)
        {
            return value.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
        }

        private static double TicksToMilliseconds(long ticks) { return 1000.0 * ticks / Stopwatch.Frequency; }
        private static double TicksToSeconds(long ticks) { return (double)ticks / Stopwatch.Frequency; }

        private static readonly KeyCode[] DesktopKeys = BuildDesktopKeys();

        private static KeyCode[] BuildDesktopKeys()
        {
            List<KeyCode> keys = new List<KeyCode>();
            foreach (KeyCode key in Enum.GetValues(typeof(KeyCode)))
            {
                int value = (int)key;
                if (value >= 8 && value < (int)KeyCode.Mouse0 && key != KeyCode.None) keys.Add(key);
            }
            return keys.ToArray();
        }

        private static INPUT KeyboardInput(ushort scanCode, bool keyUp)
        {
            return new INPUT
            {
                type = 1,
                union = new InputUnion { keyboard = new KEYBDINPUT { wScan = scanCode, dwFlags = 0x0008u | (keyUp ? 0x0002u : 0u) } }
            };
        }

        private static INPUT MouseMoveInput(int dx, int dy)
        {
            return new INPUT
            {
                type = 0,
                union = new InputUnion { mouse = new MOUSEINPUT { dx = dx, dy = dy, dwFlags = 0x0001u } }
            };
        }

        [DllImport("user32.dll", SetLastError = true)]
        private static extern uint SendInput(uint inputCount, INPUT[] inputs, int inputSize);

        [StructLayout(LayoutKind.Sequential)]
        private struct INPUT { public uint type; public InputUnion union; }
        [StructLayout(LayoutKind.Explicit)]
        private struct InputUnion
        {
            [FieldOffset(0)] public MOUSEINPUT mouse;
            [FieldOffset(0)] public KEYBDINPUT keyboard;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr extraInfo; }
        [StructLayout(LayoutKind.Sequential)]
        private struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr extraInfo; }

        private sealed class CaptureSlot
        {
            public int Index;
            public int Busy;
            public byte[] Buffer;
            public RenderTexture SourceTarget;
            public RenderTexture Target;
        }

        private sealed class FramePacket
        {
            public FramePacket(CaptureSlot slot, long captureId, long requestedTicks, long completedTicks, int unityFrame, long gameTick, long actionId, CursorSnapshot cursor)
            {
                Slot = slot; CaptureId = captureId; RequestedTicks = requestedTicks; CompletedTicks = completedTicks;
                UnityFrame = unityFrame; GameTick = gameTick; ActionId = actionId; Cursor = cursor;
            }
            public CaptureSlot Slot { get; private set; }
            public long CaptureId { get; private set; }
            public long RequestedTicks { get; private set; }
            public long CompletedTicks { get; private set; }
            public int UnityFrame { get; private set; }
            public long GameTick { get; private set; }
            public long ActionId { get; private set; }
            public CursorSnapshot Cursor { get; private set; }
        }

        private sealed class CursorSnapshot
        {
            public static readonly CursorSnapshot Hidden = new CursorSnapshot(false, -1, -1, -1, "none", FallbackCursorGlyph, 0, 0, 0, 0);

            public CursorSnapshot(bool visible, int hotspotX, int hotspotY, int index, string glyphSource, CursorGlyph glyph, int left, int top, int drawWidth, int drawHeight)
            {
                Visible = visible;
                HotspotX = hotspotX;
                HotspotY = hotspotY;
                Index = index;
                GlyphSource = glyphSource;
                Glyph = glyph;
                Left = left;
                Top = top;
                DrawWidth = drawWidth;
                DrawHeight = drawHeight;
            }

            public bool Visible { get; private set; }
            public int HotspotX { get; private set; }
            public int HotspotY { get; private set; }
            public int Index { get; private set; }
            public string GlyphSource { get; private set; }
            public CursorGlyph Glyph { get; private set; }
            public int Left { get; private set; }
            public int Top { get; private set; }
            public int DrawWidth { get; private set; }
            public int DrawHeight { get; private set; }
            public int CompositedPixels { get; set; }
        }

        private sealed class PendingAction
        {
            public PendingAction(long id, long requestedTicks) { Id = id; RequestedTicks = requestedTicks; }
            public long Id { get; private set; }
            public long RequestedTicks { get; private set; }
        }

        private sealed class PendingAcquisition
        {
            public PendingAcquisition(int itemId, int count, int inc, long gameTick, int unityFrame, long ticks)
            {
                ItemId = itemId;
                Count = count;
                Inc = inc;
                GameTick = gameTick;
                UnityFrame = unityFrame;
                Ticks = ticks;
            }
            public int ItemId { get; private set; }
            public int Count { get; private set; }
            public int Inc { get; private set; }
            public long GameTick { get; private set; }
            public int UnityFrame { get; private set; }
            public long Ticks { get; private set; }
        }
    }

    internal sealed class MinerProductionState
    {
        public int IronBefore;
        public int CopperBefore;
    }

    internal sealed class MachineCycleState
    {
        public int RecipeId;
        public int CycleCount;
        public int ExtraCycleCount;
    }

    internal sealed class SorterDeliveryState
    {
        public int InserterId;
        public int InserterEntityId;
        public int SourceEntityId;
        public int TargetEntityId;
        public int ItemId;
        public int ItemCount;
        public float Power;

        public static SorterDeliveryState Capture(InserterComponent component, float power)
        {
            if (CaptureProbePlugin.Current == null || !CaptureProbePlugin.Current.IsRecording
                || power < 0.1f || component.stage != EInserterStage.Inserting
                || component.itemId <= 0 || component.itemCount <= 0 || component.insertTarget <= 0)
            {
                return null;
            }
            return new SorterDeliveryState
            {
                InserterId = component.id,
                InserterEntityId = component.entityId,
                SourceEntityId = component.pickTarget,
                TargetEntityId = component.insertTarget,
                ItemId = component.itemId,
                ItemCount = component.itemCount,
                Power = power,
            };
        }

        public void Complete(PlanetFactory factory, InserterComponent component)
        {
            int remaining = component.itemId == ItemId ? component.itemCount : 0;
            int delivered = ItemCount - remaining;
            if (delivered > 0 && CaptureProbePlugin.Current != null)
            {
                CaptureProbePlugin.Current.RecordSorterDelivery(factory, this, delivered);
            }
        }
    }

    [HarmonyPatch(typeof(VFInput), nameof(VFInput.OnUpdate))]
    internal static class VFInputOnUpdatePatch
    {
        private static void Postfix()
        {
            if (CaptureProbePlugin.Current != null) CaptureProbePlugin.Current.RecordInputSample();
        }
    }

    [HarmonyPatch(typeof(GameMain), nameof(GameMain.Begin))]
    internal static class GameMainBeginPatch
    {
        private static void Postfix()
        {
            if (CaptureProbePlugin.Current != null) CaptureProbePlugin.Current.OnGameBegin();
        }
    }

    [HarmonyPatch(typeof(GameMain), nameof(GameMain.End))]
    internal static class GameMainEndPatch
    {
        private static void Prefix()
        {
            if (CaptureProbePlugin.Current != null) CaptureProbePlugin.Current.OnGameEnd();
        }
    }

    [HarmonyPatch(typeof(GameHistoryData), nameof(GameHistoryData.EnqueueTech))]
    internal static class GameHistoryDataEnqueueTechPatch
    {
        private static void Prefix(GameHistoryData __instance, int techId, out int __state)
        {
            __state = __instance.TechQueuedCount(techId);
        }

        private static void Postfix(GameHistoryData __instance, int techId, int __state)
        {
            int queuedCount = __instance.TechQueuedCount(techId);
            if (queuedCount > __state && CaptureProbePlugin.Current != null)
            {
                CaptureProbePlugin.Current.RecordTechEnqueued(techId, queuedCount);
            }
        }
    }

    [HarmonyPatch(typeof(MechaForge), nameof(MechaForge.AddTask))]
    internal static class MechaForgeAddTaskPatch
    {
        private static void Postfix(int recipeId, int count, ForgeTask __result)
        {
            if (__result != null && CaptureProbePlugin.Current != null)
            {
                CaptureProbePlugin.Current.RecordCraftEnqueued(recipeId, count, __result);
            }
        }
    }

    [HarmonyPatch(typeof(MechaForge), "TaskDeliver")]
    internal static class MechaForgeTaskDeliverPatch
    {
        private static void Prefix(ForgeTask task)
        {
            if (CaptureProbePlugin.Current != null) CaptureProbePlugin.Current.RecordCraftCompleted(task);
        }
    }

    [HarmonyPatch(typeof(PlayerAction_Mine), "AddProductionStat")]
    internal static class PlayerActionMineAddProductionStatPatch
    {
        private static void Postfix(PlayerAction_Mine __instance, int itemId, int itemCount, PlanetFactory factory)
        {
            if (itemCount > 0 && CaptureProbePlugin.Current != null)
            {
                CaptureProbePlugin.Current.RecordManualMiningYield(__instance, itemId, itemCount, factory);
            }
        }
    }

    [HarmonyPatch(typeof(MinerComponent), nameof(MinerComponent.InternalUpdate))]
    internal static class MinerComponentInternalUpdatePatch
    {
        private static void Prefix(int[] productRegister, out MinerProductionState __state)
        {
            __state = null;
            if (CaptureProbePlugin.Current == null || !CaptureProbePlugin.Current.IsRecording || productRegister == null
                || productRegister.Length <= 1002)
            {
                return;
            }
            __state = new MinerProductionState
            {
                IronBefore = productRegister[1001],
                CopperBefore = productRegister[1002],
            };
        }

        private static void Postfix(ref MinerComponent __instance, PlanetFactory factory, float power, int[] productRegister, MinerProductionState __state)
        {
            if (__state == null || productRegister == null || productRegister.Length <= 1002 || CaptureProbePlugin.Current == null) return;
            int iron = productRegister[1001] - __state.IronBefore;
            int copper = productRegister[1002] - __state.CopperBefore;
            if (iron > 0) CaptureProbePlugin.Current.RecordMinerProduction(factory, __instance, power, 1001, iron);
            if (copper > 0) CaptureProbePlugin.Current.RecordMinerProduction(factory, __instance, power, 1002, copper);
        }
    }

    [HarmonyPatch(typeof(AssemblerComponent), nameof(AssemblerComponent.InternalUpdate))]
    internal static class AssemblerComponentInternalUpdatePatch
    {
        private static void Prefix(ref AssemblerComponent __instance, out MachineCycleState __state)
        {
            __state = CaptureProbePlugin.Current == null || !CaptureProbePlugin.Current.IsRecording || __instance.recipeId <= 0
                ? null
                : new MachineCycleState
                {
                    RecipeId = __instance.recipeId,
                    CycleCount = __instance.cycleCount,
                    ExtraCycleCount = __instance.extraCycleCount,
                };
        }

        private static void Postfix(ref AssemblerComponent __instance, float power, MachineCycleState __state)
        {
            if (__state == null || __instance.recipeId != __state.RecipeId || CaptureProbePlugin.Current == null) return;
            int normalCycles = __instance.cycleCount - __state.CycleCount;
            if (normalCycles <= 0) return;
            CaptureProbePlugin.Current.RecordMachineBatch(
                "assembler",
                __instance.entityId,
                __instance.id,
                __instance.recipeId,
                __instance.recipeType,
                __instance.recipeExecuteData,
                power,
                normalCycles,
                __instance.extraCycleCount - __state.ExtraCycleCount);
        }
    }

    [HarmonyPatch(typeof(LabComponent), nameof(LabComponent.InternalUpdateAssemble))]
    internal static class LabComponentInternalUpdateAssemblePatch
    {
        private static void Prefix(ref LabComponent __instance, out MachineCycleState __state)
        {
            __state = CaptureProbePlugin.Current == null || !CaptureProbePlugin.Current.IsRecording || __instance.recipeId <= 0
                ? null
                : new MachineCycleState
                {
                    RecipeId = __instance.recipeId,
                    CycleCount = __instance.cycleCount,
                    ExtraCycleCount = __instance.extraCycleCount,
                };
        }

        private static void Postfix(ref LabComponent __instance, float power, MachineCycleState __state)
        {
            if (__state == null || __instance.recipeId != __state.RecipeId || CaptureProbePlugin.Current == null) return;
            int normalCycles = __instance.cycleCount - __state.CycleCount;
            if (normalCycles <= 0) return;
            CaptureProbePlugin.Current.RecordMachineBatch(
                "lab",
                __instance.entityId,
                __instance.id,
                __instance.recipeId,
                ERecipeType.Research,
                __instance.recipeExecuteData,
                power,
                normalCycles,
                __instance.extraCycleCount - __state.ExtraCycleCount);
        }
    }

    [HarmonyPatch(typeof(InserterComponent), nameof(InserterComponent.InternalUpdate))]
    internal static class InserterComponentInternalUpdatePatch
    {
        private static void Prefix(ref InserterComponent __instance, float power, out SorterDeliveryState __state)
        {
            __state = SorterDeliveryState.Capture(__instance, power);
        }

        private static void Postfix(ref InserterComponent __instance, PlanetFactory factory, SorterDeliveryState __state)
        {
            if (__state != null) __state.Complete(factory, __instance);
        }
    }

    [HarmonyPatch(typeof(InserterComponent), nameof(InserterComponent.InternalUpdateNoAnim))]
    internal static class InserterComponentInternalUpdateNoAnimPatch
    {
        private static void Prefix(ref InserterComponent __instance, float power, out SorterDeliveryState __state)
        {
            __state = SorterDeliveryState.Capture(__instance, power);
        }

        private static void Postfix(ref InserterComponent __instance, PlanetFactory factory, SorterDeliveryState __state)
        {
            if (__state != null) __state.Complete(factory, __instance);
        }
    }

    [HarmonyPatch(typeof(PlanetFactory), nameof(PlanetFactory.RemoveVegeWithComponents))]
    internal static class PlanetFactoryRemoveVegeWithComponentsPatch
    {
        private static void Prefix(PlanetFactory __instance, int id, out bool __state)
        {
            __state = id > 0
                && id < __instance.vegeCursor
                && id < __instance.vegePool.Length
                && __instance.vegePool[id].protoId == 9999;
        }

        private static void Postfix(int id, bool __state)
        {
            if (__state && CaptureProbePlugin.Current != null)
            {
                CaptureProbePlugin.Current.RecordLandingCapsuleDismantled(id);
            }
        }
    }

    [HarmonyPatch(typeof(ManualBehaviour), nameof(ManualBehaviour._Open))]
    internal static class ManualBehaviourOpenPatch
    {
        private static void Prefix(ManualBehaviour __instance, out bool __state)
        {
            __state = __instance.active;
        }

        private static void Postfix(ManualBehaviour __instance, bool __state)
        {
            if (!__state && __instance.active && CaptureProbePlugin.Current != null)
            {
                CaptureProbePlugin.Current.RecordPanelOpened(__instance);
            }
        }
    }

    [HarmonyPatch(typeof(ManualBehaviour), nameof(ManualBehaviour._Close))]
    internal static class ManualBehaviourClosePatch
    {
        private static void Prefix(ManualBehaviour __instance, out bool __state)
        {
            __state = __instance.active;
        }

        private static void Postfix(ManualBehaviour __instance, bool __state)
        {
            if (__state && !__instance.active && CaptureProbePlugin.Current != null)
            {
                CaptureProbePlugin.Current.RecordPanelClosed(__instance);
            }
        }
    }
}
