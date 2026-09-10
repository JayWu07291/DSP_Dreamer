using HarmonyLib;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;

namespace DSPDreamer.Recorder
{
    public sealed partial class RecorderPlugin
    {
        private readonly object progressGate = new object();
        private readonly Queue<Dictionary<string, object>> progressFacts = new Queue<Dictionary<string, object>>();
        private TaskProgress progress;
        private int[] progressTechIds;
        private long progressBoundary;
        private int reactorFuel;
        private StorageComponent reactor;
        internal bool ProgressEnabled => active && perturbed && episode != null &&
            (episode["start_ticks"] != null || firstPending) && episode["end_ticks"] == null;

        private void PrepareProgress()
        {
            int[][] rewards = { new[] { 2301, 1, 2203, 1 }, new[] { 2302, 3 },
                new[] { 2001, 20, 2011, 5 }, new[] { 2303, 1 }, new[] { 2901, 1 } };
            progressTechIds = rewards.Select(pairs => LDB.techs.dataArray.Single(tech =>
                Enumerable.Range(0, pairs.Length / 2).All(i => tech.AddItems != null &&
                    Enumerable.Range(0, tech.AddItems.Length).Any(j => tech.AddItems[j] == pairs[i * 2] &&
                        tech.AddItemCounts[j] == pairs[i * 2 + 1]))).ID).ToArray();
            var player = GameMain.mainPlayer;
            var factory = player.factory;
            if (Enumerable.Range(1, factory.vegeCursor - 1).Count(i => factory.vegePool[i].id == i &&
                    factory.vegePool[i].protoId == 9999) != 1 ||
                progressTechIds.Any(GameMain.history.TechUnlocked) || GameMain.history.techQueueLength != 0 ||
                player.mecha.forge.tasks.Count != 0 || player.package.GetItemCount(1801) != 0 ||
                player.mecha.reactorStorage.GetItemCount(1801) != 0 || player.mecha.reactorItemId == 1801 ||
                player.inhandItemId == 1801 || player.deliveryPackage.grids.Any(g => g.itemId == 1801 && g.count > 0) ||
                factory.entityCount != 0)
                throw new InvalidOperationException("早期進度基準不符：須保留登陸艙、空科技／製作佇列且未取得液氫燃料棒。");
            lock (progressGate)
            {
                progressFacts.Clear();
                progress = new TaskProgress(progressTechIds);
                progressBoundary = 0;
            }
            metadata["progress_version"] = 1;
            metadata["progress_tech_ids"] = progressTechIds;
            reactor = player.mecha.reactorStorage;
            reactorFuel = reactor.GetItemCount(1801);
            reactor.onStorageChange += ReactorChanged;
        }

        private void ReactorChanged()
        {
            int count = reactor.GetItemCount(1801);
            if (count > reactorFuel) RecordProgressFact("fuel_inserted", Json.Fields("item_id", 1801, "count", count - reactorFuel,
                "reactor_count", count + (GameMain.mainPlayer.mecha.reactorItemId == 1801 ? 1 : 0)));
            reactorFuel = count;
        }

        internal void RecordProgressFact(string kind, Dictionary<string, object> fields = null)
        {
            lock (progressGate)
            {
                if (!ProgressEnabled) return;
                if (progressFacts.Count >= 4096) { failed = true; return; }
                fields = fields ?? Json.Fields();
                fields["kind"] = kind;
                fields["ticks"] = Math.Max(Stopwatch.GetTimestamp(), progressBoundary);
                fields["episode_id"] = episode["episode_id"];
                progressFacts.Enqueue(fields);
            }
        }

        private void DrainProgress()
        {
            // Caller holds progressGate. Worker-thread hooks never access Unity logging or event identities.
            while (progressFacts.Count > 0)
            {
                var fact = progressFacts.Dequeue();
                progress.Apply(fact);
                fact["name"] = "progress_fact";
                Emit("game_event", fact);
            }
        }

        private long CaptureProgress(long captureId)
        {
            lock (progressGate)
            {
                DrainProgress();
                progress.Observe();
                // A fact observed before this request must be strictly inside the preceding half-open interval.
                progressBoundary = Stopwatch.GetTimestamp() + 1;
                Emit("game_event", Json.Fields("name", "progress_observation", "ticks", progressBoundary,
                    "capture_id", captureId, "task_id", progress.Active, "node_completed", (int[])progress.Done.Clone(),
                    "previous_task_id", progress.PreviousTask, "reward_vector", progress.RewardVector,
                    "reward", progress.Reward, "node_completions", progress.Completions));
                return progressBoundary;
            }
        }

        private void UnbindProgress()
        {
            if (reactor != null) reactor.onStorageChange -= ReactorChanged;
            reactor = null;
        }
    }

    [HarmonyPatch(typeof(PlayerAction_Mine), nameof(PlayerAction_Mine.GameTick))]
    internal static class ProgressMiningPatch
    {
        [ThreadStatic] internal static PlayerAction_Mine Mining;
        private static void Prefix(PlayerAction_Mine __instance) { Mining = __instance; }
        private static void Postfix(PlayerAction_Mine __instance)
        {
            if (__instance.miningType == EObjectType.Vegetable && __instance.miningProtoId == 9999 && __instance.miningTick > 0)
                RecorderPlugin.Current?.RecordProgressFact("lander_work", Json.Fields("work_ticks", __instance.miningTick));
        }
        private static void Finalizer() { Mining = null; }
    }

