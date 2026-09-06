// Throwaway issue-11 storage candidates. Each segment requires offline decode verification.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace DSPDreamer.CaptureProbe
{
    internal sealed class PrototypeFrameStorage : IDisposable
    {
        private readonly string root, codec, ffmpeg;
        private readonly int limit, width, height;
        private readonly Func<IDictionary<string, object>, string> json;
        private FileStream file;
        private Stream stream;
        private StreamWriter index;
        private Process process;
        private IntPtr processHandle;
        private Timer watchdog;
        private readonly StringBuilder errors = new StringBuilder();
        private int segment, count;
        private string partial, target;
        private bool closed;
        internal long Bytes;
        internal double MaxWriteMs, MaxFinalizeMs;
        internal double EncoderCpuSeconds;
        internal long EncoderPeakWorkingSet = -1;
        [StructLayout(LayoutKind.Sequential)]
        private struct MemoryCounters
        {
            public uint Size, PageFaultCount;
            public UIntPtr PeakWorkingSetSize, WorkingSetSize, QuotaPeakPagedPoolUsage, QuotaPagedPoolUsage;
            public UIntPtr QuotaPeakNonPagedPoolUsage, QuotaNonPagedPoolUsage, PagefileUsage, PeakPagefileUsage;
        }
        [DllImport("psapi.dll", SetLastError = true)]
        private static extern bool GetProcessMemoryInfo(IntPtr process, ref MemoryCounters counters, uint size);
        [DllImport("kernel32.dll")]
        private static extern IntPtr GetCurrentProcess();

        internal static long ReadWorkingSet(IntPtr handle, bool peak)
        {
            var counters = new MemoryCounters { Size = (uint)Marshal.SizeOf(typeof(MemoryCounters)) };
            if (!GetProcessMemoryInfo(handle, ref counters, counters.Size)) return -1;
            return (long)(peak ? counters.PeakWorkingSetSize : counters.WorkingSetSize).ToUInt64();
        }

        internal static long CurrentWorkingSet() { return ReadWorkingSet(GetCurrentProcess(), false); }
        [DllImport("kernel32.dll")]
        private static extern bool GetProcessTimes(IntPtr handle, out long creation, out long exit, out long kernel, out long user);

        internal PrototypeFrameStorage(string root, string codec, string ffmpeg, int limit, int width, int height,
            Func<IDictionary<string, object>, string> json)
        {
            if (codec != "raw" && codec != "ffv1" && codec != "gzip1") throw new ArgumentException("Unknown storage codec");
            if (limit <= 0) throw new ArgumentException("SegmentFrames must be positive");
            if (codec == "ffv1" && !File.Exists(ffmpeg)) throw new FileNotFoundException("FFmpeg executable", ffmpeg);
            this.root = root; this.codec = codec; this.ffmpeg = ffmpeg; this.limit = limit;
            this.width = width; this.height = height; this.json = json;
            if (codec == "raw")
            {
                file = new FileStream(Path.Combine(root, "frames.rgba"), FileMode.CreateNew, FileAccess.Write, FileShare.Read, 1048576);
                stream = file;
            }
        }

        private void OpenSegment()
        {
            string stem = "segment-" + segment.ToString("D6");
            target = Path.Combine(root, stem + (codec == "ffv1" ? ".mkv" : ".dwg"));
            partial = target + ".partial";
            index = new StreamWriter(new FileStream(Path.Combine(root, stem + ".index.ndjson"),
                FileMode.CreateNew, FileAccess.Write, FileShare.Read), new UTF8Encoding(false));
            index.AutoFlush = true;
            if (codec == "gzip1")
            {
                file = new FileStream(partial, FileMode.CreateNew, FileAccess.Write, FileShare.Read, 1048576);
                stream = file;
                stream.Write(new byte[] { 68, 87, 71, 49 }, 0, 4);
            }
            else
            {
                errors.Clear();
                var start = new ProcessStartInfo(ffmpeg,
                    "-hide_banner -loglevel error -nostdin -n -f rawvideo -pix_fmt rgba -video_size " + width + "x" + height +
                    " -framerate 20 -i pipe:0 -map 0:v:0 -an -fps_mode passthrough -c:v ffv1 -level 3 -coder 1 -context 0" +
                    " -g 1 -slicecrc 1 -slices 4 -threads 4 -pix_fmt bgra -f matroska \"" + partial + "\"")
                { UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardError = true };
                process = new Process { StartInfo = start };
                process.ErrorDataReceived += (s, e) => { if (e.Data != null) lock (errors) { if (errors.Length < 8192) errors.AppendLine(e.Data); } };
                process.Start();
                processHandle = process.Handle;
                process.BeginErrorReadLine();
                stream = process.StandardInput.BaseStream;
                // A dead encoder must not hold the writer thread and its twelve capture slots forever.
                Process guardedProcess = process;
                watchdog = new Timer(_ => { try { if (!guardedProcess.HasExited) guardedProcess.Kill(); } catch { } }, null, 5000, Timeout.Infinite);
            }
        }

        internal void Write(byte[] rgba, IDictionary<string, object> fields)
        {
            var sw = Stopwatch.StartNew();
            if (codec != "raw" && stream == null) OpenSegment();
            if (watchdog != null) watchdog.Change(5000, Timeout.Infinite);
            if (process != null)
            {
                EncoderPeakWorkingSet = Math.Max(EncoderPeakWorkingSet, ReadWorkingSet(processHandle, true));
            }
            fields["storage_codec"] = codec;
            fields["raw_virtual_offset"] = Bytes;
            fields["file_offset"] = codec == "raw" ? Bytes : -1L;
            if (codec == "gzip1")
            {
                fields["encoded_record_offset"] = file.Position;
                using (var buffer = new MemoryStream())
                {
                    using (var gzip = new GZipStream(buffer, CompressionLevel.Fastest, true)) gzip.Write(rgba, 0, rgba.Length);
                    byte[] compressed = buffer.ToArray();
                    byte[] header = BitConverter.GetBytes(compressed.Length);
                    stream.Write(header, 0, header.Length);
                    stream.Write(compressed, 0, compressed.Length);
                }
            }
            else stream.Write(rgba, 0, rgba.Length);
            if (codec != "raw")
            {
                fields["segment"] = Path.GetFileName(target);
                fields["decoded_frame_index"] = count;
                using (var hash = SHA256.Create()) fields["rgba_sha256"] = BitConverter.ToString(hash.ComputeHash(rgba)).Replace("-", "").ToLowerInvariant();
                fields["storage_state"] = "written_unverified";
                index.WriteLine(json(fields));
                count++;
            }
            Bytes += rgba.Length;
            if (codec != "raw" && count == limit) CloseSegment();
            sw.Stop();
            fields["storage_write_ms"] = sw.Elapsed.TotalMilliseconds;
            MaxWriteMs = Math.Max(MaxWriteMs, sw.Elapsed.TotalMilliseconds);
        }

        private void CloseSegment()
        {
            if (stream == null) return;
            var sw = Stopwatch.StartNew();
            if (process != null)
            {
                stream.Close();
                if (!process.WaitForExit(5000)) { process.Kill(); throw new IOException("FFmpeg finalization timeout"); }
                process.WaitForExit();
                if (process.ExitCode != 0) throw new IOException("FFmpeg failed: " + errors);
                EncoderCpuSeconds += ReadEncoderCpu();
                watchdog.Dispose(); watchdog = null;
                processHandle = IntPtr.Zero;
                process.Dispose(); process = null;
                using (var flush = new FileStream(partial, FileMode.Open, FileAccess.ReadWrite, FileShare.Read)) flush.Flush(true);
            }
            else { file.Flush(true); file.Dispose(); file = null; }
            stream = null;
            index.Flush();
            ((FileStream)index.BaseStream).Flush(true);
            index.Dispose(); index = null;
            File.Move(partial, target);
            var manifest = new Dictionary<string, object> {
                { "state", "closed_unverified" }, { "codec", codec }, { "file", Path.GetFileName(target) },
                { "frames", count }, { "width", width }, { "height", height }, { "pixel_format", codec == "ffv1" ? "bgra" : "rgba" },
                { "capture_pixel_format", "rgba" }, { "segment_frames_limit", limit },
                { "runtime", Environment.Version.ToString() }, { "ffmpeg", codec == "ffv1" ? ffmpeg : "" },
                { "parameters", codec == "ffv1" ? "ffv1 level=3 coder=1 context=0 g=1 slicecrc=1 slices=4 threads=4 bgra" : "GZipStream CompressionLevel.Fastest per frame" }
            };
            using (var f = new FileStream(target + ".unverified.json", FileMode.CreateNew, FileAccess.Write))
            using (var w = new StreamWriter(f, new UTF8Encoding(false))) { w.WriteLine(json(manifest)); w.Flush(); f.Flush(true); }
            count = 0; segment++;
            MaxFinalizeMs = Math.Max(MaxFinalizeMs, sw.Elapsed.TotalMilliseconds);
        }

        internal void Finish()
        {
            if (codec == "raw") { file.Flush(true); file.Dispose(); file = null; stream = null; }
            else CloseSegment();
            closed = true;
        }

        internal double CurrentEncoderCpuSeconds()
        {
            return EncoderCpuSeconds + ReadEncoderCpu();
        }

        private double ReadEncoderCpu()
        {
            long creation, exit, kernel, user;
            return processHandle != IntPtr.Zero && GetProcessTimes(processHandle, out creation, out exit, out kernel, out user)
                ? (kernel + user) / 10000000.0 : 0;
        }

        public void Dispose()
        {
            if (closed) return;
            // Failure leaves .partial and the flushed index for explicit prefix recovery.
            if (watchdog != null) watchdog.Dispose();
            if (process != null) { try { if (!process.HasExited) process.Kill(); } catch { } process.Dispose(); }
            if (index != null) index.Dispose();
            if (file != null) file.Dispose();
            closed = true;
        }
    }
}
