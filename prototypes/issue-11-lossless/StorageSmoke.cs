// Exercise the exact C# writer without requiring a game. This is not a live capture test.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Web.Script.Serialization;
using DSPDreamer.CaptureProbe;

internal static class StorageSmoke
{
    public static int Main(string[] args)
    {
        try { return Run(args); }
        catch (Exception e) { Console.Error.WriteLine(e.GetType().FullName); Console.Error.WriteLine(e.Message); return 2; }
    }

    private static int Run(string[] args)
    {
        string source = args[0], output = args[1], codec = args[2], ffmpeg = args[3];
        int frames = args.Length > 4 ? int.Parse(args[4]) : 405;
        bool crash = args.Length > 5 && args[5] == "crash";
        if (Directory.Exists(output)) throw new IOException("Output already exists");
        Directory.CreateDirectory(output);
        var json = new JavaScriptSerializer();
        var sw = Stopwatch.StartNew();
        var cpu = Process.GetCurrentProcess().TotalProcessorTime;
        using (var writer = new PrototypeFrameStorage(output, codec, ffmpeg, 200, 640, 360, json.Serialize))
        using (var raw = File.OpenRead(Path.Combine(source, "frames.rgba")))
        {
            writer.Prepare();
            byte[] bytes = new byte[640 * 360 * 4];
            int written = 0;
            foreach (var line in File.ReadLines(Path.Combine(source, "events.ndjson")))
            {
                var fields = json.Deserialize<Dictionary<string, object>>(line);
                if ((string)fields["type"] != "capture_written") continue;
                long offset = Convert.ToInt64(fields["file_offset"]);
                raw.Seek(offset, SeekOrigin.Begin);
                int read = 0;
                while (read < bytes.Length)
                {
                    int n = raw.Read(bytes, read, bytes.Length - read);
                    if (n == 0) throw new EndOfStreamException();
                    read += n;
                }
                fields["source_file_offset"] = offset;
                fields["source_run"] = Path.GetFullPath(source);
                writer.Write(bytes, fields);
                written++;
                if (written == frames) break;
            }
            if (written != frames) throw new Exception("Not enough source frames");
            if (crash)
            {
                // Kill this harness without disposal; current segment remains unverified.
                Process.GetCurrentProcess().Kill();
                return 99;
            }
            writer.Finish();
            long nativeRss = PrototypeFrameStorage.CurrentWorkingSet();
            if (nativeRss <= 0 || (codec == "ffv1" && writer.EncoderPeakWorkingSet <= 0))
                throw new Exception("Native process memory measurement unavailable");
            File.WriteAllText(Path.Combine(output, "smoke.json"), json.Serialize(new {
                test = "offline_exact_csharp_writer", codec, frames, wall_seconds = sw.Elapsed.TotalSeconds,
                writer_max_ms = writer.MaxWriteMs, finalize_max_ms = writer.MaxFinalizeMs,
                storage_prepare_ms = writer.PreparationMs,
                process_cpu_seconds = (Process.GetCurrentProcess().TotalProcessorTime - cpu).TotalSeconds,
                native_working_set_bytes = nativeRss, encoder_peak_working_set_bytes = writer.EncoderPeakWorkingSet,
                live_game = false
            }));
        }
        return 0;
    }
}
