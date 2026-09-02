param(
    [ValidateSet('build', 'deploy', 'show-latest', 'export-frame', 'export-event-frames', 'verify-alignment', 'verify-microtasks')]
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
    if ($null -ne $Event.machine_kind) { $parts.Add("機器類型 $($Event.machine_kind)") }
    if ($null -ne $Event.previous_mode) { $parts.Add("模式 $($Event.previous_mode) → $($Event.mode)") }
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
            if ($capture.PSObject.Properties.Name -contains 'cursor_composited' -and -not $capture.cursor_composited) {
                Write-Warning "Capture $($capture.capture_id) did not composite a cursor."
            }
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
                cursor_visible = $capture.cursor_visible
                cursor_composited = $capture.cursor_composited
                cursor_composited_pixels = $capture.cursor_composited_pixels
                cursor_x = $capture.cursor_x
                cursor_y = $capture.cursor_y
                cursor_index = $capture.cursor_index
                cursor_glyph_source = $capture.cursor_glyph_source
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

if ($Command -eq 'verify-microtasks') {
    $run = Get-SelectedRun
    $events = @(Get-Content -LiteralPath (Join-Path $run.FullName 'events.ndjson') | ForEach-Object { $_ | ConvertFrom-Json })
    $catalog = $events | Where-Object type -eq 'microtask_catalog' | Select-Object -First 1
    if ($null -eq $catalog) { throw 'microtask_catalog is missing. Record a new run with probe 0.1.11 or later.' }
    $snapshots = @($events | Where-Object type -eq 'microtask_state_snapshot' | Sort-Object { [long]$_.ticks })
    $tasks = @($events | Where-Object type -eq 'task_event' | Sort-Object { [long]$_.ticks })
    $startSnapshot = $snapshots | Select-Object -First 1
    $endSnapshot = $snapshots | Select-Object -Last 1
    $results = [Collections.Generic.List[object]]::new()

    function Test-IdList($Value, [int]$Expected) {
        if ($null -eq $Value) { return $false }
        return @(([string]$Value -split ',') | Where-Object { [int]$_ -eq $Expected }).Count -gt 0
    }

    function Get-SnapshotValue($Snapshot, [string]$Property) {
        if ($null -eq $Snapshot) { return $null }
        $entry = $Snapshot.PSObject.Properties[$Property]
        if ($null -eq $entry) { return $null }
        return $entry.Value
    }

    function Add-Result([int]$Task, [string]$Name, [string]$Verdict, [string]$Signal, [string]$Evidence, [string]$Fallback) {
        $results.Add([ordered]@{
            task = $Task
            name = $Name
            verdict = $Verdict
            signal = $Signal
            evidence = $Evidence
            fallback = $Fallback
        })
    }

    function Add-TechResult([int]$Task, [string]$Name, [string]$CatalogProperty, [string]$SnapshotProperty) {
        $techId = [int]$catalog.PSObject.Properties[$CatalogProperty].Value
        if ($techId -le 0) {
            Add-Result $Task $Name 'catalog_unresolved' 'none' 'The target tech could not be resolved from its unlock rewards.' 'Resolve the TechProto ID, then read GameHistoryData.TechUnlocked(id).'
            return
        }
        $unlock = $tasks | Where-Object { $_.name -eq 'tech_unlocked' -and [int]$_.tech_id -eq $techId } | Select-Object -First 1
        if ($null -ne $unlock) {
            Add-Result $Task $Name 'pass_direct_event' 'GameHistoryData.onTechUnlocked' "tech $techId $($unlock.tech_name), tick $($unlock.game_tick)" 'Poll GameHistoryData.TechUnlocked(id).'
            return
        }
        $startValue = Get-SnapshotValue $startSnapshot $SnapshotProperty
        $endValue = Get-SnapshotValue $endSnapshot $SnapshotProperty
        if ($startValue -eq $false -and $endValue -eq $true) {
            Add-Result $Task $Name 'pass_state_fallback' 'GameHistoryData.TechUnlocked' "false -> true for tech $techId" 'No weaker fallback is needed.'
        } elseif ($startValue -eq $true) {
            Add-Result $Task $Name 'already_complete_at_start' 'GameHistoryData.TechUnlocked' "tech $techId was already unlocked" 'Start from a baseline where the tech is locked.'
        } else {
            Add-Result $Task $Name 'not_observed' 'GameHistoryData.TechUnlocked' "tech $techId was not observed unlocked" 'Use onTechUnlocked or poll TechUnlocked(id) after the action.'
        }
    }

    function Find-Batch([int]$ProductId, [string]$MachineKind) {
        return $tasks | Where-Object {
            $_.name -eq 'machine_batch_completed' -and
            ($MachineKind -eq '' -or $_.machine_kind -eq $MachineKind) -and
            $_.powered -eq $true -and
            (Test-IdList $_.product_ids $ProductId)
        } | Select-Object -First 1
    }

    function Find-AutomatedBatch([int]$ProductId, [int[]]$RequiredItems, [string]$MachineKind, [int[]]$ExcludedEntities) {
        $candidates = @($tasks | Where-Object {
            $_.name -eq 'machine_batch_completed' -and
            $_.machine_kind -eq $MachineKind -and
            $_.powered -eq $true -and
            (Test-IdList $_.product_ids $ProductId)
        })
        foreach ($batch in $candidates) {
            if ($ExcludedEntities -contains [int]$batch.entity_id) { continue }
            $deliveries = @($tasks | Where-Object {
                $_.name -eq 'sorter_delivered' -and
                [int]$_.target_entity_id -eq [int]$batch.entity_id -and
                [int]$_.target_recipe_id -eq [int]$batch.recipe_id -and
                [long]$_.ticks -le [long]$batch.ticks
            })
            $allFound = $true
            foreach ($required in $RequiredItems) {
                if (@($deliveries | Where-Object { [int]$_.item_id -eq $required }).Count -eq 0) {
                    $allFound = $false
                    break
                }
            }
            if ($allFound) {
                return [pscustomobject]@{ Batch = $batch; Deliveries = $deliveries }
            }
        }
        return $null
    }

    $capsuleEvent = $tasks | Where-Object name -eq 'landing_capsule_dismantled' | Select-Object -First 1
    if ($null -ne $capsuleEvent) {
        Add-Result 1 '回收登陸艙' 'pass_direct_event' 'PlanetFactory.RemoveVegeWithComponents' "vegetation $($capsuleEvent.vege_id), tick $($capsuleEvent.game_tick)" 'Confirm the capsule count changes from one to zero.'
    } else {
        $startCapsules = Get-SnapshotValue $startSnapshot 'capsule_count'
        $endCapsules = Get-SnapshotValue $endSnapshot 'capsule_count'
        if ([int]$startCapsules -gt 0 -and [int]$endCapsules -eq 0) {
            Add-Result 1 '回收登陸艙' 'pass_state_fallback' 'factory.vegePool' "$startCapsules -> $endCapsules capsules" 'The item reward is weaker evidence and should only be diagnostic.'
        } elseif ([int]$startCapsules -eq 0) {
            Add-Result 1 '回收登陸艙' 'already_complete_at_start' 'factory.vegePool' 'No landing capsule existed at the first snapshot.' 'Start from the controlled new-game baseline.'
        } else {
            Add-Result 1 '回收登陸艙' 'not_observed' 'factory.vegePool' "capsules $startCapsules -> $endCapsules" 'Confirm the capsule count changes from one to zero.'
        }
    }

    Add-TechResult 2 '完成電磁學' 'tech_electromagnetism_id' 'tech_electromagnetism_unlocked'

    foreach ($miningTask in @(
        [pscustomobject]@{ Task = 3; Name = '自動採集鐵礦'; Item = 1001 },
        [pscustomobject]@{ Task = 4; Name = '自動採集銅礦'; Item = 1002 }
    )) {
        $mining = $tasks | Where-Object { $_.name -eq 'miner_produced' -and [int]$_.item_id -eq $miningTask.Item -and $_.powered -eq $true } | Select-Object -First 1
        if ($null -ne $mining) {
            Add-Result $miningTask.Task $miningTask.Name 'pass_component_event' 'MinerComponent.InternalUpdate' "entity $($mining.entity_id), $($mining.item_name) x$($mining.item_count), power $($mining.power)" 'Poll productRegister delta while a matching powered MinerComponent is active.'
        } else {
            Add-Result $miningTask.Task $miningTask.Name 'not_observed' 'MinerComponent.InternalUpdate' "item $($miningTask.Item) production was not observed" 'A vein amount decrease plus a powered matching miner is weaker but usable.'
        }
    }

    Add-TechResult 5 '完成自動化冶金' 'tech_automatic_metallurgy_id' 'tech_automatic_metallurgy_unlocked'

    foreach ($productionTask in @(
        [pscustomobject]@{ Task = 6; Name = '用熔爐生產磁鐵'; Product = 1102 },
        [pscustomobject]@{ Task = 7; Name = '用熔爐生產鐵塊'; Product = 1101 },
        [pscustomobject]@{ Task = 8; Name = '用熔爐生產銅塊'; Product = 1104 }
    )) {
        $batch = Find-Batch $productionTask.Product 'assembler'
        if ($null -ne $batch -and $batch.recipe_type -eq 'Smelt') {
            Add-Result $productionTask.Task $productionTask.Name 'pass_component_event' 'AssemblerComponent.cycleCount' "entity $($batch.entity_id), recipe $($batch.recipe_id) $($batch.recipe_name), tick $($batch.game_tick)" 'Poll cycleCount for the same entity and recipe; productRegister is less specific.'
        } else {
            Add-Result $productionTask.Task $productionTask.Name 'not_observed' 'AssemblerComponent.cycleCount' "smelting product $($productionTask.Product) was not observed" 'Poll cycleCount for the same entity and recipe.'
        }
    }

    Add-TechResult 9 '完成基礎物流系統' 'tech_basic_logistics_id' 'tech_basic_logistics_unlocked'

    $autoMagnet = Find-AutomatedBatch 1102 @(1001) 'assembler' @()
    $autoIron = Find-AutomatedBatch 1101 @(1001) 'assembler' @()
    $autoCopper = Find-AutomatedBatch 1104 @(1002) 'assembler' @()
    $smelterEntities = @()
    foreach ($candidate in @($autoMagnet, $autoIron, $autoCopper)) {
        if ($null -ne $candidate) { $smelterEntities += [int]$candidate.Batch.entity_id }
    }
    if ($null -ne $autoMagnet -and $null -ne $autoIron -and $null -ne $autoCopper -and @($smelterEntities | Select-Object -Unique).Count -eq 3) {
        Add-Result 10 '建立自動熔煉' 'pass_correlated_events' 'sorter_delivered + machine_batch_completed' "smelter entities $($smelterEntities -join ',')" 'Require three distinct fixed-recipe smelters with matching input-served and cycle-count transitions.'
    } else {
        Add-Result 10 '建立自動熔煉' 'not_observed' 'sorter_delivered + machine_batch_completed' "qualified smelter entities $($smelterEntities -join ',')" 'A snapshot of connected sorters, served inputs and increased cycleCount is usable but may miss historical delivery.'
    }

    Add-TechResult 11 '完成基礎製造' 'tech_basic_manufacturing_id' 'tech_basic_manufacturing_unlocked'

    $autoCoil = Find-AutomatedBatch 1202 @(1102, 1104) 'assembler' @()
    if ($null -ne $autoCoil) {
        Add-Result 12 '自動生產磁線圈' 'pass_correlated_events' 'sorter_delivered + machine_batch_completed' "assembler entity $($autoCoil.Batch.entity_id), recipe $($autoCoil.Batch.recipe_id)" 'Check served inputs and cycleCount on a fixed-recipe assembler with connected input sorters.'
    } else {
        Add-Result 12 '自動生產磁線圈' 'not_observed' 'sorter_delivered + machine_batch_completed' 'No qualified assembler completed the recipe.' 'Check served inputs and cycleCount on a fixed-recipe assembler.'
    }

    $excludedAssembler = if ($null -eq $autoCoil) { @() } else { @([int]$autoCoil.Batch.entity_id) }
    $autoBoard = Find-AutomatedBatch 1301 @(1101, 1104) 'assembler' $excludedAssembler
    if ($null -ne $autoBoard) {
        Add-Result 13 '自動生產電路板' 'pass_correlated_events' 'sorter_delivered + machine_batch_completed' "assembler entity $($autoBoard.Batch.entity_id), recipe $($autoBoard.Batch.recipe_id)" 'Check served inputs and cycleCount on another fixed-recipe assembler.'
    } else {
        Add-Result 13 '自動生產電路板' 'not_observed' 'sorter_delivered + machine_batch_completed' 'No distinct qualified assembler completed the recipe.' 'Check served inputs and cycleCount on another fixed-recipe assembler.'
    }

    Add-TechResult 14 '完成電磁矩陣科技' 'tech_electromagnetic_matrix_id' 'tech_electromagnetic_matrix_unlocked'

    $labSupply = $null
    $labDeliveries = @($tasks | Where-Object {
        $_.name -eq 'sorter_delivered' -and $_.target_kind -eq 'lab' -and
        $_.powered -eq $true -and (Test-IdList $_.target_product_ids 6001)
    })
    foreach ($delivery in $labDeliveries) {
        $sameLab = @($labDeliveries | Where-Object {
            [int]$_.target_entity_id -eq [int]$delivery.target_entity_id -and
            [int]$_.target_recipe_id -eq [int]$delivery.target_recipe_id
        })
        if (@($sameLab | Where-Object { [int]$_.item_id -eq 1202 }).Count -gt 0 -and
            @($sameLab | Where-Object { [int]$_.item_id -eq 1301 }).Count -gt 0) {
            $labSupply = [pscustomobject]@{
                EntityId = [int]$delivery.target_entity_id
                RecipeId = [int]$delivery.target_recipe_id
                LastTicks = [long](($sameLab | Sort-Object { [long]$_.ticks } | Select-Object -Last 1).ticks)
            }
            break
        }
    }
    if ($null -ne $labSupply) {
        Add-Result 15 '自動供應矩陣研究站' 'pass_correlated_events' 'LabComponent.recipeId + sorter_delivered' "lab entity $($labSupply.EntityId), recipe $($labSupply.RecipeId)" 'Poll the selected recipe and served[] deltas; a static connection alone cannot prove delivery.'
    } else {
        Add-Result 15 '自動供應矩陣研究站' 'not_observed' 'LabComponent.recipeId + sorter_delivered' 'No lab received both required items through sorters.' 'Poll the selected recipe and served[] deltas.'
    }

    $matrixBatch = $null
    if ($null -ne $labSupply) {
        $matrixBatch = $tasks | Where-Object {
            $_.name -eq 'machine_batch_completed' -and $_.machine_kind -eq 'lab' -and
            [int]$_.entity_id -eq $labSupply.EntityId -and [int]$_.recipe_id -eq $labSupply.RecipeId -and
            [long]$_.ticks -ge $labSupply.LastTicks -and $_.powered -eq $true -and
            (Test-IdList $_.product_ids 6001)
        } | Select-Object -First 1
    }
    if ($null -ne $matrixBatch) {
        Add-Result 16 '生產第一個電磁矩陣' 'pass_correlated_events' 'LabComponent.cycleCount' "lab entity $($matrixBatch.entity_id), recipe $($matrixBatch.recipe_id), tick $($matrixBatch.game_tick)" 'Poll cycleCount or produced[] for the same matrix-mode lab and recipe.'
    } else {
        Add-Result 16 '生產第一個電磁矩陣' 'not_observed' 'LabComponent.cycleCount' 'No supplied lab completed an electromagnetic matrix batch.' 'Poll cycleCount or produced[] for the same matrix-mode lab and recipe.'
    }

    $passed = @($results | Where-Object { $_.verdict -like 'pass_*' }).Count
    $overall = if ($passed -eq 16) { 'pass' } else { 'incomplete_or_fail' }
    $report = [ordered]@{
        verdict = $overall
        passed = $passed
        total = 16
        run = $run.FullName
        results = @($results)
    }
    $reportPath = Join-Path $run.FullName 'microtask-verdicts.json'
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    $results | ForEach-Object { [pscustomobject]$_ } | Format-Table task, name, verdict, signal -AutoSize
    Write-Host "$passed / 16 microtasks passed"
    Write-Host $reportPath
    if ($overall -ne 'pass') { throw "Microtask verification is incomplete. See $reportPath" }
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
