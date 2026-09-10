using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;

namespace DSPDreamer.Recorder
{
    internal sealed class ProductionProgress
    {
        private sealed class Machine
        {
            internal int Product, Recipe, Batch;
            internal int[] Requires, Counts;
            internal bool Fixed, Pending, ManualLab, PendingManual;
            internal readonly Dictionary<int, long> Inputs = new Dictionary<int, long>();
            internal readonly HashSet<int> Delivered = new HashSet<int>();
        }
        private readonly int[] done;
        private readonly int version;
        private readonly Dictionary<string, Dictionary<string, object>> lines = new Dictionary<string, Dictionary<string, object>>();
        private readonly Dictionary<string, int> miners = new Dictionary<string, int>();
        private readonly HashSet<string> produced = new HashSet<string>();
        private readonly Dictionary<string, Machine> machines = new Dictionary<string, Machine>();
        private readonly Dictionary<Tuple<string, int>, long> stock = new Dictionary<Tuple<string, int>, long>();
        private readonly Dictionary<string, int> manual = new Dictionary<string, int>(), automatic = new Dictionary<string, int>();
        private static readonly Dictionary<int, int[]> recipes = new Dictionary<int, int[]> {
            { 1101, new[] { 2302, 1, 1001, 1 } }, { 1102, new[] { 2302, 1, 1001, 1 } },
            { 1104, new[] { 2302, 1, 1002, 1 } }, { 1202, new[] { 2303, 2, 1102, 2, 1104, 1 } },
            { 1301, new[] { 2303, 2, 1101, 2, 1104, 1 } }, { 6001, new[] { 2901, 1, 1202, 1, 1301, 1 } }
        };
        internal ProductionProgress(int[] done, int version = 2) { this.done = done; this.version = version; }
        private static int Number(Dictionary<string, object> e, string key) => Convert.ToInt32(e[key]);
        private static int[] Numbers(Dictionary<string, object> e, string key) =>
            ((IEnumerable)e[key]).Cast<object>().Select(Convert.ToInt32).ToArray();
        private static long Get<K>(Dictionary<K, long> values, K key) => values.TryGetValue(key, out long value) ? value : 0;
        private void ClearStock(string target)
        {
            foreach (var key in stock.Keys.Where(k => k.Item1 == target).ToArray()) stock.Remove(key);
        }

        private bool Connected(string target, HashSet<string> seen = null)
        {
            if (miners.TryGetValue(target, out int ore)) return ore > 0;
            if (seen == null) seen = new HashSet<string>();
            if (seen.Contains(target) || !machines.TryGetValue(target, out Machine m) || !m.Fixed ||
                !lines.TryGetValue(target, out var line) || !(bool)line["powered"]) return false;
            var next = new HashSet<string>(seen) { target };
            string[] sources = ((IEnumerable)line["sources"]).Cast<string>().ToArray();
            int[] items = Numbers(line, "items"), belts = Numbers(line, "belts");
            return m.Requires.All(need => Enumerable.Range(0, sources.Length).Any(i => items[i] == need &&
                (miners.TryGetValue(sources[i], out int item) && item == need && belts[i] == 1 ||
                 produced.Contains(sources[i]) && machines.TryGetValue(sources[i], out Machine source) && source.Product == need) &&
                Connected(sources[i], next)));
        }

