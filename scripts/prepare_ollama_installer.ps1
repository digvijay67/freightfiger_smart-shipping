param(
    [string]$DownloadDirectory = (Join-Path $env:USERPROFILE 'Downloads')
)

$ErrorActionPreference = 'Stop'
$installerUrl = 'https://registry.ollama.com/download/OllamaSetup.exe'
$installerPath = Join-Path $DownloadDirectory 'OllamaSetup.exe'

Write-Host "Official source: $installerUrl"
Write-Host "Installer destination: $installerPath"
Write-Host 'This script downloads and verifies the installer only. It does not install or launch Ollama.'
$confirmation = Read-Host 'Type DOWNLOAD to continue'
if ($confirmation -cne 'DOWNLOAD') {
    Write-Host 'Cancelled; no download was started.'
    exit 0
}

if (Test-Path -LiteralPath $installerPath) {
    throw "Refusing to overwrite existing file: $installerPath"
}
if (-not (Test-Path -LiteralPath $DownloadDirectory -PathType Container)) {
    throw "Download directory does not exist: $DownloadDirectory"
}

try {
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath
    $signature = Get-AuthenticodeSignature -LiteralPath $installerPath
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Ollama') {
        throw "Installer signature was not valid for Ollama (status: $($signature.Status); signer: $($signature.SignerCertificate.Subject))."
    }
    $hash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash
    Write-Host "Verified Authenticode signer: $($signature.SignerCertificate.Subject)"
    Write-Host "SHA-256: $hash"
    Write-Host 'Review the file, then launch it manually from Downloads to see and respond to Windows installation prompts.'
} catch {
    if (Test-Path -LiteralPath $installerPath) {
        Remove-Item -LiteralPath $installerPath -Force
    }
    throw
}
