using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace DSPDreamer.Recorder
{
    internal sealed class SegmentWriter : IDisposable
    {
        internal const string FfmpegHash = "04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00";
        private readonly string root, executable;
        private readonly StreamWriter index;
        private Process encoder;
        private Timer watchdog;
        private int ordinal;
        private string partial;
        private readonly Dictionary<string, object> sealedSegments = new Dictionary<string, object>();
        internal bool AtBoundary => ordinal > 0 && ordinal % 200 == 0;

        internal static string HashFile(string path)
        {
            using (var stream = File.OpenRead(path))
            using (var hash = SHA256.Create()) return Hex(hash.ComputeHash(stream));
        }
        internal static string HashAssembly(Assembly assembly, string sourcePath)
        {
            // BepInEx 修補後從記憶體載入的組件沒有 Location；指紋記錄其磁碟來源。
            string path = string.IsNullOrEmpty(assembly.Location) ? sourcePath : assembly.Location;
            if (string.IsNullOrEmpty(path)) throw new IOException("找不到組件來源：" + assembly.FullName);
            if (AssemblyName.GetAssemblyName(path).FullName != assembly.FullName)
                throw new IOException("組件來源身分不符：" + path);
            return HashFile(path);
        }
        internal static string Hash(byte[] bytes)
        {
            using (var hash = SHA256.Create()) return Hex(hash.ComputeHash(bytes));
        }
        private static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }

        internal SegmentWriter(string root, string executable)
        {
            if (HashFile(executable) != FfmpegHash) throw new InvalidOperationException("Unknown FFmpeg executable");
            this.root = root;
            this.executable = executable;
            index = new StreamWriter(new FileStream(Path.Combine(root, "frames.ndjson"), FileMode.CreateNew,
                FileAccess.Write, FileShare.Read), new UTF8Encoding(false));
            Open(); // Prepare the first encoder before the capture clock begins.
        }

        private void Open()
        {
            partial = Path.Combine(root, "segment-" + (ordinal / 200).ToString("D6") + ".mkv.partial");
            var start = new ProcessStartInfo(executable,
                "-hide_banner -loglevel error -n -f rawvideo -pix_fmt rgba -video_size 640x360 -framerate 20 -i pipe:0 -an " +
                "-c:v ffv1 -level 3 -coder 1 -context 0 -g 1 -slicecrc 1 -slices 4 -threads 4 -pix_fmt bgra -f matroska \"" + partial + "\"")
            { UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
            encoder = Process.Start(start);
            encoder.OutputDataReceived += (sender, args) => { };
            encoder.ErrorDataReceived += (sender, args) => { };
            encoder.BeginOutputReadLine();
            encoder.BeginErrorReadLine();
            Process guarded = encoder;
            watchdog = new Timer(_ => { try { if (!guarded.HasExited) guarded.Kill(); } catch (InvalidOperationException) { } }, null, Timeout.Infinite, Timeout.Infinite);
        }

        internal void Write(byte[] rgba, Dictionary<string, object> frame)
        {
            if (encoder == null) Open();
            watchdog.Change(5000, Timeout.Infinite);
            encoder.StandardInput.BaseStream.Write(rgba, 0, rgba.Length);
            watchdog.Change(Timeout.Infinite, Timeout.Infinite);
            frame["ordinal"] = ordinal;
            frame["segment"] = "segment-" + (ordinal / 200).ToString("D6") + ".mkv";
            frame["segment_ordinal"] = ordinal % 200;
            frame["rgba_sha256"] = Hash(rgba);
            index.WriteLine(Json.Encode(frame));
            ordinal++;
            if (ordinal % 200 == 0) CloseSegment();
        }

        private void CloseSegment()
        {
            if (encoder == null) return;
            encoder.StandardInput.Close();
            if (!encoder.WaitForExit(10000)) { encoder.Kill(); throw new IOException("Encoder timeout"); }
            encoder.WaitForExit();
            if (encoder.ExitCode != 0) throw new IOException("Encoder failed; source retained");
            watchdog.Dispose();
            encoder.Dispose();
            encoder = null;
            using (var file = new FileStream(partial, FileMode.Open, FileAccess.ReadWrite)) file.Flush(true);
            File.Move(partial, partial.Substring(0, partial.Length - ".partial".Length));
            string name = Path.GetFileName(partial.Substring(0, partial.Length - ".partial".Length));
            sealedSegments[name] = FileInfo(name);
        }

        private Dictionary<string, object> FileInfo(string name)
        {
            using (var file = new FileStream(Path.Combine(root, name), FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            using (var hash = SHA256.Create())
                return Json.Fields("bytes", file.Length, "sha256", Hex(hash.ComputeHash(file)));
        }

        internal Dictionary<string, object> Seal(StreamWriter events)
        {
            index.Flush(); events.Flush();
            ((FileStream)index.BaseStream).Flush(true);
            ((FileStream)events.BaseStream).Flush(true);
            var files = new Dictionary<string, object>(sealedSegments);
            // ponytail: sidecar prefix hashing is quadratic across segments; use incremental hashes if it stalls the writer.
            files["frames.ndjson"] = FileInfo("frames.ndjson");
            files["events.ndjson"] = FileInfo("events.ndjson");
            return files;
        }

        internal void Checkpoint(StreamWriter events, string metadataSnapshot)
        {
            var files = Seal(events);
            string json = metadataSnapshot.Substring(0, metadataSnapshot.Length - 1) + ",\"sealed_files\":" + Json.Encode(files) + "}";
            string path = Path.Combine(root, "checkpoint-" + (ordinal / 200 - 1).ToString("D6") + ".json");
            using (var file = new FileStream(path + ".partial", FileMode.CreateNew))
            {
                byte[] bytes = Encoding.UTF8.GetBytes(json);
                file.Write(bytes, 0, bytes.Length); file.Flush(true);
            }
            File.Move(path + ".partial", path);
        }

        internal void Finish()
        {
            if (ordinal < 2) throw new IOException("Need at least two observations");
            CloseSegment();
            index.Flush();
            ((FileStream)index.BaseStream).Flush(true);
        }

        public void Dispose()
        {
            watchdog?.Dispose();
            if (encoder != null)
            {
                try { if (!encoder.HasExited) encoder.Kill(); } catch (InvalidOperationException) { }
                encoder.Dispose();
            }
            index.Dispose();
        }
    }
}
