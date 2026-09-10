using System;
using System.Collections.Generic;
using System.Linq;

namespace DSPDreamer.Recorder
{
    // Current native connections, independent of the contents of machine buffers.
    internal static class ProductionConnections
    {
        private static readonly Dictionary<string, string> lastSignatures = new Dictionary<string, string>();
        internal static void Reset() { lock (lastSignatures) lastSignatures.Clear(); }
        internal static void Forget(string key) { lock (lastSignatures) lastSignatures.Remove(key); }
        private static bool Powered(PlanetFactory factory, int entity)
        {
            int consumer = factory.entityPool[entity].powerConId;
            if (consumer <= 0) return false;
            int network = factory.powerSystem.consumerPool[consumer].networkId;
            return network > 0 && factory.powerSystem.netPool[network].consumerRatio >= 0.1;
        }

        internal static void Capture(PlanetFactory factory, int entity)
        {
            lock (lastSignatures) CaptureTree(factory, entity, new HashSet<int>());
        }
        private static void CaptureTree(PlanetFactory factory, int entity, HashSet<int> visited)
        {
            if (entity <= 0 || !visited.Add(entity)) return;
            var data = factory.entityPool[entity];
            if (data.id != entity) return;
            string key = ProductionCapture.Key("m", factory, entity);
            if (data.minerId > 0)
            {
                var miner = factory.factorySystem.minerPool[data.minerId];
                int ore = miner.type == EMinerType.Vein && miner.veinCount > 0 &&
                    factory.veinPool[miner.veins[miner.currentVeinIndex]].amount > 0 ?
                    factory.veinPool[miner.veins[miner.currentVeinIndex]].productId : 0;
                bool powered = Powered(factory, entity);
                string state = ore + ":" + powered;
                if (lastSignatures.TryGetValue(key, out string old) && old == state) return;
                lastSignatures[key] = state;
                ProductionCapture.Fact("miner_stock", "target", key, "item_id", ore, "count", miner.productCount,
                    "vein_item_id", ore, "network_id", factory.powerSystem.consumerPool[miner.pcId].networkId,
                    "power", powered ? 1.0 : 0.0, "proto_id", (int)data.protoId);
                return;
            }
            RecipeExecuteData recipe = data.assemblerId > 0 ? factory.factorySystem.assemblerPool[data.assemblerId].recipeExecuteData :
                data.labId > 0 && !factory.factorySystem.labPool[data.labId].researchMode ? factory.factorySystem.labPool[data.labId].recipeExecuteData : null;
            if (recipe == null) return;
            ProductionCapture.Configure(factory, entity);
            var sources = new List<string>();
            var items = new List<int>();
            var belts = new List<int>();
            foreach (int item in recipe.requires)
            {
                var found = new Dictionary<int, bool>();
                FindSources(factory, entity, item, false, false, new HashSet<long>(), found);
                foreach (var source in found.OrderBy(p => p.Key))
                {
                    CaptureTree(factory, source.Key, visited);
                    sources.Add(ProductionCapture.Key("m", factory, source.Key));
                    items.Add(item); belts.Add(source.Value ? 1 : 0);
                }
            }
            bool hasPower = Powered(factory, entity);
            string signature = hasPower + "|" + string.Join(",", sources.Zip(items, (s, i) => s + ":" + i)) + "|" + string.Join(",", belts);
            if (lastSignatures.TryGetValue(key, out string previous) && previous == signature) return;
            lastSignatures[key] = signature;
            ProductionCapture.Fact("line_state", "target", key, "powered", hasPower,
                "sources", sources.ToArray(), "items", items.ToArray(), "belts", belts.ToArray());
        }

        private static void FindSources(PlanetFactory factory, int entity, int item, bool viaBelt, bool acceptMachine,
            HashSet<long> visited, Dictionary<int, bool> found)
        {
            if (entity <= 0 || !visited.Add(2L * entity + (viaBelt ? 1 : 0))) return;
            var data = factory.entityPool[entity];
            if (data.id != entity) return;
            var system = factory.factorySystem;
            if (acceptMachine && (data.minerId > 0 || data.assemblerId > 0))
            {
                int product = data.minerId > 0 ? system.minerPool[data.minerId].productId :
                    system.assemblerPool[data.assemblerId].recipeExecuteData?.products.FirstOrDefault() ?? 0;
                if (product == item) found[entity] = viaBelt || found.TryGetValue(entity, out bool prior) && prior;
                return;
            }
            if (data.beltId > 0)
            {
                viaBelt = true;
                var belt = factory.cargoTraffic.beltPool[data.beltId];
                foreach (int input in new[] { belt.backInputId, belt.leftInputId, belt.rightInputId })
                    if (input > 0 && factory.cargoTraffic.beltPool[input].outputId == belt.id)
                        FindSources(factory, factory.cargoTraffic.beltPool[input].entityId, item, true, true, visited, found);
                for (int i = 1; i < system.minerCursor; i++)
                    if (system.minerPool[i].id == i && system.minerPool[i].insertTarget == entity)
                        FindSources(factory, system.minerPool[i].entityId, item, true, true, visited, found);
            }
            // ponytail: scan early-game inserters per reachable belt; index incoming edges if #21 profiling requires it.
            for (int i = 1; i < system.inserterCursor; i++)
            {
                var sorter = system.inserterPool[i];
                if (sorter.id == i && sorter.insertTarget == entity && !sorter.bidirectional &&
                    (sorter.filter == 0 || sorter.filter == item) && Powered(factory, sorter.entityId))
                    FindSources(factory, sorter.pickTarget, item, viaBelt, true, visited, found);
            }
        }
    }
}
