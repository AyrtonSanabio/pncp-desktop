param(
    [string]$ApplicationDirectory = "$PSScriptRoot\..\dist\ConsultaPNCP"
)

$ErrorActionPreference = "Stop"
$applicationDirectory = [System.IO.Path]::GetFullPath($ApplicationDirectory)
$executable = Join-Path $applicationDirectory "ConsultaPNCP.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Executavel nao encontrado: $executable"
}

$isolatedDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("pncp-desktop-smoke-" + [guid]::NewGuid())
$screenshot = Join-Path $isolatedDirectory "smoke.png"
$database = Join-Path $isolatedDirectory "data\pncp.sqlite3"
New-Item -ItemType Directory -Path $isolatedDirectory | Out-Null
$previousDatabaseOverride = $env:PNCP_DESKTOP_DB_PATH

try {
    Copy-Item -LiteralPath $applicationDirectory -Destination $isolatedDirectory -Recurse
    $isolatedExecutable = Join-Path $isolatedDirectory "ConsultaPNCP\ConsultaPNCP.exe"
    $env:PNCP_DESKTOP_DB_PATH = $database
    $process = Start-Process -FilePath $isolatedExecutable -ArgumentList @("--screenshot", $screenshot) -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit(30000)) {
        $process.Kill()
        throw "O aplicativo nao encerrou o smoke test em 30 segundos."
    }
    if ($process.ExitCode -ne 0) {
        throw "O aplicativo encerrou com codigo $($process.ExitCode)."
    }
    if (-not (Test-Path -LiteralPath $screenshot -PathType Leaf)) {
        throw "O aplicativo abriu, mas nao gerou a captura de verificacao."
    }
    if ((Get-Item -LiteralPath $screenshot).Length -lt 1000) {
        throw "A captura de verificacao parece invalida."
    }
    Write-Host "SMOKE_EXE_OK: $isolatedExecutable"
}
finally {
    $env:PNCP_DESKTOP_DB_PATH = $previousDatabaseOverride
    if (Test-Path -LiteralPath $isolatedDirectory) {
        Remove-Item -LiteralPath $isolatedDirectory -Recurse -Force
    }
}
