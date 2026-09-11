using System;
using System.Collections.Generic;
using System.Linq;
using DSPDreamer.Recorder;

internal static class Program
{
    private static int Main()
    {
        var pairs = new List<int[]>();
        for (int a = 0; a < 20; a++)
            for (int b = a + 1; b < 20; b++)
            {
                var binary = new int[20]; binary[a] = binary[b] = 1;
                try { ModelAction.Validate(ModelAction.Catalog, binary, 60, 1); pairs.Add(new[] { a, b }); }
                catch (ArgumentException) { }
            }
        foreach (var catalog in new[] { "action_catalog_v1", "action_catalog_v2", "unknown" })
        {
            try { ModelAction.Validate(catalog, new int[20], 60, 1); return 1; }
            catch (ArgumentException) { }
        }
        Console.WriteLine(Json.Encode(Json.Fields("controls", ModelAction.Controls, "scan_codes", ModelAction.ScanCodes,
            "pixels", Enumerable.Range(0, 11).Select(ModelAction.Pixel).ToArray(), "legal_pairs", pairs)));
        return 0;
    }
}
