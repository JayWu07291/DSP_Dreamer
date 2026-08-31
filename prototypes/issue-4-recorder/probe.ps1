param(
    [ValidateSet('build', 'deploy', 'show-latest', 'export-frame', 'export-event-frames', 'verify-alignment')]
    [string]$Command = 'deploy',
    [string]$DspRoot = 'E:\Steam\steamapps\common\Dyson Sphere Program',
    [string]$RunDirectory
)

$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot 'DSPDreamer.CaptureProbe.csproj'
$configuration = 'Release'
$output = Join-Path $PSScriptRoot 'bin\Release'
$pluginDirectory = Join-Path $DspRoot 'BepInEx\plugins\DSPDreamerCaptureProbe'
$runsDirectory = Join-Path $pluginDirectory 'runs'

function Get-SelectedRun {
    if (-not [string]::IsNullOrWhiteSpace($RunDirectory)) {
        $selected = Get-Item -LiteralPath $RunDirectory
        if (-not $selected.PSIsContainer) { throw "RunDirectory is not a directory: $RunDirectory" }
        return $selected
    }
    $latest = Get-ChildItem -LiteralPath $runsDirectory -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if ($null -eq $latest) { throw "No probe run exists under $runsDirectory" }
    return $latest
}

function Export-RgbaFrame($Stream, $Summary, $Capture, [string]$Path, [bool]$Flip = $false) {
    $width = [int]$Summary.width
    $height = [int]$Summary.height
    $expectedBytes = $width * $height * 4
    if ([int]$Capture.byte_count -ne $expectedBytes) {
        throw "Capture $($Capture.capture_id) has $($Capture.byte_count) bytes; expected $expectedBytes for ${width}x${height} RGBA."
    }
    $bytes = New-Object byte[] ([int]$Capture.byte_count)
    $Stream.Seek([long]$Capture.file_offset, [System.IO.SeekOrigin]::Begin) | Out-Null
    if ($Stream.Read($bytes, 0, $bytes.Length) -ne $bytes.Length) { throw "Raw frame is truncated at capture $($Capture.capture_id)." }
    $bitmap = New-Object System.Drawing.Bitmap($width, $height, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $rectangle = New-Object System.Drawing.Rectangle(0, 0, $width, $height)
    $bitmapData = $bitmap.LockBits($rectangle, [System.Drawing.Imaging.ImageLockMode]::WriteOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    try {
        $bitmapBytes = New-Object byte[] ([Math]::Abs($bitmapData.Stride) * $height)
        for ($destinationY = 0; $destinationY -lt $height; $destinationY++) {
            $sourceY = if ($Flip) { $height - 1 - $destinationY } else { $destinationY }
            $sourceRowOffset = $sourceY * $width * 4
            $destinationRowOffset = $destinationY * [Math]::Abs($bitmapData.Stride)
            for ($x = 0; $x -lt $width; $x++) {
                $sourceOffset = $sourceRowOffset + $x * 4
                $destinationOffset = $destinationRowOffset + $x * 4
                $bitmapBytes[$destinationOffset] = $bytes[$sourceOffset + 2]
                $bitmapBytes[$destinationOffset + 1] = $bytes[$sourceOffset + 1]
                $bitmapBytes[$destinationOffset + 2] = $bytes[$sourceOffset]
                $bitmapBytes[$destinationOffset + 3] = $bytes[$sourceOffset + 3]
            }
        }
        [Runtime.InteropServices.Marshal]::Copy($bitmapBytes, 0, $bitmapData.Scan0, $bitmapBytes.Length)
    } finally {
        $bitmap.UnlockBits($bitmapData)
    }
    try {
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $bitmap.Dispose()
    }
}

function Find-CaptureAtOrAfter($Captures, [long]$Ticks) {
    return $Captures | Where-Object { [long]$_.requested_ticks -ge $Ticks } | Select-Object -First 1
}

function Find-CaptureAtOrBefore($Captures, [long]$Ticks) {
    return $Captures | Where-Object { [long]$_.requested_ticks -le $Ticks } | Select-Object -Last 1
}

function Format-TaskEventDetails($Event) {
    $parts = [Collections.Generic.List[string]]::new()
    if ($null -ne $Event.tech_id) { $parts.Add("科技 $($Event.tech_id) $($Event.tech_name)") }
    if ($null -ne $Event.recipe_id) { $parts.Add("配方 $($Event.recipe_id) $($Event.recipe_name)") }
    if ($null -ne $Event.product_ids) { $parts.Add("產物 $($Event.product_ids) $($Event.product_names) ×$($Event.product_counts)") }
    if ($null -ne $Event.item_id) { $parts.Add("物品 $($Event.item_id) $($Event.item_name) ×$($Event.item_count)") }
    if ($null -ne $Event.mining_proto_id) { $parts.Add("採集物 $($Event.mining_proto_id) $($Event.mining_proto_name)") }
    if ($null -ne $Event.entity_id) { $parts.Add("實體ID $($Event.entity_id)") }
    if ($null -ne $Event.prebuild_id -and $Event.prebuild_id -ne 0) { $parts.Add("預建物ID $($Event.prebuild_id)") }
    if ($null -ne $Event.object_id) { $parts.Add("拆除物ID $($Event.object_id)") }
    if ($null -ne $Event.vege_id) { $parts.Add("植被實例ID $($Event.vege_id)") }
    if ($null -ne $Event.proto_id) { $parts.Add("原型 $($Event.proto_id) $($Event.proto_name)") }
    if ($null -ne $Event.panel_instance_id) { $parts.Add("面板 $($Event.panel)#$($Event.panel_instance_id)") }
    return $parts -join '; '
}

if ($Command -eq 'show-latest') {
    $latest = Get-SelectedRun
    Get-Content -LiteralPath (Join-Path $latest.FullName 'summary.json')
    $taskEvents = Get-Content -LiteralPath (Join-Path $latest.FullName 'events.ndjson') | ForEach-Object {
        $event = $_ | ConvertFrom-Json
        if ($event.type -eq 'task_event') { $event }
    }
    $panelSnapshot = Get-Content -LiteralPath (Join-Path $latest.FullName 'events.ndjson') | ForEach-Object {
        $event = $_ | ConvertFrom-Json
        if ($event.type -eq 'panel_state_snapshot') { $event }
    } | Select-Object -First 1
    Write-Host "Initial open panels: $($panelSnapshot.open_panels)"
    Write-Host "Task events: $($taskEvents.Count)"
    $sourceAcquisitionKeys = [Collections.Generic.HashSet[string]]::new()
    foreach ($event in $taskEvents) {
        if ($event.name -eq 'manual_mining_yield') {
            $sourceAcquisitionKeys.Add("$($event.game_tick)|$($event.item_id)|$($event.item_count)") | Out-Null
        }
        if ($event.name -eq 'craft_completed') {
            $productIds = @([string]$event.product_ids -split ',')
            $productCounts = @([string]$event.product_counts -split ',')
            for ($i = 0; $i -lt [Math]::Min($productIds.Count, $productCounts.Count); $i++) {
                $sourceAcquisitionKeys.Add("$($event.game_tick)|$($productIds[$i])|$($productCounts[$i])") | Out-Null
            }
        }
    }
    $collapsedItemEvents = 0
    $displayEvents = @($taskEvents | Where-Object {
        if ($_.name -ne 'item_acquired') { return $true }
        $isOverlap = $sourceAcquisitionKeys.Contains("$($_.game_tick)|$($_.item_id)|$($_.item_count)")
        if ($isOverlap) { $collapsedItemEvents++ }
        return -not $isOverlap
    })
    Write-Host "Collapsed overlapping item_acquired rows: $collapsedItemEvents"
    $displayEvents | ForEach-Object {
        [PSCustomObject]@{
            Event = $_.name
            GameTick = $_.game_tick
            IdAndChineseName = Format-TaskEventDetails $_
        }
    } | Format-Table -Wrap -AutoSize
    exit
}

if ($Command -eq 'export-frame') {
    Add-Type -AssemblyName System.Drawing
    $latest = Get-SelectedRun
    $summary = Get-Content -LiteralPath (Join-Path $latest.FullName 'summary.json') -Raw | ConvertFrom-Json
    $event = Get-Content -LiteralPath (Join-Path $latest.FullName 'events.ndjson') | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object type -eq 'capture_written' | Select-Object -First 1
    if ($null -eq $event) { throw 'The run contains no written frame.' }
    $stream = [System.IO.File]::OpenRead((Join-Path $latest.FullName 'frames.rgba'))
    try {
        foreach ($flip in @($false, $true)) {
            $name = if ($flip) { 'first-frame-flipped.png' } else { 'first-frame-native.png' }
            $path = Join-Path $latest.FullName $name
            Export-RgbaFrame $stream $summary $event $path $flip
            Write-Host $path
        }
    } finally { $stream.Dispose() }
    exit
}

if ($Command -eq 'export-event-frames') {
    Add-Type -AssemblyName System.Drawing
    $run = Get-SelectedRun
    $summary = Get-Content -LiteralPath (Join-Path $run.FullName 'summary.json') -Raw | ConvertFrom-Json
    $events = @(Get-Content -LiteralPath (Join-Path $run.FullName 'events.ndjson') | ForEach-Object { $_ | ConvertFrom-Json })
    $captures = @($events | Where-Object type -eq 'capture_written' | Sort-Object { [long]$_.requested_ticks })
    if ($captures.Count -eq 0) { throw 'The run contains no written frame.' }

    $targets = [Collections.Generic.List[object]]::new()
    $ordinal = 0
    foreach ($event in @($events | Where-Object { $_.type -eq 'task_event' -and $_.name -eq 'panel_opened' -and $_.panel -eq 'UITechTree' })) {
        $ordinal++
        $targets.Add([PSCustomObject]@{ Label = 'tech-tree-open'; Ordinal = $ordinal; Event = $event; TargetTicks = [long]$event.ticks + [Diagnostics.Stopwatch]::Frequency / 2; Direction = 'after' })
    }
    $ordinal = 0
    foreach ($event in @($events | Where-Object { $_.type -eq 'task_event' -and $_.name -eq 'panel_closed' -and $_.panel -eq 'UITechTree' })) {
        $ordinal++
        $targets.Add([PSCustomObject]@{ Label = 'tech-tree-closed'; Ordinal = $ordinal; Event = $event; TargetTicks = [long]$event.ticks; Direction = 'after' })
    }
    $ordinal = 0
    foreach ($event in @($events | Where-Object { $_.type -eq 'episode_end' -and $null -ne $_.ticks })) {
        $ordinal++
        $targets.Add([PSCustomObject]@{ Label = 'before-episode-end'; Ordinal = $ordinal; Event = $event; TargetTicks = [long]$event.ticks; Direction = 'before' })
    }
    $ordinal = 0
    foreach ($event in @($events | Where-Object { $_.type -eq 'episode_begin' -and $null -ne $_.ticks })) {
        $ordinal++
        $targets.Add([PSCustomObject]@{ Label = 'after-episode-begin'; Ordinal = $ordinal; Event = $event; TargetTicks = [long]$event.ticks + [Diagnostics.Stopwatch]::Frequency; Direction = 'after' })
    }
    if ($targets.Count -eq 0) { throw 'No exportable tech-tree or episode event exists. This run may predate probe 0.1.9.' }

    $index = [Collections.Generic.List[object]]::new()
    $stream = [System.IO.File]::OpenRead((Join-Path $run.FullName 'frames.rgba'))
    try {
        foreach ($target in $targets) {
            $capture = if ($target.Direction -eq 'before') {
                Find-CaptureAtOrBefore $captures $target.TargetTicks
            } else {
                Find-CaptureAtOrAfter $captures $target.TargetTicks
            }
            if ($null -eq $capture) {
                Write-Warning "No capture found for $($target.Label) event at tick $($target.Event.game_tick)."
                continue
            }
            $name = '{0}-{1:D2}-event-tick-{2}-capture-{3}.png' -f $target.Label, $target.Ordinal, $target.Event.game_tick, $capture.capture_id
            $path = Join-Path $run.FullName $name
            Export-RgbaFrame $stream $summary $capture $path
            $index.Add([PSCustomObject]@{
                label = $target.Label
                event_type = $target.Event.type
                event_name = $target.Event.name
                event_ticks = $target.Event.ticks
                event_unity_frame = $target.Event.unity_frame
                event_game_tick = $target.Event.game_tick
                capture_id = $capture.capture_id
                capture_ticks = $capture.requested_ticks
                capture_unity_frame = $capture.unity_frame
                capture_game_tick = $capture.game_tick
                path = $path
            })
            Write-Host $path
        }
    } finally {
        $stream.Dispose()
    }
    $indexPath = Join-Path $run.FullName 'event-frames.json'
    ConvertTo-Json -InputObject @($index) -Depth 4 | Set-Content -LiteralPath $indexPath -Encoding UTF8
    Write-Host $indexPath
    exit
}

if ($Command -eq 'verify-alignment') {
    $run = Get-SelectedRun
    $events = @(Get-Content -LiteralPath (Join-Path $run.FullName 'events.ndjson') | ForEach-Object { $_ | ConvertFrom-Json })
    $captures = @($events | Where-Object type -eq 'capture_written' | Sort-Object { [long]$_.requested_ticks })
    $inputs = @($events | Where-Object type -eq 'input_sample')
    $tasks = @($events | Where-Object type -eq 'task_event')
    $actions = @($events | Where-Object type -eq 'action_observed')
    $episodes = @($events | Where-Object type -in @('episode_begin', 'episode_end'))
    if ($captures.Count -lt 2) { throw 'At least two written captures are required.' }
    if (@($inputs | Where-Object { $null -eq $_.ticks }).Count -gt 0) { throw 'input_sample lacks ticks. Record a new run with probe 0.1.9 or later.' }
    if (@($tasks | Where-Object { $null -eq $_.ticks }).Count -gt 0) { throw 'task_event lacks ticks. Record a new run with a current probe.' }
    if (@($episodes | Where-Object { $null -eq $_.ticks }).Count -gt 0) { throw 'episode event lacks ticks. Record a new run with probe 0.1.9 or later.' }

    $inputs = @($inputs | Sort-Object { [long]$_.ticks })
    $tasks = @($tasks | Sort-Object { [long]$_.ticks })
    $actions = @($actions | Sort-Object { [long]$_.observed_ticks })
    $episodes = @($episodes | Sort-Object { [long]$_.ticks })
    $errors = [Collections.Generic.List[string]]::new()
    for ($i = 1; $i -lt $captures.Count; $i++) {
        if ([long]$captures[$i].requested_ticks -le [long]$captures[$i - 1].requested_ticks) {
            $errors.Add("Capture request ticks are not strictly increasing at capture $($captures[$i].capture_id).")
        }
    }
    $frameFile = Get-Item -LiteralPath (Join-Path $run.FullName 'frames.rgba')
    foreach ($capture in $captures) {
        if ([long]$capture.file_offset -lt 0 -or [long]$capture.byte_count -le 0 -or [long]$capture.file_offset + [long]$capture.byte_count -gt $frameFile.Length) {
            $errors.Add("Capture $($capture.capture_id) points outside frames.rgba.")
        }
    }

    $firstTicks = [long]$captures[0].requested_ticks
    $lastTicks = [long]$captures[-1].requested_ticks
    $inputIndex = 0
    $taskIndex = 0
    $actionIndex = 0
    $episodeIndex = 0
    $inputPrefix = 0
    $taskPrefix = 0
    $actionPrefix = 0
    $episodePrefix = 0
    while ($inputIndex -lt $inputs.Count -and [long]$inputs[$inputIndex].ticks -lt $firstTicks) { $inputPrefix++; $inputIndex++ }
    while ($taskIndex -lt $tasks.Count -and [long]$tasks[$taskIndex].ticks -lt $firstTicks) { $taskPrefix++; $taskIndex++ }
    while ($actionIndex -lt $actions.Count -and [long]$actions[$actionIndex].observed_ticks -lt $firstTicks) { $actionPrefix++; $actionIndex++ }
    while ($episodeIndex -lt $episodes.Count -and [long]$episodes[$episodeIndex].ticks -lt $firstTicks) { $episodePrefix++; $episodeIndex++ }

    $assignedInputs = 0
    $assignedTasks = 0
    $assignedActions = 0
    $assignedEpisodes = 0
    $manifestPath = Join-Path $run.FullName 'alignment-manifest.ndjson'
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $writer = New-Object System.IO.StreamWriter($manifestPath, $false, $utf8)
    try {
        for ($pairIndex = 0; $pairIndex -lt $captures.Count - 1; $pairIndex++) {
            $current = $captures[$pairIndex]
            $next = $captures[$pairIndex + 1]
            $endTicks = [long]$next.requested_ticks
            $intervalInputs = [Collections.Generic.List[object]]::new()
            $intervalTasks = [Collections.Generic.List[object]]::new()
            $intervalActions = [Collections.Generic.List[object]]::new()
            $intervalEpisodes = [Collections.Generic.List[object]]::new()
            while ($inputIndex -lt $inputs.Count -and [long]$inputs[$inputIndex].ticks -lt $endTicks) {
                $input = $inputs[$inputIndex]
                $intervalInputs.Add([ordered]@{
                    ticks = $input.ticks
                    unity_frame = $input.unity_frame
                    game_tick = $input.game_tick
                    down = $input.down
                    up = $input.up
                    mouse_dx = $input.mouse_dx
                    mouse_dy = $input.mouse_dy
                    wheel = $input.wheel
                    mouse0 = $input.mouse0
                    mouse1 = $input.mouse1
                    mouse2 = $input.mouse2
                })
                $assignedInputs++; $inputIndex++
            }
            while ($taskIndex -lt $tasks.Count -and [long]$tasks[$taskIndex].ticks -lt $endTicks) {
                $intervalTasks.Add($tasks[$taskIndex])
                $assignedTasks++; $taskIndex++
            }
            while ($actionIndex -lt $actions.Count -and [long]$actions[$actionIndex].observed_ticks -lt $endTicks) {
                $intervalActions.Add($actions[$actionIndex])
                $assignedActions++; $actionIndex++
            }
            while ($episodeIndex -lt $episodes.Count -and [long]$episodes[$episodeIndex].ticks -lt $endTicks) {
                $intervalEpisodes.Add($episodes[$episodeIndex])
                $assignedEpisodes++; $episodeIndex++
            }
            $row = [ordered]@{
                transition_index = $pairIndex
                observation = [ordered]@{
                    capture_id = $current.capture_id
                    file_offset = $current.file_offset
                    byte_count = $current.byte_count
                    requested_ticks = $current.requested_ticks
                    unity_frame = $current.unity_frame
                    game_tick = $current.game_tick
                }
                next_observation = [ordered]@{
                    capture_id = $next.capture_id
                    file_offset = $next.file_offset
                    byte_count = $next.byte_count
                    requested_ticks = $next.requested_ticks
                    unity_frame = $next.unity_frame
                    game_tick = $next.game_tick
                }
                action_input_samples = @($intervalInputs)
                observed_injected_actions = @($intervalActions)
                next_state_events = @($intervalTasks)
                episode_events = @($intervalEpisodes)
            }
            $writer.WriteLine(($row | ConvertTo-Json -Compress -Depth 7))
        }
    } finally {
        $writer.Dispose()
    }

    $inputTail = $inputs.Count - $inputIndex
    $taskTail = $tasks.Count - $taskIndex
    $actionTail = $actions.Count - $actionIndex
    $episodeTail = $episodes.Count - $episodeIndex
    if ($taskPrefix -gt 0) { $errors.Add("$taskPrefix task events occurred before the first observation.") }
    if ($taskTail -gt 0) { $errors.Add("$taskTail task events have no following observation.") }
    if ($actionPrefix -gt 0) { $errors.Add("$actionPrefix observed injected actions occurred before the first observation.") }
    if ($actionTail -gt 0) { $errors.Add("$actionTail observed injected actions have no following observation.") }

    $episodeBegins = @($episodes | Where-Object type -eq 'episode_begin')
    $episodeEnds = @($episodes | Where-Object type -eq 'episode_end')
    $validResetPairs = 0
    foreach ($begin in $episodeBegins) {
        if (@($episodeEnds | Where-Object { [long]$_.ticks -lt [long]$begin.ticks }).Count -gt 0) { $validResetPairs++ }
    }
    $postResetTaskEvents = if ($episodeBegins.Count -eq 0) { 0 } else {
        $lastBeginTicks = [long]($episodeBegins | Sort-Object { [long]$_.ticks } | Select-Object -Last 1).ticks
        @($tasks | Where-Object { [long]$_.ticks -gt $lastBeginTicks }).Count
    }
    $worldResetVerdict = if ($episodeBegins.Count -eq 0 -and $episodeEnds.Count -eq 0) {
        'not_tested'
    } elseif ($validResetPairs -gt 0 -and $postResetTaskEvents -gt 0) {
        'pass'
    } else {
        'fail'
    }
    $alignmentVerdict = if ($errors.Count -eq 0) { 'pass' } else { 'fail' }
    $alignmentSummary = [ordered]@{
        alignment_verdict = $alignmentVerdict
        world_reset_verdict = $worldResetVerdict
        capture_count = $captures.Count
        transition_count = $captures.Count - 1
        input_samples_assigned = $assignedInputs
        task_events_assigned = $assignedTasks
        observed_actions_assigned = $assignedActions
        episode_events_assigned = $assignedEpisodes
        input_prefix_excluded = $inputPrefix
        input_tail_excluded = $inputTail
        task_prefix_unpaired = $taskPrefix
        task_tail_unpaired = $taskTail
        action_prefix_unpaired = $actionPrefix
        action_tail_unpaired = $actionTail
        episode_prefix_excluded = $episodePrefix
        episode_tail_excluded = $episodeTail
        episode_begin_count = $episodeBegins.Count
        episode_end_count = $episodeEnds.Count
        valid_reset_pairs = $validResetPairs
        post_reset_task_events = $postResetTaskEvents
        first_capture_ticks = $firstTicks
        last_capture_ticks = $lastTicks
        errors = @($errors)
        manifest = $manifestPath
    }
    $summaryPath = Join-Path $run.FullName 'alignment-summary.json'
    $alignmentSummary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    $alignmentSummary | Format-List
    Write-Host $summaryPath
    Write-Host $manifestPath
    if ($alignmentVerdict -ne 'pass') { throw "Alignment verification failed. See $summaryPath" }
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
