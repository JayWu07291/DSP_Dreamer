param(
    [ValidateSet('all', 'world_model', 'agent_finetune', 'imagination')]
    [string]$Stage = 'all'
)

$ErrorActionPreference = 'Stop'
$prototypeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $prototypeRoot '..\..')
$runtimePython = 'C:\Users\jay07\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$venvRoot = Join-Path $repoRoot 'tmp\issue-6-venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    & $runtimePython -m venv $venvRoot
}

& $venvPython -c 'import numpy' 2>$null
if ($LASTEXITCODE -ne 0) {
    & $venvPython -m pip install numpy
}

& $venvPython -c 'import torch' 2>$null
if ($LASTEXITCODE -ne 0) {
    & $venvPython -m pip install --index-url https://download.pytorch.org/whl/cu128 torch==2.9.0
}

& $venvPython (Join-Path $prototypeRoot 'prototype.py') `
    --stage $Stage `
    --output (Join-Path $prototypeRoot 'measured_rtx5070.json')
