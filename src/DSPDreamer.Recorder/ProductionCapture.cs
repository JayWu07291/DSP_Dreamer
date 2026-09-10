using HarmonyLib;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace DSPDreamer.Recorder
{
    // Hooks retain native cargo IDs through belts; no topology-based guesses about item origins.
    internal static class ProductionCapture
    {
        internal sealed class Transport
        {
            internal PlanetFactory Factory;
            internal int Sorter, Miner;
            internal float Power;
            internal bool HadItems;
        }
        internal sealed class Sample
        {
            internal PlanetFactory Factory;
            internal int Entity, Cycles, Output;
            internal int[] Before;
        }
        [ThreadStatic] internal static Transport Moving;
        private static readonly object gate = new object();
        private static readonly Dictionary<string, int> recipes = new Dictionary<string, int>();
        private static readonly Dictionary<string, int[]> lastInputs = new Dictionary<string, int[]>();
        private static readonly Dictionary<string, int> lastOutputs = new Dictionary<string, int>();
        internal static bool Enabled => RecorderPlugin.Current != null && RecorderPlugin.Current.ProgressEnabled;
        internal static string Key(string type, PlanetFactory factory, int id) => type + ":" + factory.index + ":" + id;
        internal static void Fact(string kind, params object[] fields) => RecorderPlugin.Current?.RecordProgressFact(kind, Json.Fields(fields));
        internal static void Reset() { lock (gate) { recipes.Clear(); lastInputs.Clear(); lastOutputs.Clear(); } }
        internal static void Forget(PlanetFactory factory, int entity)
        {
            string key = Key("m", factory, entity);
            lock (gate) { recipes.Remove(key); lastInputs.Remove(key); lastOutputs.Remove(key); }
        }
        internal static PlanetFactory FindFactory(object array, bool signs = false)
        {
            // ponytail: linear owner lookup for the early single-planet scene; cache ownership if #21 profiling requires it.
            var data = GameMain.data;
            if (data == null) return null;
            for (int i = 0; i < data.factoryCount; i++)
            {
                var factory = data.factories[i];
                if (ReferenceEquals(signs ? (object)factory.entitySignPool : GameMain.statistics.production.factoryStatPool[i].productRegister, array))
                    return factory;
            }
            return null;
        }
        internal static PlanetFactory CargoFactory(CargoContainer container)
        {
            if (Moving != null && Moving.Factory.cargoTraffic.container == container) return Moving.Factory;
            var data = GameMain.data;
            for (int i = 0; data != null && i < data.factoryCount; i++)
                if (data.factories[i].cargoTraffic.container == container) return data.factories[i];
            return null;
        }
        internal static void Configure(PlanetFactory factory, int entity, bool reset = false)
        {
            if (!Enabled || factory == null || entity <= 0 || factory.entityPool[entity].id != entity) return;
            var data = factory.entityPool[entity];
            int recipeId;
            RecipeExecuteData recipe;
            if (data.assemblerId > 0)
            {
                var machine = factory.factorySystem.assemblerPool[data.assemblerId];
                recipeId = machine.recipeId; recipe = machine.recipeExecuteData;
            }
            else if (data.labId > 0)
            {
                var machine = factory.factorySystem.labPool[data.labId];
                recipeId = machine.researchMode ? 0 : machine.recipeId; recipe = machine.researchMode ? null : machine.recipeExecuteData;
            }
            else return;
            string key = Key("m", factory, entity);
            lock (gate)
            {
                if (!reset && recipes.TryGetValue(key, out int old) && old == recipeId) return;
                if (recipeId == 0 && !recipes.ContainsKey(key)) return;
                recipes[key] = recipeId;
                lastInputs.Remove(key);
                lastOutputs.Remove(key);
                Fact("machine_config", "target", key, "recipe_id", recipeId, "proto_id", (int)data.protoId,
                    "product", recipe?.products.Length == 1 ? recipe.products[0] : 0,
                    "batch_size", recipe?.products.Length == 1 ? recipe.productCounts[0] : 0,
                    "requires", recipe == null ? new int[0] : (int[])recipe.requires.Clone(),
                    "counts", recipe == null ? new int[0] : (int[])recipe.requireCounts.Clone());
            }
        }
        internal static Sample Before(int entity, int cycles, int[] served, int[] produced, int[] register)
        {
            if (!Enabled || served == null || produced == null || produced.Length != 1) return null;
            var factory = FindFactory(register);
            if (factory == null) return null;
            Configure(factory, entity);
            return new Sample { Factory = factory, Entity = entity, Cycles = cycles,
                Output = produced[0], Before = (int[])served.Clone() };
        }
        internal static void After(Sample sample, int cycles, int[] served, int[] produced)
        {
            if (sample == null || !Enabled) return;
            string key = Key("m", sample.Factory, sample.Entity);
            int completed = unchecked(cycles - sample.Cycles);
            lock (gate)
            {
                bool changed = !sample.Before.SequenceEqual(served) || !lastInputs.TryGetValue(key, out int[] last) ||
                    !last.SequenceEqual(sample.Before) || sample.Output != produced[0] ||
                    !lastOutputs.TryGetValue(key, out int lastOutput) || lastOutput != sample.Output;
                if (!changed && completed == 0) return;
                lastInputs[key] = (int[])served.Clone();
                lastOutputs[key] = produced[0];
            }
            var system = sample.Factory.factorySystem;
            bool automatic = false;
            for (int i = 1; i < system.inserterCursor; i++)
                if (system.inserterPool[i].id == i && system.inserterPool[i].insertTarget == sample.Entity) { automatic = true; break; }
            Fact("machine_step", "target", key, "before", sample.Before, "after", (int[])served.Clone(),
                "cycles", completed, "output_before", sample.Output, "auto_input", automatic);
        }
        internal static int[] Inputs(PlanetFactory factory, int entity)
        {
            Configure(factory, entity);
            var data = factory.entityPool[entity];
            int[] inputs = data.assemblerId > 0 ? factory.factorySystem.assemblerPool[data.assemblerId].served :
                data.labId > 0 ? factory.factorySystem.labPool[data.labId].served : null;
            return inputs == null ? new int[0] : (int[])inputs.Clone();
        }
        internal static void Manual(PlanetFactory factory, int entity, int[] before)
        {
            if (!Enabled || before == null) return;
            int[] after = Inputs(factory, entity);
            if (before.SequenceEqual(after)) return;
            Fact("machine_manual", "target", Key("m", factory, entity),
                "inserted", after.Where((value, i) => i >= before.Length || value > before[i]).Any());
        }
        internal static void Transfer(string source, string target, int item, int count, int before)
        {
            if (Moving != null && count > 0 && (source.StartsWith("s:") || target.StartsWith("s:"))) Moving.HadItems = true;
            if (count > 0) Fact("flow_transfer", "source", source, "target", target,
                "item_id", item, "count", count, "source_before", before);
        }
        internal static string Source(out int before)
        {
            before = 0;
            if (Moving == null) return "unknown";
            var system = Moving.Factory.factorySystem;
            if (Moving.Sorter > 0)
            {
                var sorter = system.inserterPool[Moving.Sorter];
                before = sorter.itemCount;
                return Key("s", Moving.Factory, sorter.entityId);
            }
            if (Moving.Miner > 0)
            {
                var miner = system.minerPool[Moving.Miner];
                before = miner.productCount;
                int network = Moving.Factory.powerSystem.consumerPool[miner.pcId].networkId;
                int veinItem = miner.type == EMinerType.Vein && miner.veinCount > 0 ?
                    Moving.Factory.veinPool[miner.veins[miner.currentVeinIndex]].productId : 0;
                string key = Key("m", Moving.Factory, miner.entityId);
                Fact("miner_stock", "target", key, "item_id", miner.productId, "count", before,
                    "vein_item_id", veinItem, "network_id", network, "power", Moving.Power,
                    "proto_id", (int)Moving.Factory.entityPool[miner.entityId].protoId);
                return key;
            }
            return "unknown";
        }
        internal static int Entity(PlanetFactory factory, uint target)
        {
            int id = (int)(target & 0xffffff);
            switch ((EFactoryIOTargetType)(target & 0xff000000))
            {
                case EFactoryIOTargetType.Assembler: return factory.factorySystem.assemblerPool[id].entityId;
                case EFactoryIOTargetType.Lab: return factory.factorySystem.labPool[id].entityId;
                default: return 0;
            }
        }
    }

    [HarmonyPatch(typeof(MechaLab), nameof(MechaLab.ManageSupply))]
    internal static class ProgressSupplyPatch
    {
        private static void Postfix(MechaLab __instance, TechProto techProto)
        {
            if (!ProductionCapture.Enabled) return;
            var state = __instance.gameHistory.TechState(techProto.ID);
            long remaining = state.hashNeeded - state.hashUploaded;
            int[] buffered = techProto.Items.Select(__instance.itemPoints.GetCount).ToArray();
            // Record the actual remaining obligation and buffer, once the whole obligation fits.
            if (remaining > 0 && Enumerable.Range(0, buffered.Length).All(i => buffered[i] >= remaining * techProto.ItemPoints[i]))
                RecorderPlugin.Current.RecordResearchSupply(techProto, remaining, buffered);
        }
    }

    [HarmonyPatch(typeof(AssemblerComponent), nameof(AssemblerComponent.InternalUpdate))]
    internal static class ProgressAssemblyPatch
    {
        private static void Prefix(ref AssemblerComponent __instance, int[] productRegister, out ProductionCapture.Sample __state) =>
            __state = ProductionCapture.Before(__instance.entityId, __instance.cycleCount, __instance.served, __instance.produced, productRegister);
        private static void Postfix(ref AssemblerComponent __instance, ProductionCapture.Sample __state) =>
            ProductionCapture.After(__state, __instance.cycleCount, __instance.served, __instance.produced);
    }
    [HarmonyPatch(typeof(LabComponent), nameof(LabComponent.InternalUpdateAssemble))]
    internal static class ProgressLabProductionPatch
    {
        private static void Prefix(ref LabComponent __instance, int[] productRegister, out ProductionCapture.Sample __state) =>
            __state = ProductionCapture.Before(__instance.entityId, __instance.cycleCount, __instance.served, __instance.produced, productRegister);
        private static void Postfix(ref LabComponent __instance, ProductionCapture.Sample __state) =>
            ProductionCapture.After(__state, __instance.cycleCount, __instance.served, __instance.produced);
    }
    [HarmonyPatch(typeof(AssemblerComponent), nameof(AssemblerComponent.SetRecipe))]
    internal static class ProgressRecipePatch
    {
        private static void Postfix(ref AssemblerComponent __instance, SignData[] signPool) =>
            ProductionCapture.Configure(ProductionCapture.FindFactory(signPool, true), __instance.entityId, true);
    }
    [HarmonyPatch(typeof(LabComponent), nameof(LabComponent.SetFunction))]
    internal static class ProgressLabRecipePatch
    {
        private static void Postfix(ref LabComponent __instance, SignData[] _signPool) =>
            ProductionCapture.Configure(ProductionCapture.FindFactory(_signPool, true), __instance.entityId, true);
    }
    [HarmonyPatch]
    internal static class ProgressSorterPatch
    {
        private static IEnumerable<MethodBase> TargetMethods() => new[] { "InternalUpdate", "InternalUpdateNoAnim", "InternalUpdate_Bidirectional" }
            .Select(name => AccessTools.Method(typeof(InserterComponent), name));
        private static void Prefix(ref InserterComponent __instance, PlanetFactory factory, out ProductionCapture.Transport __state)
        {
            __state = ProductionCapture.Moving;
            if (ProductionCapture.Enabled) ProductionCapture.Moving = new ProductionCapture.Transport {
                Factory = factory, Sorter = __instance.id, HadItems = __instance.itemCount > 0 };
        }
        private static void Finalizer(ProductionCapture.Transport __state) { ProductionCapture.Moving = __state; }
        private static void Postfix(ref InserterComponent __instance, PlanetFactory factory)
        {
            if (ProductionCapture.Enabled && ProductionCapture.Moving.HadItems && __instance.itemCount == 0)
                ProductionCapture.Fact("flow_reset", "target", ProductionCapture.Key("s", factory, __instance.entityId));
        }
    }
    [HarmonyPatch(typeof(MinerComponent), nameof(MinerComponent.InternalUpdate))]
    internal static class ProgressMinerTransportPatch
    {
        private static void Prefix(ref MinerComponent __instance, PlanetFactory factory, float power, out ProductionCapture.Transport __state)
        {
            __state = ProductionCapture.Moving;
            if (ProductionCapture.Enabled) ProductionCapture.Moving = new ProductionCapture.Transport { Factory = factory, Miner = __instance.id, Power = power };
        }
        private static void Finalizer(ProductionCapture.Transport __state) { ProductionCapture.Moving = __state; }
    }
    [HarmonyPatch]
    internal static class ProgressCargoCreatedPatch
    {
        private static IEnumerable<MethodBase> TargetMethods() => AccessTools.GetDeclaredMethods(typeof(CargoContainer)).Where(m => m.Name == "AddCargo");
        private static void Postfix(CargoContainer __instance, short item, byte stack, int __result)
        {
            if (!ProductionCapture.Enabled) return;
            var factory = ProductionCapture.CargoFactory(__instance);
            if (factory == null) return;
            string target = ProductionCapture.Key("c", factory, __result);
            ProductionCapture.Fact("flow_reset", "target", target);
            string source = ProductionCapture.Source(out int before);
            ProductionCapture.Transfer(source, target, item, stack, Math.Max(before, stack));
        }
    }
    [HarmonyPatch(typeof(CargoContainer), nameof(CargoContainer.RemoveCargo))]
    internal static class ProgressCargoRemovedPatch
    {
        private static void Prefix(CargoContainer __instance, int index)
        {
            if (!ProductionCapture.Enabled) return;
            var factory = ProductionCapture.CargoFactory(__instance);
            if (factory == null) return;
            var cargo = __instance.cargoPool[index];
            string target = ProductionCapture.Moving?.Sorter > 0 ?
                ProductionCapture.Key("s", factory, factory.factorySystem.inserterPool[ProductionCapture.Moving.Sorter].entityId) : "discard";
            ProductionCapture.Transfer(ProductionCapture.Key("c", factory, index), target, cargo.item, cargo.stack, cargo.stack);
        }
    }
    [HarmonyPatch(typeof(CargoContainer), nameof(CargoContainer.AddItemStackToCargo))]
    internal static class ProgressCargoStackPatch
    {
        private static void Prefix(CargoContainer __instance, int cargoId)
        {
            if (!ProductionCapture.Enabled) return;
            var factory = ProductionCapture.CargoFactory(__instance);
            if (factory != null)
                // ponytail: merged stacks lose provenance; track per-source stack counts if higher-tier sorters are required.
                ProductionCapture.Fact("flow_reset", "target", ProductionCapture.Key("c", factory, cargoId));
        }
    }
    [HarmonyPatch]
    internal static class ProgressInsertPatch
    {
        private static IEnumerable<MethodBase> TargetMethods() => AccessTools.GetDeclaredMethods(typeof(PlanetFactory)).Where(m => m.Name == "InsertInto");
        private static void Prefix(PlanetFactory __instance, object[] __args, out int __state)
        {
            __state = __args[0] is uint ? ProductionCapture.Entity(__instance, (uint)__args[0]) : (int)__args[0];
            if (ProductionCapture.Enabled && __state > 0) ProductionCapture.Configure(__instance, __state);
        }
        private static void Postfix(PlanetFactory __instance, int itemId, int __result, int __state)
        {
            if (!ProductionCapture.Enabled || __result <= 0 || __state <= 0) return;
            var entity = __instance.entityPool[__state];
            if (entity.assemblerId <= 0 && entity.labId <= 0) return;
            string source = ProductionCapture.Source(out int before);
            ProductionCapture.Transfer(source, ProductionCapture.Key("m", __instance, __state), itemId, __result, Math.Max(before, __result));
        }
    }
    [HarmonyPatch]
    internal static class ProgressPickPatch
    {
        internal sealed class Sample { internal int Entity; internal int[] Products, Counts; }
        private static IEnumerable<MethodBase> TargetMethods() => AccessTools.GetDeclaredMethods(typeof(PlanetFactory)).Where(m => m.Name == "PickFrom");
        private static void Prefix(PlanetFactory __instance, object[] __args, out Sample __state)
        {
            __state = null;
            if (!ProductionCapture.Enabled || ProductionCapture.Moving == null || ProductionCapture.Moving.Sorter <= 0) return;
            int id = __args[0] is uint ? ProductionCapture.Entity(__instance, (uint)__args[0]) : (int)__args[0];
            if (id <= 0) return;
            var entity = __instance.entityPool[id];
            if (entity.assemblerId <= 0) return;
            var machine = __instance.factorySystem.assemblerPool[entity.assemblerId];
            if (machine.recipeExecuteData == null) return;
            __state = new Sample { Entity = id, Products = machine.recipeExecuteData.products, Counts = (int[])machine.produced.Clone() };
        }
        private static void Postfix(PlanetFactory __instance, int __result, byte stack, Sample __state)
        {
            if (__state == null || __result <= 0) return;
            int index = Array.IndexOf(__state.Products, __result);
            if (index < 0) return;
            string target = ProductionCapture.Key("s", __instance, __instance.factorySystem.inserterPool[ProductionCapture.Moving.Sorter].entityId);
            ProductionCapture.Transfer(ProductionCapture.Key("m", __instance, __state.Entity), target, __result, stack, __state.Counts[index]);
        }
    }
    [HarmonyPatch(typeof(PlanetFactory), nameof(PlanetFactory.RemoveEntityWithComponents))]
    internal static class ProgressEntityRemovedPatch
    {
        private static void Prefix(PlanetFactory __instance, int id)
        {
            if (!ProductionCapture.Enabled) return;
            foreach (string type in new[] { "m", "s" }) ProductionCapture.Fact("flow_reset", "target", ProductionCapture.Key(type, __instance, id));
            ProductionCapture.Forget(__instance, id);
        }
    }

    [HarmonyPatch(typeof(PlanetFactory), nameof(PlanetFactory.EntityFastFillIn))]
    internal static class ProgressFastFillPatch
    {
        private static void Prefix(PlanetFactory __instance, int entityId, out int[] __state) =>
            __state = ProductionCapture.Enabled ? ProductionCapture.Inputs(__instance, entityId) : null;
        private static void Postfix(PlanetFactory __instance, int entityId, int[] __state) => ProductionCapture.Manual(__instance, entityId, __state);
    }
    [HarmonyPatch(typeof(PlanetFactory), nameof(PlanetFactory.EntityFastTakeOut))]
    internal static class ProgressFastTakePatch
    {
        private static void Prefix(PlanetFactory __instance, int entityId)
        {
            if (ProductionCapture.Enabled && __instance.entityPool[entityId].inserterId > 0)
                ProductionCapture.Fact("flow_reset", "target", ProductionCapture.Key("s", __instance, entityId));
        }
    }
    [HarmonyPatch]
    internal static class ProgressSorterTakePatch
    {
        private static IEnumerable<MethodBase> TargetMethods() => new[] { "TakeBackItems_Inserter", "ClearItems_Inserter" }
            .Select(name => AccessTools.Method(typeof(FactorySystem), name));
        private static void Prefix(FactorySystem __instance, int inserterId)
        {
            if (ProductionCapture.Enabled && inserterId > 0)
                ProductionCapture.Fact("flow_reset", "target", ProductionCapture.Key("s", __instance.factory,
                    __instance.inserterPool[inserterId].entityId));
        }
    }
    [HarmonyPatch(typeof(UIAssemblerWindow), nameof(UIAssemblerWindow.OnManualServingContentChange))]
    internal static class ProgressManualAssemblerPatch
    {
        private static void Prefix(UIAssemblerWindow __instance, out int[] __state) =>
            __state = ProductionCapture.Enabled && __instance.assemblerId > 0 ?
                ProductionCapture.Inputs(__instance.factory, __instance.factorySystem.assemblerPool[__instance.assemblerId].entityId) : null;
        private static void Postfix(UIAssemblerWindow __instance, int[] __state)
        {
            if (__state != null) ProductionCapture.Manual(__instance.factory,
                __instance.factorySystem.assemblerPool[__instance.assemblerId].entityId, __state);
        }
    }
    [HarmonyPatch(typeof(UILabWindow), "OnItemButtonClick")]
    internal static class ProgressManualLabPatch
    {
        private static void Prefix(UILabWindow __instance, PlanetFactory ___factory, out int[] __state) =>
            __state = ProductionCapture.Enabled && __instance.labId > 0 ?
                ProductionCapture.Inputs(___factory, ___factory.factorySystem.labPool[__instance.labId].entityId) : null;
        private static void Postfix(UILabWindow __instance, PlanetFactory ___factory, int[] __state)
        {
            if (__state != null) ProductionCapture.Manual(___factory,
                ___factory.factorySystem.labPool[__instance.labId].entityId, __state);
        }
    }
}
