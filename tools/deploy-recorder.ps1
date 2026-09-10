param(
    [string]$DSPRoot = 'E:\Steam\steamapps\common\Dyson Sphere Program',
    [string]$FFmpeg = 'E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe',
    [switch]$Diagnostics
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (Get-Process DSPGAME -ErrorAction SilentlyContinue) { throw 'Exit DSP before deployment.' }
$expectedGame = 'AE0BA95F75BD879A62AA4CE253B2AB78EAA4FB3C7C595F5E1FEE75EBE0E0EF85'
if ((Get-FileHash -LiteralPath (Join-Path $DSPRoot 'DSPGAME_Data\Managed\Assembly-CSharp.dll')).Hash -ne $expectedGame) {
    throw 'Unknown game binary. Revalidate integration points before deployment.'
}
if ((Get-FileHash -LiteralPath $FFmpeg).Hash -ne '04E1307997530F9CF2FE35CBA2CA7E8875CA91DA02F89D6C7243DF819C94AD00') {
    throw 'Unknown FFmpeg executable.'
}
& dotnet build (Join-Path $repoRoot 'src\DSPDreamer.Recorder\DSPDreamer.Recorder.csproj') --configuration Release "-p:DSPRoot=$DSPRoot"
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
$plugin = Join-Path $DSPRoot 'BepInEx\plugins\DSPDreamer'
$config = Join-Path $DSPRoot 'BepInEx\config\tw.jaywu.dspdreamer.recorder.cfg'
$dll = Join-Path $plugin 'DSPDreamer.Recorder.dll'
$backup = Join-Path $repoRoot ('runs\deployment-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($file in @($dll, $config)) {
    if (Test-Path -LiteralPath $file) { Copy-Item -LiteralPath $file -Destination $backup }
}
New-Item -ItemType Directory -Path $plugin -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repoRoot 'src\DSPDreamer.Recorder\bin\Release\DSPDreamer.Recorder.dll') -Destination $dll
$settings = @"
[Recording]
Output = $repoRoot\runs\live
FFmpeg = $FFmpeg
ApprovedFingerprint =
Python = $repoRoot\.venv\Scripts\python.exe
Repository = $repoRoot

[Diagnostics]
Enabled = $($Diagnostics.IsPresent.ToString().ToLowerInvariant())
"@
Set-Content -LiteralPath $config -Value $settings -Encoding utf8
Get-FileHash -LiteralPath $dll
Write-Output "Deployed. Existing files backed up under $backup. Runtime fingerprint remains unapproved."
