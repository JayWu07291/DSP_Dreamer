using System;
using System.Linq;

namespace DSPDreamer.Recorder
{
    // Wire identities mirror dsp_dreamer.actions; tests compare the complete contract.
    public static class ModelAction
    {
        public const string Catalog = "action_catalog_v4";
        public const string CodecSha256 = "8e6b4754bf534c8eb5697aed8450e6dfd0c468648b799fce4d25b7ef53bc9352";
        public static readonly string[] Controls = { "Escape", "Digit1", "Digit2", "Tab", "W", "R", "T", "LeftControl",
            "A", "S", "D", "F", "LeftShift", "X", "C", "MouseLeft", "MouseRight", "MouseMiddle", "Space", "E", "B" };
        public static readonly ushort[] ScanCodes = { 1, 2, 3, 15, 17, 19, 20, 29, 30, 31, 32, 33, 42, 45, 46, 0, 0, 0, 57, 18, 48 };

        public static void Validate(string catalog, int[] binary, int mouse, int wheel)
        {
            if (catalog != Catalog || binary == null || binary.Length != Controls.Length || binary.Any(v => v != 0 && v != 1) ||
                mouse < 0 || mouse >= 121 || wheel < 0 || wheel >= 3)
                throw new ArgumentException("Incompatible model action");
            if (binary[4] + binary[9] > 1 || binary[8] + binary[10] > 1 || binary[7] + binary[12] > 1 ||
                binary[15] + binary[16] + binary[17] > 1)
                throw new ArgumentException("Forbidden action combination");
        }

        public static int Pixel(int bin)
        {
            if (bin < 0 || bin > 10) throw new ArgumentOutOfRangeException(nameof(bin));
            double value = (bin * 2 - 10) / 10.0;
            return (int)Math.Round(Math.Sign(value) * (Math.Exp(Math.Abs(value) * Math.Log(6)) - 1) * 2);
        }
    }

    public static class PolicyTiming
    {
        public static bool Passed(double[] latencies, long misses, long longestStreak)
        {
            if (latencies.Length == 0 || misses > latencies.Length * .01 || longestStreak >= 5 ||
                latencies.Any(v => double.IsNaN(v) || double.IsInfinity(v) || v < 0)) return false;
            var sorted = latencies.OrderBy(v => v).ToArray();
            Func<double, double> percentile = q => {
                double index = (sorted.Length - 1) * q;
                int lower = (int)index;
                return sorted[lower] + (sorted[Math.Min(lower + 1, sorted.Length - 1)] - sorted[lower]) * (index - lower);
            };
            return percentile(.95) <= 80 && percentile(.99) <= 100;
        }
    }
}
