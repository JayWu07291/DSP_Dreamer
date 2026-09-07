param(
    [ValidateSet('prepare', 'verify', 'benchmark', 'finalize')][string]$Command = 'prepare',
    [ValidateSet('ffv1', 'gzip1', 'raw')][string]$Codec = 'ffv1',
    [int]$Seconds = 1800,
    [string]$DspRoot = 'E:\Steam\steamapps\common\Dyson Sphere Program',
    [string]$Ffmpeg = 'E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe',
    [string]$Python = 'C:\Users\jay07\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe',
    [string]$RunDirectory
)
$ErrorActionPreference = 'Stop'
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$tool = Join-Path $PSScriptRoot 'storage_probe.py'
$pluginDirectory = Join-Path $DspRoot 'BepInEx\plugins\DSPDreamerCaptureProbe'
$runs = Join-Path $pluginDirectory 'runs-lossless'
if ($Command -eq 'benchmark') {
    & $Python $tool --ffmpeg $Ffmpeg benchmark --out (Join-Path $PSScriptRoot "out\offline-$stamp")
    if ($LASTEXITCODE -ne 0) { throw 'Benchmark failed' }
    exit
}
if ($Command -eq 'verify' -or $Command -eq 'finalize') {
    if (-not $RunDirectory) {
        $RunDirectory = (Get-ChildItem -LiteralPath $runs -Directory | Sort-Object Name -Descending | Select-Object -First 1).FullName
    }
    if (-not $RunDirectory) { throw 'No lossless run found' }
    if ($Command -eq 'finalize') {
        & $Python (Join-Path $PSScriptRoot 'auto_finalize.py') --ffmpeg $Ffmpeg --run $RunDirectory
    } else {
        & $Python $tool --ffmpeg $Ffmpeg verify-run --run $RunDirectory
    }
    if ($LASTEXITCODE -ne 0) { throw 'Verification failed' }
    exit
}
if (Get-Process -Name DSPGAME -ErrorAction SilentlyContinue) { throw 'Close DSP before preparing a run' }
if ($Seconds -le 0) { throw 'Seconds must be positive' }
if ($Codec -eq 'ffv1' -and -not (Test-Path -LiteralPath $Ffmpeg)) { throw 'FFmpeg executable missing' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Python executable missing' }
$project = Join-Path $PSScriptRoot '..\issue-4-recorder\DSPDreamer.CaptureProbe.csproj'
dotnet build $project --configuration Release "-p:DSPRoot=$DspRoot"
if ($LASTEXITCODE -ne 0) { throw 'Build failed; deployment skipped' }
$backup = Join-Path $PSScriptRoot "out\deployment-backup-$stamp"
New-Item -ItemType Directory -Path $backup | Out-Null
$dll = Join-Path $pluginDirectory 'DSPDreamer.CaptureProbe.dll'
$config = Join-Path $DspRoot 'BepInEx\config\tw.jaywu.dspdreamer.capture-probe.cfg'
foreach ($path in @($dll, $config)) {
    if (Test-Path -LiteralPath $path) { Copy-Item -LiteralPath $path -Destination $backup }
}
$finalizerDirectory = Join-Path $pluginDirectory 'finalizer'
if (Test-Path -LiteralPath $finalizerDirectory) {
    Copy-Item -LiteralPath $finalizerDirectory -Destination (Join-Path $backup 'finalizer') -Recurse
}
New-Item -ItemType Directory -Path $finalizerDirectory -Force | Out-Null
foreach ($workerFile in @('auto_finalize.py', 'merge_prototype.py', 'storage_probe.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $workerFile) -Destination (Join-Path $finalizerDirectory $workerFile) -Force
}
$text = if (Test-Path -LiteralPath $config) { Get-Content -LiteralPath $config -Raw } else { "[Probe]`r`n" }
function Set-ProbeValue([string]$Document, [string]$Key, [string]$Value, [string]$Section) {
    $pattern = '(?m)^' + [regex]::Escape($Key) + '\s*=.*$'
    if ([regex]::IsMatch($Document, $pattern)) {
        return [regex]::Replace($Document, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) "$Key = $Value" })
    }
    $sectionPattern = '(?m)^\[' + [regex]::Escape($Section) + '\]\s*$'
    if ([regex]::IsMatch($Document, $sectionPattern)) {
        return [regex]::Replace($Document, $sectionPattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $m.Value + "`r`n$Key = $Value" })
    }
    return $Document + "`r`n[$Section]`r`n$Key = $Value`r`n"
}
foreach ($entry in @(@('CaptureHz','20','Probe'), @('DurationSeconds',[string]$Seconds,'Probe'),
    @('OutputRoot',$runs,'Probe'), @('Codec',$Codec,'StoragePrototype'), @('Ffmpeg',$Ffmpeg,'StoragePrototype'),
    @('SegmentFrames','200','StoragePrototype'), @('AutoFinalize','true','StoragePrototype'),
    @('FinalizePython',$Python,'StoragePrototype'))) {
    $text = Set-ProbeValue $text $entry[0] $entry[1] $entry[2]
}
[IO.File]::WriteAllText($config, $text, [Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\issue-4-recorder\bin\Release\DSPDreamer.CaptureProbe.dll') -Destination $dll -Force
[ordered]@{ codec=$Codec; capture_hz=20; duration_seconds=$Seconds; segment_frames=200; runs=$runs; backup=$backup;
    dll_sha256=(Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash;
    ffmpeg_sha256=(Get-FileHash -LiteralPath $Ffmpeg -Algorithm SHA256).Hash } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'deployment.json') -Encoding utf8
Write-Host "Prepared $Codec at 20 Hz for $Seconds seconds. Backup: $backup"
Write-Host 'Start DSP at 1280x720, load a scene, and press Ctrl+F8. Recording stops automatically.'
Write-Host 'After stopping, FFV1 automatically merges and verifies, then cleans this session temporary files.'
Write-Host 'If finalization fails, sources remain. Retry with: .\prototypes\issue-11-lossless\probe.ps1 finalize -RunDirectory <run>'