    [HarmonyPatch(typeof(Player), nameof(Player.TryAddItemToPackage))]
    internal static class ProgressReceivedPatch
    {
        private static void Postfix(Player __instance, int itemId, int __result)
        {
            if (__result <= 0 || __instance != GameMain.mainPlayer) return;
            var mining = ProgressMiningPatch.Mining;
            string origin = mining == null ? "other" : mining.miningType == EObjectType.Vegetable &&
                mining.miningProtoId == 9999 ? "lander" : mining.miningType == EObjectType.Vein ? "manual" : "other";
            RecorderPlugin.Current?.RecordProgressFact("item_received", Json.Fields("origin", origin, "item_id", itemId, "count", __result));
        }
    }

    [HarmonyPatch(typeof(PlanetFactory), nameof(PlanetFactory.RemoveVegeWithComponents))]
    internal static class ProgressLanderPatch
    {
        private static void Prefix(PlanetFactory __instance, int id, out bool __state)
        {
            var mining = ProgressMiningPatch.Mining;
            __state = mining != null && mining.miningType == EObjectType.Vegetable && mining.miningId == id &&
                __instance.vegePool[id].id == id && __instance.vegePool[id].protoId == 9999;
        }
        private static void Postfix(PlanetFactory __instance, int id, bool __state)
        {
            if (__state && __instance.vegePool[id].id == 0) RecorderPlugin.Current?.RecordProgressFact("lander_removed");
        }
    }

    [HarmonyPatch(typeof(GameHistoryData), nameof(GameHistoryData.EnqueueTech))]
    internal static class ProgressResearchPatch
    {
        private static void Postfix(GameHistoryData __instance)
        {
            RecorderPlugin.Current?.RecordProgressFact("research_queue", Json.Fields("tech_ids", (int[])__instance.techQueue.Clone()));
        }
    }

    [HarmonyPatch(typeof(MechaForge), nameof(MechaForge.AddTask))]
    internal static class ProgressCraftPatch
    {
        private static void Postfix(int count, ForgeTask __result)
        {
            if (__result != null)
                RecorderPlugin.Current?.RecordProgressFact("craft_queued", Json.Fields("item_ids", (int[])__result.productIds.Clone(),
                    "item_counts", __result.productCounts.Select(c => checked(c * count)).ToArray()));
        }
    }

    [HarmonyPatch(typeof(MinerComponent), nameof(MinerComponent.InternalUpdate))]
    internal static class ProgressMinerPatch
    {
        internal sealed class Sample
        {
            internal int Before, Item, Network;
            internal int[] Register;
            internal VeinData[] Veins;
            internal bool RegisterLocked;
        }
        private static void Prefix(ref MinerComponent __instance, PlanetFactory factory, int[] productRegister, out Sample __state)
        {
            __state = null;
            if (RecorderPlugin.Current == null || !RecorderPlugin.Current.ProgressEnabled ||
                __instance.type != EMinerType.Vein || __instance.veinCount == 0) return;
            var sample = new Sample { Register = productRegister, Veins = factory.veinPool };
            // Match the game's veinPool -> productRegister lock order, including the pre-update vein snapshot.
            Monitor.Enter(sample.Veins);
            __state = sample;
            if (__instance.veinCount == 0) return;
            int item = sample.Veins[__instance.veins[__instance.currentVeinIndex]].productId;
            if (item != 1001 && item != 1002) return;
            sample.Item = item;
            sample.Network = factory.powerSystem.consumerPool[__instance.pcId].networkId;
            // ponytail: serialize a factory's production register while sampling; use a local production hook if profiling requires it.
            Monitor.Enter(productRegister);
            sample.RegisterLocked = true;
            sample.Before = productRegister[item];
        }
        private static void Postfix(ref MinerComponent __instance, PlanetFactory factory, float power, Sample __state)
        {
            if (__state == null || !__state.RegisterLocked) return;
            int count = __state.Register[__state.Item] - __state.Before;
            if (count > 0)
                RecorderPlugin.Current?.RecordProgressFact("miner_output", Json.Fields("item_id", __state.Item, "count", count,
                    "vein_item_id", __state.Item, "power", power, "network_id", __state.Network, "entity_id", __instance.entityId,
                    "factory_index", factory.index, "proto_id", (int)factory.entityPool[__instance.entityId].protoId));
        }
        private static void Finalizer(Sample __state)
        {
            if (__state == null) return;
            if (__state.RegisterLocked) Monitor.Exit(__state.Register);
            Monitor.Exit(__state.Veins);
        }
    }

    [HarmonyPatch(typeof(AssemblerComponent), nameof(AssemblerComponent.InternalUpdate))]
    internal static class ProgressForeignFuelPatch
    {
        internal struct Sample { internal int Cycles, Extra, PerCycle; }
        private static void Prefix(ref AssemblerComponent __instance, out Sample __state)
        {
            __state = default(Sample);
            if (RecorderPlugin.Current == null || !RecorderPlugin.Current.ProgressEnabled || __instance.recipeExecuteData == null) return;
            int index = Array.IndexOf(__instance.recipeExecuteData.products, 1801);
            if (index < 0) return;
            __state = new Sample { Cycles = __instance.cycleCount, Extra = __instance.extraCycleCount,
                PerCycle = __instance.recipeExecuteData.productCounts[index] };
        }
        private static void Postfix(ref AssemblerComponent __instance, Sample __state)
        {
            if (__state.PerCycle == 0) return;
            int cycles = unchecked(__instance.cycleCount - __state.Cycles + __instance.extraCycleCount - __state.Extra);
            if (cycles > 0) RecorderPlugin.Current?.RecordProgressFact("foreign_fuel_produced", Json.Fields("count", checked(cycles * __state.PerCycle)));
        }
    }
}
