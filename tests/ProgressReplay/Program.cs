using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Web.Script.Serialization;
using DSPDreamer.Recorder;

internal static class Program
{
    private static int Main(string[] args)
    {
        try { if (args.Length > 0) CheckHooks(args[0], args[1]); else Replay(); return 0; }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }

    private static void CheckHooks(string gameRoot, string pluginPath)
    {
        AppDomain.CurrentDomain.AssemblyResolve += (sender, e) => {
            string file = new AssemblyName(e.Name).Name + ".dll";
            foreach (string directory in new[] { "DSPGAME_Data/Managed", "BepInEx/core" })
            {
                string path = Path.Combine(gameRoot, directory, file);
                if (File.Exists(path)) return Assembly.Load(File.ReadAllBytes(path));
            }
            return null;
        };
        var harmonyAssembly = Assembly.Load(File.ReadAllBytes(Path.Combine(gameRoot, "BepInEx/core/0Harmony.dll")));
        Type harmonyType = harmonyAssembly.GetType("HarmonyLib.Harmony");
        object harmony = Activator.CreateInstance(harmonyType, "dspdreamer.production.check");
        Assembly plugin = Assembly.LoadFrom(pluginPath);
        foreach (Type type in plugin.GetTypes().Where(t => t.Name.StartsWith("Progress") &&
            t.GetCustomAttributesData().Any(a => a.AttributeType.Name == "HarmonyPatch")))
        {
            object processor = harmonyType.GetMethod("CreateClassProcessor", new[] { typeof(Type) }).Invoke(harmony, new object[] { type });
            processor.GetType().GetMethod("Patch", Type.EmptyTypes).Invoke(processor, null);
            Console.WriteLine(type.Name);
        }
    }

    private static void Replay()
    {
        var json = new JavaScriptSerializer();
        string header = Console.ReadLine();
        var options = header.StartsWith("{") ? json.Deserialize<Dictionary<string, object>>(header) : null;
        int[] ids = options == null ? json.Deserialize<int[]>(header) : json.ConvertToType<int[]>(options["tech_ids"]);
        int version = options == null ? 1 : Convert.ToInt32(options["version"]);
        var states = new Dictionary<string, TaskProgress>();
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var row = json.Deserialize<Dictionary<string, object>>(line);
            string id = (string)row["episode_id"];
            if (!states.TryGetValue(id, out TaskProgress state)) states[id] = state = new TaskProgress(ids, version);
            if ((string)row["name"] == "progress_fact") state.Apply(row);
            else
            {
                state.Observe();
                row["task_id"] = state.Active;
                row["node_completed"] = state.Done;
                row["previous_task_id"] = state.PreviousTask;
                row["reward_vector"] = state.RewardVector;
                row["reward"] = state.Reward;
                row["node_completions"] = state.Completions;
                Console.WriteLine(json.Serialize(row));
            }
        }
    }
}
