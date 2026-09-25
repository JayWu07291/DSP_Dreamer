using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.Serialization;
using System.Threading;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Mono.Cecil;
using Mono.Cecil.Cil;

internal static class Program
{
    private const BindingFlags Fields = BindingFlags.Instance | BindingFlags.NonPublic;

    private static int Main(string[] args)
    {
        AppDomain.CurrentDomain.AssemblyResolve += (_, e) => {
            foreach (string directory in new[] { args[1], args[2] })
            {
                string path = Path.Combine(directory, new AssemblyName(e.Name).Name + ".dll");
                if (File.Exists(path)) return Assembly.LoadFrom(path);
            }
            return null;
        };
        try { Run(args[0]); Console.WriteLine("human-policy guards passed"); return 0; }
        catch (Exception error)
        {
            for (Exception e = error; e != null; e = e.InnerException) Console.Error.WriteLine(e.GetType().FullName + ": " + e.Message);
            return 1;
        }
    }

    private static void Run(string dll)
    {
        // Copy the built DLL in memory. Keep public API IL unchanged; replace only
        // Unity logging and side-effect boundaries because Unity ECalls cannot run in CLR.
        byte[] bytes;
        using (var module = ModuleDefinition.ReadModule(dll))
        using (var stream = new MemoryStream())
        {
            var recorder = module.Types.Single(t => t.Name == "RecorderPlugin");
            foreach (string name in new[] { "Emit", "InjectAction", "ReleaseControls", "StartRecording" })
            {
                var method = recorder.Methods.Single(m => m.Name == name);
                method.Body = new Mono.Cecil.Cil.MethodBody(method);
                var il = method.Body.GetILProcessor();
                if (name == "Emit") il.Emit(OpCodes.Ret);
                else
                {
                    il.Emit(OpCodes.Ldstr, "Guard crossed side-effect boundary: " + name);
                    il.Emit(OpCodes.Newobj, module.ImportReference(typeof(Exception).GetConstructor(new[] { typeof(string) })));
                    il.Emit(OpCodes.Throw);
                }
            }
            module.Write(stream);
            bytes = stream.ToArray();
        }
        Type type = Assembly.Load(bytes).GetType("DSPDreamer.Recorder.RecorderPlugin", true);
        object plugin = FormatterServices.GetUninitializedObject(type);
        Action<string, object> set = (name, value) => type.GetField(name, Fields).SetValue(plugin, value);
        set("mainThread", Thread.CurrentThread.ManagedThreadId);
        set("controlMode", "human");
        set("active", true);
        var pendingField = type.GetField("pendingAction", Fields);
        object pending = FormatterServices.GetUninitializedObject(pendingField.FieldType);
        var values = new object[] { new int[] { 1, 0, 1 }, 17, 2, 123L, 456L };
        var names = new[] { "Binary", "Mouse", "Wheel", "CaptureTicks", "InferenceTicks" };
        for (int i = 0; i < names.Length; i++) pendingField.FieldType.GetField(names[i], Fields).SetValue(pending, values[i]);
        set("pendingAction", pending);
        Action unchanged = () => {
            if ((string)type.GetField("controlMode", Fields).GetValue(plugin) != "human" ||
                !ReferenceEquals(pendingField.GetValue(plugin), pending) ||
                !(bool)type.GetField("active", Fields).GetValue(plugin) ||
                !((int[])values[0]).SequenceEqual(new[] { 1, 0, 1 }))
                throw new Exception("Human session mutated by rejected policy action");
            for (int i = 0; i < names.Length; i++)
                if (!Equals(pendingField.FieldType.GetField(names[i], Fields).GetValue(pending), values[i]))
                    throw new Exception("Pending action mutated: " + names[i]);
        };
        Reject(type, plugin, "StartPolicyRecording", "Recording already active");
        unchanged();
        Reject(type, plugin, "SubmitAction", "No active policy episode", "action_catalog_v4", new int[21], 60, 1, 1L, 1L);
        unchanged();
        set("active", false);
        set("writer", new Thread(() => { }));
        Reject(type, plugin, "StartPolicyRecording", "Recording already active");
        set("mainThread", -1);
        Reject(type, plugin, "StartPolicyRecording", "Control must run on Unity main thread");
        Reject(type, plugin, "SubmitAction", "Control must run on Unity main thread", "action_catalog_v4", new int[21], 60, 1, 1L, 1L);

        // A worker failure must reach Update with ownership intact so final capture is not a recorder fault.
        set("policyGate", new object());
        var worker = new Process();
        set("policyWorker", worker);
        set("policyError", "test worker exit");
        bool workerRejected = false;
        try { type.GetMethod("RunnerUpdate", Fields).Invoke(plugin, null); }
        catch (TargetInvocationException error) when (error.InnerException is IOException && error.InnerException.Message == "test worker exit") { workerRejected = true; }
        if (!workerRejected || !ReferenceEquals(type.GetField("policyWorker", Fields).GetValue(plugin), worker))
            throw new Exception("Worker error discarded ownership before final capture");
        worker.Dispose();
        set("policyWorker", null);

        // Exercise real hook installation/pump/shutdown without sending any input to the desktop.
        type.GetMethod("WatchHumanInput", Fields).Invoke(plugin, null);
        var hookThread = (Thread)type.GetField("policyHookThread", Fields).GetValue(plugin);
        if (!hookThread.IsAlive || hookThread.ManagedThreadId == Thread.CurrentThread.ManagedThreadId)
            throw new Exception("Input hook does not have its own message pump");
        type.GetMethod("StopHumanInputWatch", Fields).Invoke(plugin, null);
        if (hookThread.IsAlive) throw new Exception("Input hook thread leaked");
        IntPtr data = Marshal.AllocHGlobal(32);
        try
        {
            foreach (bool mouse in new[] { false, true })
            {
                var callback = (Delegate)type.GetField(mouse ? "policyMouseCallback" : "policyKeyboardCallback", Fields).GetValue(plugin);
                for (int i = 0; i < 32; i++) Marshal.WriteByte(data, i, 0);
                Marshal.WriteInt32(data, mouse ? 12 : 8, mouse ? 1 : 0x10);
                Marshal.WriteInt64(data, mouse ? 24 : 16, 0x44535044);
                set("humanInput", false);
                set("watchHumanInput", true);
                callback.DynamicInvoke(0, IntPtr.Zero, data);
                if ((bool)type.GetField("humanInput", Fields).GetValue(plugin)) throw new Exception("Tagged input called human");
                Marshal.WriteInt64(data, mouse ? 24 : 16, 0);
                callback.DynamicInvoke(0, IntPtr.Zero, data);
                if (!(bool)type.GetField("humanInput", Fields).GetValue(plugin)) throw new Exception("Foreign input missed");
            }
        }
        finally { Marshal.FreeHGlobal(data); }
    }

    private static void Reject(Type type, object plugin, string method, string expected, params object[] args)
    {
        try { type.GetMethod(method).Invoke(plugin, args); }
        catch (TargetInvocationException error) when (error.InnerException is InvalidOperationException && error.InnerException.Message == expected) { return; }
        throw new Exception(method + " did not reject: " + expected);
    }
}
