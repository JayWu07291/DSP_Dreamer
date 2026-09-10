using System;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using DSPDreamer.Recorder;

internal static class Program
{
    private static void Main()
    {
        var json = new JavaScriptSerializer();
        int[] ids = json.Deserialize<int[]>(Console.ReadLine());
        var states = new Dictionary<string, TaskProgress>();
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var row = json.Deserialize<Dictionary<string, object>>(line);
            string id = (string)row["episode_id"];
            if (!states.TryGetValue(id, out TaskProgress state)) states[id] = state = new TaskProgress(ids);
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
