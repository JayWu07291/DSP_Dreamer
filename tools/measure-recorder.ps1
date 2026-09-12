#requires -Version 7.0
param(
    [Parameter(Mandatory)][string]$Out,
    [int]$IntervalSeconds = 5,
    [int]$Samples = 0
)
$ErrorActionPreference = 'Stop'
if ($IntervalSeconds -lt 1 -or $Samples -lt 0) { throw 'Invalid sampling limits.' }
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$live = Join-Path $repo 'runs\live'
$existing = @(Get-ChildItem -LiteralPath $live -Directory -Filter '*.source' | ForEach-Object Name)
$destination = [IO.Path]::GetFullPath($Out)
$clock = [Diagnostics.Stopwatch]::StartNew()
$stream = [IO.StreamWriter]::new([IO.File]::Open($destination, 'CreateNew', 'Write', 'Read'))
try {
    $sample = 0
    do {
        $processes = @(Get-Process DSPGAME, python, ffmpeg -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                if ($_.ProcessName -eq 'DSPGAME' -or $_.Path -eq (Join-Path $repo '.venv\Scripts\python.exe') -or
                    $_.Parent.Path -eq (Join-Path $repo '.venv\Scripts\python.exe') -or
                    $_.Path -eq 'E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe') {
                    [ordered]@{ pid = $_.Id; parent_pid = $_.Parent.Id; name = $_.ProcessName; start_utc = $_.StartTime.ToUniversalTime().ToString('o');
                        working_set_bytes = $_.WorkingSet64; private_bytes = $_.PrivateMemorySize64;
                        peak_working_set_bytes = $_.PeakWorkingSet64; cpu_seconds = $_.CPU }
                }
            } catch { [ordered]@{ pid = $_.Id; error = 'Process exited or metrics unavailable' } }
        })
        # ponytail: periodic samples miss short peaks; use ETW if sub-interval attribution is required.
        $row = [ordered]@{
            utc = [DateTime]::UtcNow.ToString('o'); elapsed_seconds = $clock.Elapsed.TotalSeconds
            interval_seconds = $IntervalSeconds; processes = $processes
            recordings = @(Get-ChildItem -LiteralPath $live -Directory -Filter '*.source' |
                Where-Object { $_.Name -notin $existing } | ForEach-Object {
                    $recordingPath = $_.FullName
                    [ordered]@{ source = $_.Name
                        sealed = Test-Path -LiteralPath (Join-Path $recordingPath 'SOURCE.json')
                        evidence_published = Test-Path -LiteralPath ($recordingPath + '.evidence\manifest.json')
                        dataset_started = Test-Path -LiteralPath ($recordingPath + '.dataset')
                        dataset_completed = Test-Path -LiteralPath ($recordingPath + '.dataset\COMPLETED') }
                })
            drives = @([IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady -and $_.DriveType -eq 'Fixed' } |
                ForEach-Object { [ordered]@{ name = $_.Name; free_bytes = $_.AvailableFreeSpace; total_bytes = $_.TotalSize } })
        }
        $stream.WriteLine(($row | ConvertTo-Json -Depth 8 -Compress))
        $stream.Flush()
        $sample++
        if (($Samples -gt 0 -and $sample -ge $Samples) -or (Test-Path -LiteralPath ($destination + '.stop'))) { break }
        Start-Sleep -Seconds $IntervalSeconds
    } while ($true)
} finally { $stream.Dispose() }
