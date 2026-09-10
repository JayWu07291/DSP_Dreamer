using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;

namespace DSPDreamer.Recorder
{
    // Pure fact replay, also compiled into the evidence integration check.
    internal sealed class TaskProgress
    {
        internal static readonly int[][] Dependencies = {
            new int[0], new[] { 0 }, new[] { 16 }, new[] { 16 }, new[] { 16 },
            new[] { 17 }, new[] { 17 }, new[] { 17 }, new[] { 18 }, new[] { 18, 6, 4 },
            new[] { 19 }, new[] { 9, 19, 6, 7 }, new[] { 20 }, new[] { 11, 20 },
            new[] { 11, 20 }, new[] { 13, 14, 21 }
        };
        internal readonly int[] Done = new int[23];
        internal int Active;
        internal int PreviousTask, Reward;
        internal int[] RewardVector = new int[16], Completions = new int[0];
        private int[] observed = new int[23];
        private readonly int[] techIds;
        private readonly int version;
        private readonly ProductionProgress production;
        private long coils, boards, copper, landerFuel, foreignFuel;

        internal TaskProgress(int[] techIds, int version = 1)
        { this.techIds = techIds; this.version = version; production = new ProductionProgress(Done); }
        private static int Number(Dictionary<string, object> e, string name) => Convert.ToInt32(e[name]);
        private static int[] Numbers(Dictionary<string, object> e, string name) =>
            ((IEnumerable)e[name]).Cast<object>().Select(Convert.ToInt32).ToArray();

        internal void Apply(Dictionary<string, object> e)
        {
            string kind = (string)e["kind"];
            if (version == 2) production.Apply(e);
            if (kind == "lander_work" && Number(e, "work_ticks") > 0) Done[0] = 1;
            else if (kind == "lander_removed") Done[16] = 1;
            else if (kind == "research_queue" && Numbers(e, "tech_ids").Take(5).SequenceEqual(techIds)) Done[1] = 1;
            else if (kind == "craft_queued" && Done[16] == 1)
            {
                int[] items = Numbers(e, "item_ids"), counts = Numbers(e, "item_counts");
                for (int i = 0; i < items.Length; i++)
                {
                    if (items[i] == 1202) coils += counts[i];
                    else if (items[i] == 1301) boards += counts[i];
                }
                if (coils >= 10 && boards >= 10) Done[2] = 1;
            }
            else if (kind == "item_received")
            {
                if ((string)e["origin"] == "lander" && Number(e, "item_id") == 1801) landerFuel += Number(e, "count");
                if ((string)e["origin"] != "lander" && Number(e, "item_id") == 1801) foreignFuel += Number(e, "count");
                if ((string)e["origin"] == "manual" && Number(e, "item_id") == 1002 && Done[16] == 1)
                {
                    copper += Number(e, "count");
                    if (copper >= 4) Done[4] = 1;
                }
            }
            else if (kind == "fuel_inserted" && Done[16] == 1 && Number(e, "item_id") == 1801)
            {
                // Other-source receipts/production are an upper bound, never spent by repeated transfers.
                if (landerFuel > 0 && Number(e, "count") > 0 && Number(e, "reactor_count") > foreignFuel) Done[3] = 1;
            }
            else if (kind == "foreign_fuel_produced") foreignFuel += Number(e, "count");
            else if (kind == "tech_state" && (bool)e["unlocked"])
            {
                int index = Array.IndexOf(techIds, Number(e, "tech_id"));
                if (index == 0 || version == 2 && index > 0) Done[17 + index] = 1;
            }
            else if (version == 2 && kind == "research_supply")
            {
                int index = Array.IndexOf(techIds, Number(e, "tech_id"));
                int[] points = Numbers(e, "item_points"), buffered = Numbers(e, "buffered_points");
                long remaining = Convert.ToInt64(e["remaining_hash"]);
                if (index > 0 && remaining > 0 && points.Length > 0 &&
                    Enumerable.Range(0, points.Length).All(i => buffered[i] >= remaining * points[i]))
                    Done[new[] { 0, 5, 8, 10, 12 }[index]] = 1;
            }
            else if (kind == "miner_output")
            {
                int item = Number(e, "item_id");
                if ((item == 1001 || item == 1002) && item == Number(e, "vein_item_id") && Number(e, "count") > 0 &&
                    Convert.ToDouble(e["power"]) >= 0.1 && Number(e, "network_id") > 0 && Number(e, "entity_id") > 0 &&
                    Number(e, "proto_id") == 2301) Done[item == 1001 ? 6 : 7] = 1;
            }
        }

        internal void Observe()
        {
            PreviousTask = Active;
            Completions = Enumerable.Range(0, 23).Where(i => Done[i] > observed[i]).ToArray();
            RewardVector = Enumerable.Range(0, 16).Select(i => Done[i] - observed[i]).ToArray();
            Reward = Active < 16 ? RewardVector[Active] : 0;
            observed = (int[])Done.Clone();
            if (Active != 16 && Done[Active] == 0) return;
            Active = 16;
            for (int i = 0; i < 16; i++)
                if (Done[i] == 0 && Dependencies[i].All(d => Done[d] == 1)) { Active = i; break; }
        }
    }
}
