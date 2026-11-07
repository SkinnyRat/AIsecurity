#!/usr/bin/env pwsh

$ErrorActionPreference = "Stop"

function Stop-WithMessage([string]$Message) {
    Write-Error $Message
    exit 1
}

function Invoke-GitCapture([string[]]$Arguments) {
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $git.Source @Arguments 2>&1)
        $script:GitExitCode = $LASTEXITCODE
        return $output
    } finally {
        $ErrorActionPreference = $savedPreference
    }
}

$pluginRoot = $PSScriptRoot
$patchPath = Join-Path $pluginRoot "patches\openharness-bare-plugin-commands.patch"
$pluginSource = Join-Path $pluginRoot ".openharness\plugins\dependency_audit"

if (-not (Test-Path -LiteralPath $patchPath -PathType Leaf)) {
    Stop-WithMessage "Patch not found: $patchPath"
}
if (-not (Test-Path -LiteralPath $pluginSource -PathType Container)) {
    Stop-WithMessage "Plugin folder not found: $pluginSource"
}

do {
    $openHarnessInput = Read-Host "Path to your OpenHarness checkout"
    if ([string]::IsNullOrWhiteSpace($openHarnessInput)) {
        Write-Host "Enter the path to the OpenHarness checkout."
    }
} while ([string]::IsNullOrWhiteSpace($openHarnessInput))

$openHarnessPath = (Resolve-Path -LiteralPath $openHarnessInput -ErrorAction SilentlyContinue).Path
if (-not $openHarnessPath -or -not (Test-Path -LiteralPath (Join-Path $openHarnessPath ".git"))) {
    Stop-WithMessage "That path is not a Git checkout: $openHarnessInput"
}

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) { Stop-WithMessage "Git is required but was not found on PATH." }

$reverseOutput = Invoke-GitCapture @("-C", $openHarnessPath, "apply", "--reverse", "--check", $patchPath)
if ($script:GitExitCode -eq 0) {
    Write-Host "OpenHarness patch is already applied."
} else {
    $checkOutput = Invoke-GitCapture @("-C", $openHarnessPath, "apply", "--check", $patchPath)
    if ($script:GitExitCode -ne 0) {
        if ($checkOutput) { $checkOutput | ForEach-Object { Write-Host $_ } }
        Stop-WithMessage "Patch does not apply cleanly. Confirm this checkout uses the supported upstream revision and has no conflicting edits."
    }
    $applyOutput = Invoke-GitCapture @("-C", $openHarnessPath, "apply", $patchPath)
    if ($script:GitExitCode -ne 0) {
        if ($applyOutput) { $applyOutput | ForEach-Object { Write-Host $_ } }
        Stop-WithMessage "Failed to apply OpenHarness patch."
    }
    Write-Host "Applied OpenHarness patch."
}

$pluginDestinationRoot = Join-Path $openHarnessPath ".openharness\plugins"
$pluginDestination = Join-Path $pluginDestinationRoot "dependency_audit"
New-Item -ItemType Directory -Force -Path $pluginDestinationRoot | Out-Null
if (Test-Path -LiteralPath $pluginDestination) {
    $answer = Read-Host "Plugin already exists at '$pluginDestination'. Replace it? [y/N]"
    if ($answer -notmatch '^(y|yes)$') { Stop-WithMessage "Setup cancelled before replacing the existing plugin." }
    Remove-Item -LiteralPath $pluginDestination -Recurse -Force
}
Copy-Item -LiteralPath $pluginSource -Destination $pluginDestination -Recurse
Get-ChildItem -LiteralPath $pluginDestination -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $pluginDestination -Recurse -File -Filter *.pyc | Remove-Item -Force

# OpenHarness loads plugin enablement from its user config (~/.openharness/settings.json).
$configDir = Join-Path $HOME ".openharness"
$settingsPath = Join-Path $configDir "settings.json"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
    try { $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json }
    catch { Stop-WithMessage "Could not parse existing settings JSON at '$settingsPath': $($_.Exception.Message)" }
    if ($null -eq $settings -or $settings -isnot [pscustomobject]) {
        Stop-WithMessage "Settings file must contain a JSON object: $settingsPath"
    }
} else {
    $settings = [pscustomobject]@{}
}

if ($settings.PSObject.Properties.Name -contains "allow_project_plugins") {
    $settings.allow_project_plugins = $true
} else {
    $settings | Add-Member -NotePropertyName allow_project_plugins -NotePropertyValue $true
}
if ($settings.PSObject.Properties.Name -contains "enabled_plugins") {
    if ($null -eq $settings.enabled_plugins) { $settings.enabled_plugins = [pscustomobject]@{} }
} else {
    $settings | Add-Member -NotePropertyName enabled_plugins -NotePropertyValue ([pscustomobject]@{})
}
if ($settings.enabled_plugins -isnot [pscustomobject]) {
    Stop-WithMessage "'enabled_plugins' in settings must be a JSON object."
}
if ($settings.enabled_plugins.PSObject.Properties.Name -contains "dependency_audit") {
    $settings.enabled_plugins.dependency_audit = $true
} else {
    $settings.enabled_plugins | Add-Member -NotePropertyName dependency_audit -NotePropertyValue $true
}

$settingsJson = $settings | ConvertTo-Json -Depth 100
$utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($settingsPath, $settingsJson, $utf8WithoutBom)
Write-Host "Enabled project plugins and dependency_audit in $settingsPath"
Write-Host "Setup complete. Start OpenHarness from: $openHarnessPath"
