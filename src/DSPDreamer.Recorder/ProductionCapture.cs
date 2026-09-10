using HarmonyLib;
using System;
using System.Collections.Generic;
using System.Linq;

namespace DSPDreamer.Recorder
{
    // Native recipe, inventory and completed-cycle facts accompany current line connections.
    internal static class ProductionCapture
    {
        internal sealed class Sample
        {
            internal PlanetFactory Factory;
            internal int Entity, Cycles, Output;
            internal int[] Before;
        }
        private static readonly object gate = new object();
        private static readonly Dictionary<string, int> recipes = new Dictionary<string, int>();
        private static readonly Dictionary<string, int[]> lastInputs = new Dictionary<string, int[]>();
        private static readonly Dictionary<string, int> lastOutputs = new Dictionary<string, int>();
        internal static bool Enabled => RecorderPlugin.Current != null && RecorderPlugin.Current.ProgressEnabled;
        internal static string Key(string type, PlanetFactory factory, int id) => type + ":" + factory.index + ":" + id;
        internal static void Fact(string kind, params object[] fields) => RecorderPlugin.Current?.RecordProgressFact(kind, Json.Fields(fields));
        internal static void Reset()
        {
            lock (gate) { recipes.Clear(); lastInputs.Clear(); lastOutputs.Clear(); }
            ProductionConnections.Reset();
        }
        internal static void Forget(PlanetFactory factory, int entity)
        {
            string key = Key("m", factory, entity);
            lock (gate) { recipes.Remove(key); lastInputs.Remove(key); lastOutputs.Remove(key); }
            ProductionConnections.Forget(key);
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
            ProductionConnections.Capture(sample.Factory, sample.Entity);
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
            Fact("manual_inventory", "target", Key("m", factory, entity), "before", before, "after", after);
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
