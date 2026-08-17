param(
    [Parameter(Mandatory = $true)]
    [string]$Tag
)

$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $workspace

if ($Tag -notmatch '^v(\d+\.\d+\.\d+)$') {
    throw "Release tag must use stable vX.Y.Z form."
}
$version = $Matches[1]
$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
$sourceVersion = & $python -c "from app import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0 -or $sourceVersion.Trim() -ne $version) {
    throw "app.__version__ ($($sourceVersion.Trim())) does not match tag $Tag."
}

$releaseRoot = Join-Path $workspace "release"
if ((Test-Path $releaseRoot) -and -not ((Resolve-Path $releaseRoot).Path.StartsWith($workspace, [System.StringComparison]::OrdinalIgnoreCase))) {
    throw "Refusing to remove a release folder outside the workspace."
}
Remove-Item -LiteralPath $releaseRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

$assetName = "JD-Tool-windows-x64-$Tag.zip"
$assetPath = Join-Path $releaseRoot $assetName
Compress-Archive -LiteralPath (Join-Path $workspace "dist\BankStatementToTally") -DestinationPath $assetPath -CompressionLevel Optimal
$asset = Get-Item -LiteralPath $assetPath
$sha256 = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    schema_version = 1
    version = $version
    asset = $assetName
    sha256 = $sha256
    size_bytes = $asset.Length
    published_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releaseRoot "update-manifest.json") -Encoding utf8
Write-Host "Created $assetName ($($asset.Length) bytes)"