        internal void Apply(Dictionary<string, object> e)
        {
            string kind = (string)e["kind"];
            string target = e.ContainsKey("target") ? (string)e["target"] : "";
            if (kind == "line_state") { lines[target] = e; return; }
            if (kind == "machine_config")
            {
                produced.Remove(target);
                machines.TryGetValue(target, out Machine old);
                int product = Number(e, "product"), recipeId = Number(e, "recipe_id");
                int[] requires = Numbers(e, "requires"), counts = Numbers(e, "counts");
                bool allowed = recipes.TryGetValue(product, out int[] recipe) && Number(e, "proto_id") == recipe[0] &&
                    Number(e, "batch_size") == recipe[1] && requires.SequenceEqual(recipe.Where((v, i) => i >= 2 && i % 2 == 0)) &&
                    counts.SequenceEqual(recipe.Where((v, i) => i >= 2 && i % 2 == 1));
                machines[target] = new Machine { Product = product, Recipe = recipeId, Requires = requires, Counts = counts,
                    Batch = Number(e, "batch_size"), Fixed = allowed && (version >= 3 || old == null || old.Fixed && old.Recipe == recipeId), ManualLab = old != null && old.ManualLab };
                manual.Remove(target); automatic.Remove(target);
                ClearStock(target);
            }
            else if (kind == "flow_reset") { machines.Remove(target); manual.Remove(target); automatic.Remove(target); ClearStock(target);
                lines.Remove(target); miners.Remove(target); produced.Remove(target); }
            else if (kind == "flow_transfer")
            {
                if (version >= 3) return;
                int item = Number(e, "item_id"), count = Number(e, "count"), before = Number(e, "source_before");
                string source = (string)e["source"];
                var key = Tuple.Create(source, item);
                long trusted = Math.Min(Get(stock, key), before);
                long moved = Math.Max(0, count - Math.Max(0, before - trusted));
                // Mixed stacks have no per-item identity; retain only the provable lower bound.
                stock[key] = Math.Max(0, trusted - count);
                if ((item == 1001 || item == 1002) && source.StartsWith("m:") && target.StartsWith("s:")) moved = 0;
                if (target.StartsWith("m:"))
                {
                    if (!machines.TryGetValue(target, out Machine m) || !m.Requires.Contains(item)) return;
                    long credit = source.StartsWith("s:") ? moved : 0;
                    m.Inputs[item] = Get(m.Inputs, item) + credit;
                    if (credit > 0) m.Delivered.Add(item);
                    if (m.Product == 6001 && credit < count) m.ManualLab = true;
                    if (m.Product == 6001 && m.Fixed && !m.ManualLab && m.Delivered.IsSupersetOf(new[] { 1202, 1301 })) done[15] = 1;
                }
                else
                {
                    key = Tuple.Create(target, item);
                    stock[key] = Get(stock, key) + moved;
                }
            }
            else if (kind == "miner_stock")
            {
                int item = Number(e, "item_id");
                bool valid = (item == 1001 || item == 1002) && item == Number(e, "vein_item_id") &&
                    Convert.ToDouble(e["power"]) >= 0.1 && Number(e, "network_id") > 0 && Number(e, "proto_id") == 2301;
                stock[Tuple.Create(target, item)] = valid ? Number(e, "count") : 0;
                miners[target] = valid ? item : 0;
            }
            else if ((kind == "machine_manual" || kind == "manual_inventory") && machines.TryGetValue(target, out Machine manualMachine))
            {
                if (version >= 3) return;
                bool inserted;
                if (kind == "manual_inventory")
                {
                    int[] before = Numbers(e, "before"), after = Numbers(e, "after");
                    int width = Math.Max(before.Length, after.Length);
                    Array.Resize(ref before, width); Array.Resize(ref after, width);
                    if (before.SequenceEqual(after)) return;
                    inserted = Enumerable.Range(0, width).Any(i => after[i] > before[i]);
                }
                else inserted = (bool)e["inserted"]; // Preserve legacy recorded claims.
                manualMachine.Inputs.Clear();
                if (manualMachine.Product == 6001 && inserted) manualMachine.ManualLab = true;
            }
            else if (kind == "machine_step" && machines.TryGetValue(target, out Machine m))
            {
                int product = m.Product, cycles = Number(e, "cycles");
                bool connected = version >= 3 && Connected(target);
                if (connected && product == 6001) done[15] = 1;
                var key = Tuple.Create(target, product);
                stock[key] = Math.Min(Get(stock, key), Number(e, "output_before"));
                if (cycles > 0)
                {
                    if (m.Fixed && m.PendingManual && (product == 1101 || product == 1102 || product == 1104) && !(bool)e["auto_input"])
                    {
                        manual[target] = product;
                        if (new[] { 1101, 1102, 1104 }.All(manual.Values.Contains)) done[9] = 1;
                    }
                    if (m.Fixed && m.Pending && !m.ManualLab && (version < 3 || connected))
                    {
                        produced.Add(target);
                        stock[key] += (long)cycles * m.Batch;
                        if (product == 1101 || product == 1102 || product == 1104)
                        {
                            automatic[target] = product;
                            if (new[] { 1101, 1102, 1104 }.All(automatic.Values.Contains)) done[11] = 1;
                        }
                        else if (product == 1202 || product == 1301) done[product == 1202 ? 13 : 14] = 1;
                        else if (product == 6001) done[22] = 1;
                    }
                    m.Pending = false;
                    m.PendingManual = false;
                }
                int[] before = Numbers(e, "before"), after = Numbers(e, "after");
                if (Enumerable.Range(0, before.Length).Any(i => after[i] < before[i]))
                {
                    bool eligible = m.Fixed && !m.ManualLab;
                    for (int i = 0; i < before.Length; i++)
                    {
                        long credit = Math.Min(Get(m.Inputs, m.Requires[i]), before[i]);
                        eligible &= before[i] - after[i] == m.Counts[i] && credit == before[i];
                        m.Inputs[m.Requires[i]] = Math.Max(0, credit - (before[i] - after[i]));
                    }
                    m.Pending = version >= 3 ? connected : eligible;
                    m.PendingManual = !(bool)e["auto_input"];
                }
                else for (int i = 0; i < before.Length; i++) m.Inputs[m.Requires[i]] = Math.Min(Get(m.Inputs, m.Requires[i]), before[i]);
            }
        }
    }
}
