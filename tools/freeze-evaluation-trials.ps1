param(
    [Parameter(Mandatory=$true)][string]$DatasetMetadata,
    [Parameter(Mandatory=$true)][string]$Out
)
$ErrorActionPreference = 'Stop'
# Use Windows PowerShell 5.1 / .NET Framework so yaw and double serialization match net472.
if ($PSVersionTable.PSEdition -ne 'Desktop') { throw 'Run with Windows PowerShell 5.1 (powershell.exe).' }
if (Test-Path -LiteralPath $Out) { throw "Refusing overwrite: $Out" }
$root = Split-Path $PSScriptRoot -Parent
$jsonSource = Get-Content -Raw -LiteralPath (Join-Path $root 'src/DSPDreamer.Recorder/Json.cs')
# Windows PowerShell's bundled compiler predates C# pattern variables; keep the shared encoder's logic.
$jsonSource = $jsonSource.Replace('if (value is string text)', 'string text = value as string; if (text != null)')
$jsonSource = $jsonSource.Replace('if (value is bool flag)', 'bool flag = value is bool && (bool)value; if (value is bool)')
$jsonSource = $jsonSource.Replace('if (value is IDictionary<string, object> map)', 'var map = value as IDictionary<string, object>; if (map != null)')
$jsonSource = $jsonSource.Replace('if (value is IEnumerable items)', 'var items = value as IEnumerable; if (items != null)')
Add-Type -ReferencedAssemblies System.Web.Extensions -TypeDefinition ($jsonSource + @'
public static class FrozenEvaluationTrials {
    public static string Generate(string metadata) {
        var serializer = new System.Web.Script.Serialization.JavaScriptSerializer();
        serializer.MaxJsonLength = int.MaxValue;
        var document = serializer.Deserialize<System.Collections.Generic.Dictionary<string, object>>(metadata);
        var baseline = (System.Collections.Generic.Dictionary<string, object>)document["trial_manifest"];
        var entries = new System.Collections.Generic.List<object>();
        foreach (string purpose in new[] { "development", "final" }) {
            int count = purpose == "development" ? 10 : 30;
            int firstSeed = purpose == "development" ? 220100 : 220200;
            for (int i = 0; i < count; i++) {
                var trial = new System.Collections.Generic.Dictionary<string, object>(baseline);
                trial.Remove("manifest_id"); trial.Remove("split_group_id"); trial.Remove("purpose");
                trial["mecha_seed"] = firstSeed + 3*i;
                trial["camera_seed"] = firstSeed + 3*i + 1;
                trial["policy_seed"] = firstSeed + 3*i + 2;
                trial["mecha_yaw"] = new System.Random((int)trial["mecha_seed"]).NextDouble()*30-15;
                trial["camera_yaw"] = new System.Random((int)trial["camera_seed"]).NextDouble()*30-15;
                string encoded = DSPDreamer.Recorder.Json.Encode(trial);
                string id;
                using (var hash = System.Security.Cryptography.SHA256.Create())
                    id = System.BitConverter.ToString(hash.ComputeHash(System.Text.Encoding.UTF8.GetBytes(encoded))).Replace("-", "").ToLowerInvariant();
                trial["manifest_id"] = id; trial["split_group_id"] = id;
                entries.Add(DSPDreamer.Recorder.Json.Fields("purpose", purpose, "trial_manifest", trial));
            }
        }
        return DSPDreamer.Recorder.Json.Encode(DSPDreamer.Recorder.Json.Fields("schema", "dsp-evaluation-trials/1", "manifests", entries));
    }
}
'@)
$payload = [FrozenEvaluationTrials]::Generate([IO.File]::ReadAllText((Resolve-Path -LiteralPath $DatasetMetadata)))
$payload | & (Join-Path $root '.venv/Scripts/python.exe') -c 'import json,sys; sys.path.insert(0,sys.argv[1]); from dsp_dreamer.evaluation_protocol import seal; from dsp_dreamer.contract import atomic_save; atomic_save(sys.argv[2], seal(json.load(sys.stdin)))' $root $Out
if ($LASTEXITCODE -ne 0) { throw 'Trial artifact publication failed' }
