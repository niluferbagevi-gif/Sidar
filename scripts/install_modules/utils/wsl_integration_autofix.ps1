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

$cfg = Get-Content $settingsPath -Raw | ConvertFrom-Json
$prop = $cfg.PSObject.Properties | Where-Object { $_.Name -ieq 'integratedWslDistros' } | Select-Object -First 1
if ($null -eq $prop) {
    $cfg | Add-Member -NotePropertyName 'integratedWslDistros' -NotePropertyValue @() -Force
    $propName = 'integratedWslDistros'
} else {
    $propName = $prop.Name
}

$list = @($cfg.$propName)
if ($list -notcontains $CurrentDistro) {
    $list += $CurrentDistro
}
$cfg.$propName = $list
[System.IO.File]::WriteAllText($settingsPath, ($cfg | ConvertTo-Json -Depth 100), (New-Object System.Text.UTF8Encoding $false))

# Post-write verification (file-level): ensure the distro is persisted.
$verifyCfg = Get-Content $settingsPath -Raw | ConvertFrom-Json
$verifyProp = $verifyCfg.PSObject.Properties | Where-Object { $_.Name -ieq 'integratedWslDistros' } | Select-Object -First 1
if ($null -eq $verifyProp) {
    throw "Doğrulama başarısız: integratedWslDistros alanı yazım sonrası bulunamadı."
}
$verifyList = @($verifyCfg.($verifyProp.Name))
if ($verifyList -notcontains $CurrentDistro) {
    throw "Doğrulama başarısız: integratedWslDistros içinde '$CurrentDistro' bulunamadı."
}

Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe' -WindowStyle Hidden
