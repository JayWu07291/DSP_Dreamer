using System;
using System.IO;
using System.Reflection;
using DSPDreamer.Recorder;

internal static class Program
{
    private static int Main(string[] args)
    {
        try
        {
            Check();
            foreach (string path in args)
            {
                byte[] bytes = File.ReadAllBytes(path);
                Assembly assembly = Assembly.Load(bytes);
                if (assembly.Location != "" || SegmentWriter.HashAssembly(assembly, path) != SegmentWriter.Hash(bytes))
                    throw new Exception("實際組件的記憶體載入檢查失敗：" + path);
                Console.WriteLine("通過：" + Path.GetFileName(path));
            }
            return 0;
        }
        catch (Exception error) { Console.WriteLine(error.GetType().Name + ": " + error.Message); return 1; }
    }

    private static void Check()
    {
        string path = Assembly.GetExecutingAssembly().Location;
        byte[] bytes = File.ReadAllBytes(path);
        Assembly memoryLoaded = Assembly.Load(bytes);
        if (memoryLoaded.Location != "") throw new Exception("測試必須使用沒有磁碟路徑的組件");
        string actual = SegmentWriter.HashAssembly(memoryLoaded, path);
        if (actual != SegmentWriter.Hash(bytes)) throw new Exception("組件來源的 SHA-256 不符");
        if (SegmentWriter.HashAssembly(Assembly.GetExecutingAssembly(), "") != actual)
            throw new Exception("磁碟載入組件的來源指紋不符");
        try
        {
            SegmentWriter.HashAssembly(memoryLoaded, path + ".missing");
            throw new Exception("缺少來源檔案時必須拒絕");
        }
        catch (FileNotFoundException) { }
        bool mismatchRejected = false;
        try { SegmentWriter.HashAssembly(memoryLoaded, typeof(object).Assembly.Location); }
        catch (IOException) { mismatchRejected = true; }
        if (!mismatchRejected) throw new Exception("組件來源身分不符時必須拒絕");
        Console.WriteLine("通過：記憶體載入組件的來源指紋正確");
    }
}
