param(
    [Parameter(Mandatory = $true)]
    [string]$CurrentDistro
)

$ErrorActionPreference = "Stop"

$settingsPath = Join-Path $env:APPDATA 'Docker\settings-store.json'
if (!(Test-Path $settingsPath)) {
    $settingsPath = Join-Path $env:APPDATA 'Docker\settings.json'
}
if (!(Test-Path $settingsPath)) {
    throw "Docker settings dosyası bulunamadı."
}

Copy-Item $settingsPath "$settingsPath.bak" -Force

if (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue) {
    Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe' -ArgumentList '--quit' -WindowStyle Hidden -ErrorAction SilentlyContinue
    $stopped = $false
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Seconds 1
        if (!(Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            $stopped = $true
            break
        }
    }
    if (-not $stopped) {
        Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 3
    }
}

$rawJson = Get-Content $settingsPath -Raw
$rawJson = $rawJson.TrimStart([char]0xFEFF)
$rawJson = $rawJson -replace "`r", ""
$cfg = $rawJson | ConvertFrom-Json

# Docker Desktop 29.x+ schema compatibility:
# - integratedWslDistros (legacy/current flat list)
# - integration.wslDistros (nested map or list)
# - EnableIntegrationWithDefaultWslDistro / enableIntegrationWithDefaultWslDistro / wslEngineEnabled / integration.wslEngineEnabled
$prop = $cfg.PSObject.Properties | Where-Object { $_.Name -ieq 'integratedWslDistros' -or $_.Name -ieq 'IntegratedWslDistros' } | Select-Object -First 1
if ($null -eq $prop) {
    $cfg | Add-Member -NotePropertyName 'integratedWslDistros' -NotePropertyValue @() -Force
    $propName = 'integratedWslDistros'
}
else {
    $propName = $prop.Name
}

$list = @($cfg.$propName)
if ($list -notcontains $CurrentDistro) {
    $list += $CurrentDistro
}
$cfg.$propName = $list

if ($null -eq $cfg.integration) {
    $cfg | Add-Member -NotePropertyName 'integration' -NotePropertyValue ([pscustomobject]@{}) -Force
}
if ($null -eq $cfg.integration.wslDistros) {
    $cfg.integration | Add-Member -NotePropertyName 'wslDistros' -NotePropertyValue ([pscustomobject]@{}) -Force
}
if ($cfg.integration.wslDistros -isnot [System.Collections.IDictionary] -and $cfg.integration.wslDistros -isnot [pscustomobject]) {
    $cfg.integration.wslDistros = [pscustomobject]@{}
}
$cfg.integration.wslDistros | Add-Member -NotePropertyName $CurrentDistro -NotePropertyValue $true -Force

if ($null -eq $cfg.EnableIntegrationWithDefaultWslDistro) { $cfg | Add-Member -NotePropertyName 'EnableIntegrationWithDefaultWslDistro' -NotePropertyValue $true -Force } else { $cfg.EnableIntegrationWithDefaultWslDistro = $true }
if ($null -eq $cfg.enableIntegrationWithDefaultWslDistro) { $cfg | Add-Member -NotePropertyName 'enableIntegrationWithDefaultWslDistro' -NotePropertyValue $true -Force } else { $cfg.enableIntegrationWithDefaultWslDistro = $true }
if ($null -eq $cfg.wslEngineEnabled) { $cfg | Add-Member -NotePropertyName 'wslEngineEnabled' -NotePropertyValue $true -Force } else { $cfg.wslEngineEnabled = $true }
if ($null -eq $cfg.integration.wslEngineEnabled) { $cfg.integration | Add-Member -NotePropertyName 'wslEngineEnabled' -NotePropertyValue $true -Force } else { $cfg.integration.wslEngineEnabled = $true }
[System.IO.File]::WriteAllText($settingsPath, ($cfg | ConvertTo-Json -Depth 100), (New-Object System.Text.UTF8Encoding $false))

# Post-write verification (file-level): ensure the distro is persisted.
$verifyRawJson = Get-Content $settingsPath -Raw
$verifyRawJson = $verifyRawJson.TrimStart([char]0xFEFF)
$verifyRawJson = $verifyRawJson -replace "`r", ""
$verifyCfg = $verifyRawJson | ConvertFrom-Json
$verifyProp = $verifyCfg.PSObject.Properties | Where-Object { $_.Name -ieq 'integratedWslDistros' -or $_.Name -ieq 'IntegratedWslDistros' } | Select-Object -First 1
if ($null -eq $verifyProp) {
    throw "Doğrulama başarısız: integratedWslDistros alanı yazım sonrası bulunamadı."
}
$verifyList = @($verifyCfg.($verifyProp.Name))
if ($verifyList -notcontains $CurrentDistro) {
    throw "Doğrulama başarısız: integratedWslDistros içinde '$CurrentDistro' bulunamadı."
}
if ($null -eq $verifyCfg.integration -or $null -eq $verifyCfg.integration.wslDistros) {
    throw "Doğrulama başarısız: integration.wslDistros alanı yazım sonrası bulunamadı."
}
$verifyNested = $verifyCfg.integration.wslDistros
if ($verifyNested -is [System.Array]) {
    if (@($verifyNested) -notcontains $CurrentDistro) {
        throw "Doğrulama başarısız: integration.wslDistros array içinde '$CurrentDistro' bulunamadı."
    }
}
elseif ($verifyNested.PSObject.Properties.Name -notcontains $CurrentDistro) {
    throw "Doğrulama başarısız: integration.wslDistros map içinde '$CurrentDistro' bulunamadı."
}

Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe' -WindowStyle Hidden
