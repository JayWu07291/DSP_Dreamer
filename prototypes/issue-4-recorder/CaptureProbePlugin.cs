using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
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
        public const string PluginVersion = "0.1.4";

        private const int SlotCount = 12;
        private const int SpaceCapsuleProtoId = 9999;
        private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
        private static readonly string[] RequiredTaskEventKinds =
        {
            "landing_capsule_dismantled",
            "tech_tree_opened",
            "tech_enqueued",
            "craft_enqueued",
            "craft_completed",
            "tech_unlocked",
            "manual_mining_yield",
            "factory_build"
        };
        internal static CaptureProbePlugin Current;

        private readonly object eventLock = new object();
        private readonly Stopwatch clock = new Stopwatch();
        private readonly Dictionary<KeyCode, bool> keyState = new Dictionary<KeyCode, bool>();
        private readonly Queue<PendingAction> pendingActions = new Queue<PendingAction>();
        private readonly HashSet<string> taskEventKinds = new HashSet<string>(StringComparer.Ordinal);
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
        private long lastObservedActionId;
        private int lastObservedActionFrame = -1;
        private long inputSamples;
        private int sourceWidth;
        private int sourceHeight;
        private string sourceDisplayMode;
        private int outstandingReadbacks;
        private long releaseWAtTicks;
        private bool injectedWHeld;
        private string lastMessage = "Ctrl+F8 開始 10 Hz 擷取";
        private GUIStyle overlayStyle;

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
                "capture_strategy", "full_frame_then_bilinear_gpu_scale",
                "unity_frame", Time.frameCount,
                "game_tick", SafeGameTick()));
            recording = true;
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
            requestedFrames++;
            Interlocked.Increment(ref outstandingReadbacks);
            WriteEvent("capture_requested", Fields(
                "capture_id", captureId,
                "slot", slot.Index,
                "requested_ticks", requestedTicks,
                "unity_frame", unityFrame,
                "game_tick", gameTick,
                "pending_action_id", actionId));

            try
            {
                ScreenCapture.CaptureScreenshotIntoRenderTexture(slot.SourceTarget);
                Graphics.Blit(slot.SourceTarget, slot.Target);
                AsyncGPUReadback.Request(slot.Target, 0, TextureFormat.RGBA32, request => CompleteReadback(request, slot, captureId, requestedTicks, unityFrame, gameTick, actionId));
            }
            catch (Exception exception)
            {
                readbackErrors++;
                Interlocked.Exchange(ref slot.Busy, 0);
                Interlocked.Decrement(ref outstandingReadbacks);
                WriteEvent("capture_drop", Fields("reason", "request_exception", "capture_id", captureId, "error", exception.Message));
            }
        }

        private void CompleteReadback(AsyncGPUReadbackRequest request, CaptureSlot slot, long captureId, long requestedTicks, int unityFrame, long gameTick, long actionId)
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
                FramePacket packet = new FramePacket(slot, captureId, requestedTicks, clock.ElapsedTicks, unityFrame, gameTick, actionId);
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
                    WriteEvent("capture_written", Fields(
                        "capture_id", packet.CaptureId,
                        "file_offset", offset,
                        "byte_count", packet.Slot.Buffer.Length,
                        "requested_ticks", packet.RequestedTicks,
                        "completed_ticks", packet.CompletedTicks,
                        "unity_frame", packet.UnityFrame,
                        "game_tick", packet.GameTick,
                        "pending_action_id", packet.ActionId));
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
                "capture_strategy", "full_frame_then_bilinear_gpu_scale",
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
            PlanetFactory.onFactoryBuildEntity += OnFactoryBuild;
            PlanetFactory.beforeFactoryDismantleObject += OnBeforeDismantle;
            PlanetFactory.onFactoryDismantleObject += OnAfterDismantle;
        }

        private void UnbindTaskEvents()
        {
            if (GameMain.history != null) GameMain.history.onTechUnlocked -= OnTechUnlocked;
            PlanetFactory.onFactoryBuildEntity -= OnFactoryBuild;
            PlanetFactory.beforeFactoryDismantleObject -= OnBeforeDismantle;
            PlanetFactory.onFactoryDismantleObject -= OnAfterDismantle;
        }

        private void OnTechUnlocked(int techId, int level, bool direct)
        {
            WriteTaskEvent("tech_unlocked", Fields("tech_id", techId, "level", level, "direct", direct));
        }

        private void OnFactoryBuild(PlanetFactory factory, int entityId, int prebuildId)
        {
            int protoId = entityId > 0 && entityId < factory.entityPool.Length ? factory.entityPool[entityId].protoId : 0;
            WriteTaskEvent("factory_build", Fields("entity_id", entityId, "prebuild_id", prebuildId, "proto_id", protoId));
        }

        private void OnBeforeDismantle(PlanetFactory factory, int objectId)
        {
            WriteTaskEvent("before_dismantle", Fields("object_id", objectId));
        }

        private void OnAfterDismantle(PlanetFactory factory, int objectId)
        {
            WriteTaskEvent("after_dismantle", Fields("object_id", objectId));
        }

        internal void RecordTechTreeOpened()
        {
            WriteTaskEvent("tech_tree_opened", Fields());
        }

        internal void RecordTechEnqueued(int techId, int queuedCount)
        {
            WriteTaskEvent("tech_enqueued", Fields("tech_id", techId, "queued_count", queuedCount));
        }

        internal void RecordCraftEnqueued(int recipeId, int count, ForgeTask task)
        {
            WriteTaskEvent("craft_enqueued", Fields(
                "recipe_id", recipeId,
                "count", count,
                "product_ids", JoinInts(task == null ? null : task.productIds),
                "product_counts", JoinInts(task == null ? null : task.productCounts)));
        }

        internal void RecordCraftCompleted(ForgeTask task)
        {
            if (task == null) return;
            WriteTaskEvent("craft_completed", Fields(
                "recipe_id", task.recipeId,
                "product_ids", JoinInts(task.productIds),
                "product_counts", JoinInts(task.productCounts)));
        }

        internal void RecordManualMiningYield(PlayerAction_Mine action, int itemId, int itemCount, PlanetFactory factory)
        {
            WriteTaskEvent("manual_mining_yield", Fields(
                "item_id", itemId,
                "item_count", itemCount,
                "mining_type", action == null ? "unknown" : action.miningType.ToString(),
                "mining_id", action == null ? 0 : action.miningId,
                "mining_proto_id", action == null ? 0 : action.miningProtoId,
                "planet_id", factory == null || factory.planet == null ? 0 : factory.planet.id));
        }

        internal void RecordLandingCapsuleDismantled(int vegeId)
        {
            WriteTaskEvent("landing_capsule_dismantled", Fields("vege_id", vegeId, "proto_id", SpaceCapsuleProtoId));
        }

        private void WriteTaskEvent(string name, IDictionary<string, object> fields)
        {
            if (!recording) return;
            taskEventCount++;
            taskEventKinds.Add(name);
            fields["name"] = name;
            fields["unity_frame"] = Time.frameCount;
            fields["game_tick"] = SafeGameTick();
            fields["ticks"] = clock.IsRunning ? clock.ElapsedTicks : 0;
            WriteEvent("task_event", fields);
        }

        internal void OnGameBegin()
        {
            if (!recording) return;
            BindTaskEvents();
            WriteEvent("episode_begin", Fields("unity_frame", Time.frameCount, "game_tick", SafeGameTick()));
        }

        internal void OnGameEnd()
        {
            if (!recording) return;
            WriteEvent("episode_end", Fields("unity_frame", Time.frameCount, "game_tick", SafeGameTick()));
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
            taskEventKinds.Clear();
            inputSamples = 0;
            outstandingReadbacks = 0;
            nextCaptureId = 0;
            lastObservedActionId = 0;
            lastObservedActionFrame = -1;
            pendingActions.Clear();
            keyState.Clear();
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
            public FramePacket(CaptureSlot slot, long captureId, long requestedTicks, long completedTicks, int unityFrame, long gameTick, long actionId)
            {
                Slot = slot; CaptureId = captureId; RequestedTicks = requestedTicks; CompletedTicks = completedTicks;
                UnityFrame = unityFrame; GameTick = gameTick; ActionId = actionId;
            }
            public CaptureSlot Slot { get; private set; }
            public long CaptureId { get; private set; }
            public long RequestedTicks { get; private set; }
            public long CompletedTicks { get; private set; }
            public int UnityFrame { get; private set; }
            public long GameTick { get; private set; }
            public long ActionId { get; private set; }
        }

        private sealed class PendingAction
        {
            public PendingAction(long id, long requestedTicks) { Id = id; RequestedTicks = requestedTicks; }
            public long Id { get; private set; }
            public long RequestedTicks { get; private set; }
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

    [HarmonyPatch(typeof(UITechTree), "_OnOpen")]
    internal static class UITechTreeOnOpenPatch
    {
        private static void Postfix()
        {
            if (CaptureProbePlugin.Current != null) CaptureProbePlugin.Current.RecordTechTreeOpened();
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
}
