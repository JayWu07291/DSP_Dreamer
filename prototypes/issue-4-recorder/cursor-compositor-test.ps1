$ErrorActionPreference = 'Stop'

Add-Type -Path (Join-Path $PSScriptRoot 'CursorCompositor.cs')

$width = 8
$height = 6
$frame = New-Object byte[] ($width * $height * 4)
for ($offset = 0; $offset -lt $frame.Length; $offset += 4) {
    $frame[$offset] = 10
    $frame[$offset + 1] = 20
    $frame[$offset + 2] = 30
    $frame[$offset + 3] = 255
}

$glyph = [DSPDreamer.CaptureProbe.CursorGlyph]::new(2, 2, [byte[]]@(
    255, 255, 255, 255,  0, 0, 0, 0,
    0, 0, 0, 255,          250, 10, 20, 128
))

$changed = [DSPDreamer.CaptureProbe.CursorCompositor]::Composite($frame, $width, $height, $glyph, 2, 1, 4, 4)
if ($changed -ne 12) { throw "Expected 12 composited pixels, got $changed." }

$whiteOffset = 4 * (1 * $width + 2)
if ($frame[$whiteOffset] -ne 255 -or $frame[$whiteOffset + 1] -ne 255 -or $frame[$whiteOffset + 2] -ne 255) {
    throw 'Opaque white cursor pixel was not copied.'
}

$transparentOffset = 4 * (1 * $width + 4)
if ($frame[$transparentOffset] -ne 10 -or $frame[$transparentOffset + 1] -ne 20 -or $frame[$transparentOffset + 2] -ne 30) {
    throw 'Transparent cursor pixel changed the frame.'
}

$redOffset = 4 * (3 * $width + 4)
if ($frame[$redOffset] -ne 130 -or $frame[$redOffset + 1] -ne 15 -or $frame[$redOffset + 2] -ne 25) {
    throw "Half-alpha cursor pixel blended incorrectly: $($frame[$redOffset]),$($frame[$redOffset + 1]),$($frame[$redOffset + 2])."
}

$clipped = [DSPDreamer.CaptureProbe.CursorCompositor]::Composite($frame, $width, $height, $glyph, -3, -3, 4, 4)
if ($clipped -ne 1) { throw "Expected one clipped cursor pixel, got $clipped." }

Write-Host 'Cursor compositor regression test: PASS'
