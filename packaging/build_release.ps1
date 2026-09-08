param(
    [string]$Python = "python",
    [string]$InnoCompiler = ""
)
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$buildPython = Join-Path $projectRoot ".venv-build\Scripts\python.exe"
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $buildPython)) {
        & $Python -m venv .venv-build
        if ($LASTEXITCODE -ne 0) { throw "Could not create build environment" }
    }
    & $buildPython -m pip install -r packaging/requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "Could not install build dependencies" }
    $buildArgs = @("packaging/build_release.py")
    if ($InnoCompiler) { $buildArgs += @("--iscc", $InnoCompiler) }
    & $buildPython @buildArgs
    if ($LASTEXITCODE -ne 0) { throw "Release build failed. Inspect build/windows logs." }
}
finally {
    Pop-Location
}
