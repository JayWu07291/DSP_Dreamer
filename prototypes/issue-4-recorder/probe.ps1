param(
    [ValidateSet('build', 'deploy', 'show-latest', 'export-frame')]
    [string]$Command = 'deploy',
    [string]$DspRoot = 'E:\Steam\steamapps\common\Dyson Sphere Program'
)

$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot 'DSPDreamer.CaptureProbe.csproj'
$configuration = 'Release'
$output = Join-Path $PSScriptRoot 'bin\Release'
$pluginDirectory = Join-Path $DspRoot 'BepInEx\plugins\DSPDreamerCaptureProbe'
$runsDirectory = Join-Path $pluginDirectory 'runs'

if ($Command -eq 'show-latest') {
    $latest = Get-ChildItem -LiteralPath $runsDirectory -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if ($null -eq $latest) { throw "No probe run exists under $runsDirectory" }
    Get-Content -LiteralPath (Join-Path $latest.FullName 'summary.json')
    $taskEvents = Get-Content -LiteralPath (Join-Path $latest.FullName 'events.ndjson') | ForEach-Object {
        $event = $_ | ConvertFrom-Json
        if ($event.type -eq 'task_event') { $event }
    }
    Write-Host "Task events: $($taskEvents.Count)"
    $taskEvents | Select-Object name, game_tick, unity_frame, tech_id, level, entity_id, prebuild_id, proto_id, object_id | Format-Table -AutoSize
    exit
}

if ($Command -eq 'export-frame') {
    Add-Type -AssemblyName System.Drawing
    $latest = Get-ChildItem -LiteralPath $runsDirectory -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if ($null -eq $latest) { throw "No probe run exists under $runsDirectory" }
    $summary = Get-Content -LiteralPath (Join-Path $latest.FullName 'summary.json') -Raw | ConvertFrom-Json
    $event = Get-Content -LiteralPath (Join-Path $latest.FullName 'events.ndjson') | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object type -eq 'capture_written' | Select-Object -First 1
    if ($null -eq $event) { throw 'The run contains no written frame.' }
    $bytes = New-Object byte[] ([int]$event.byte_count)
    $stream = [System.IO.File]::OpenRead((Join-Path $latest.FullName 'frames.rgba'))
    try {
        $stream.Seek([long]$event.file_offset, [System.IO.SeekOrigin]::Begin) | Out-Null
        if ($stream.Read($bytes, 0, $bytes.Length) -ne $bytes.Length) { throw 'The raw frame is truncated.' }
    } finally { $stream.Dispose() }

    foreach ($flip in @($false, $true)) {
        $bitmap = New-Object System.Drawing.Bitmap([int]$summary.width, [int]$summary.height)
        for ($y = 0; $y -lt $summary.height; $y++) {
            $sourceY = if ($flip) { $summary.height - 1 - $y } else { $y }
            for ($x = 0; $x -lt $summary.width; $x++) {
                $offset = 4 * ($sourceY * $summary.width + $x)
                $bitmap.SetPixel($x, $y, [System.Drawing.Color]::FromArgb($bytes[$offset + 3], $bytes[$offset], $bytes[$offset + 1], $bytes[$offset + 2]))
            }
        }
        $name = if ($flip) { 'first-frame-flipped.png' } else { 'first-frame-native.png' }
        $path = Join-Path $latest.FullName $name
        $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
        $bitmap.Dispose()
        Write-Host $path
    }
    exit
}

if ($Command -eq 'deploy' -and $null -ne (Get-Process -Name DSPGAME -ErrorAction SilentlyContinue)) {
    throw 'DSP is running. Close DSP before deploying the probe DLL.'
}

$pluginSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'CaptureProbePlugin.cs') -Raw
if ($pluginSource -notmatch 'PluginVersion\s*=\s*"([^"]+)"') {
    throw 'PluginVersion constant was not found.'
}
$pluginVersion = $Matches[1]
[Reflection.Assembly]::LoadFrom((Join-Path $DspRoot 'BepInEx\core\BepInEx.dll')) | Out-Null
$pluginMetadata = New-Object BepInEx.BepInPlugin('probe.validation', 'probe validation', $pluginVersion)
if ($null -eq $pluginMetadata.Version) {
    throw "BepInEx 5 rejects plugin version '$pluginVersion'. Use a numeric System.Version value such as 0.1.0."
}

dotnet build $project --configuration $configuration -p:DSPRoot=$DspRoot

if ($Command -eq 'deploy') {
    New-Item -ItemType Directory -Force -Path $pluginDirectory | Out-Null
    Copy-Item -LiteralPath (Join-Path $output 'DSPDreamer.CaptureProbe.dll') -Destination $pluginDirectory -Force
    Write-Host "Deployed to $pluginDirectory"
    Write-Host 'Set DSP to 1280x720 at 60 FPS. Then use Ctrl+F8, Ctrl+F9, and Ctrl+Shift+F11 as described in README.md.'
}
