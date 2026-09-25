using System;
using System.Collections.Generic;
using System.Linq;
using DSPDreamer.Recorder;

internal static class Program
{
    private static int Main()
    {
        var pairs = new List<int[]>();
        for (int a = 0; a < ModelAction.Controls.Length; a++)
            for (int b = a + 1; b < ModelAction.Controls.Length; b++)
            {
                var binary = new int[ModelAction.Controls.Length]; binary[a] = binary[b] = 1;
                try { ModelAction.Validate(ModelAction.Catalog, binary, 60, 1); pairs.Add(new[] { a, b }); }
                catch (ArgumentException) { }
            }
        foreach (var catalog in new[] { "action_catalog_v1", "action_catalog_v2", "action_catalog_v3", "unknown" })
        {
            try { ModelAction.Validate(catalog, new int[ModelAction.Controls.Length], 60, 1); return 1; }
            catch (ArgumentException) { }
        }
        var timings = new[] { new double[0], Enumerable.Repeat(20.0, 99).Concat(new[] { 101.0 }).ToArray(),
            Enumerable.Repeat(80.0, 100).ToArray(), Enumerable.Repeat(81.0, 100).ToArray(),
            Enumerable.Repeat(20.0, 500).ToArray() };
        Console.WriteLine(Json.Encode(Json.Fields("controls", ModelAction.Controls, "scan_codes", ModelAction.ScanCodes,
            "codec_sha256", ModelAction.CodecSha256,
            "timing_passed", timings.Select((v, i) => PolicyTiming.Passed(v, i == 1 ? 1 : i == 4 ? 5 : 0, i == 4 ? 5 : 0)).ToArray(),
            "pixels", Enumerable.Range(0, 11).Select(ModelAction.Pixel).ToArray(), "legal_pairs", pairs)));
        return 0;
    }
}
