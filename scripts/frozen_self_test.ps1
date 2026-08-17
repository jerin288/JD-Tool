$ErrorActionPreference = "Stop"
$workspace = (Get-Location).Path
$testRoot = Join-Path $workspace "tmp\Frozen Self Test"
if ((Test-Path $testRoot) -and -not ((Resolve-Path $testRoot).Path.StartsWith($workspace, [System.StringComparison]::OrdinalIgnoreCase))) {
    throw "Refusing to remove a self-test folder outside the workspace."
}
Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $workspace "dist\BankStatementToTally") -Destination $testRoot -Recurse
$result = Join-Path $testRoot "build self test.json"
Remove-Item -LiteralPath $result -Force -ErrorAction SilentlyContinue
$executable = Join-Path $testRoot "BankStatementToTally\BankStatementToTally.exe"
$process = Start-Process -FilePath $executable -ArgumentList "--self-test", ('"' + $result + '"') -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0 -or -not (Test-Path $result)) {
    throw "Frozen runtime self-test failed."
}
$payload = Get-Content -Raw $result | ConvertFrom-Json
if ($payload.status -ne "ok") {
    throw "Frozen runtime self-test reported: $($payload.error)"
}
Write-Host "Frozen runtime self-test passed (Tcl $($payload.tcl))."
