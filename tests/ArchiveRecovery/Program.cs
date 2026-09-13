using System;
using System.IO;
using System.Text;
using System.Threading;
using DSPDreamer.Recorder;

internal static class Program
{
    private static int Main(string[] args)
    {
        try
        {
            Directory.CreateDirectory(args[0]);
            using (var writer = new SegmentWriter(args[0], args[1]))
            using (var events = new StreamWriter(new FileStream(Path.Combine(args[0], "events.ndjson"),
                FileMode.CreateNew, FileAccess.Write, FileShare.Read), new UTF8Encoding(false)))
            {
                string metadata = Json.Encode(Json.Fields("schema", "dsp-recording/1", "catalog", "action_catalog_v3",
                    "source_kind", "synthetic", "ticks_frequency", 1000, "recording_session_id", "native-session",
                    "episode_id", "native-episode", "attempt_id", "native-attempt"));
                for (int i = 0; i < 200; i++)
                    writer.Write(new byte[640 * 360 * 4], Json.Fields("ticks", i * 50, "requested_ticks", i * 50,
                        "capture_id", i, "sequence_number", i, "unity_frame", i, "game_tick", i,
                        "cursor", Json.Fields("visible", false)));
                if (args.Length > 2)
                    File.WriteAllText(Path.Combine(args[0], "checkpoint-000000.json.partial"), "retain");
                writer.Checkpoint(events, metadata);
                if (args.Length > 2)
                {
                    File.WriteAllText(Path.Combine(args[0], "checkpoint-returned"), "ready");
                    writer.Finish(); // Must surface the background publication failure.
                    throw new Exception("Checkpoint failure was ignored");
                }
                for (int i = 200; i < 230; i++)
                {
                    events.WriteLine(Json.Encode(Json.Fields("type", "control_request", "ticks", i * 50,
                        "sequence_number", i + 1000, "operation", "after_checkpoint")));
                    writer.Write(new byte[640 * 360 * 4], Json.Fields("ticks", i * 50, "requested_ticks", i * 50,
                        "capture_id", i, "sequence_number", i, "unity_frame", i, "game_tick", i,
                        "cursor", Json.Fields("visible", false)));
                }
                events.Flush();
                File.WriteAllText(Path.Combine(args[0], "append-ready"), "ready");
                Thread.Sleep(60000); // The test terminates this process before Finish/SOURCE publication.
            }
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
