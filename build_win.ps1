# Build Kolbe Windows EXE — ALWAYS uses project .venv Python 3.12 (never system Python).
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$RequiredMajor = 3
$RequiredMinor = 12

function Assert-VenvPython312 {
    param([string]$PythonExe)
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        throw "Missing $PythonExe — create the venv with Python 3.12 first."
    }
    $verLine = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'); print(sys.executable)"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to query interpreter: $PythonExe"
    }
    $parts = @($verLine)
    $ver = $parts[0].Trim()
    $exePath = if ($parts.Count -gt 1) { $parts[1].Trim() } else { $PythonExe }
    $nums = $ver.Split(".")
    $major = [int]$nums[0]
    $minor = [int]$nums[1]
    if ($major -ne $RequiredMajor -or $minor -ne $RequiredMinor) {
        throw @"
Wrong Python in .venv: $ver ($exePath)
Kolbe Windows builds require Python $RequiredMajor.$RequiredMinor in .\.venv
Recreate with:
  py -3.12 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -e . `"pyinstaller>=6.0`"
"@
    }
    # Refuse if this somehow isn't the project .venv
    $expected = [System.IO.Path]::GetFullPath($PythonExe)
    $actual = [System.IO.Path]::GetFullPath($exePath)
    if ($actual -ne $expected) {
        throw "Interpreter mismatch.`nExpected: $expected`nActual:   $actual"
    }
    Write-Host "Using .venv Python $ver"
    Write-Host "  $actual"
}

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "Creating .venv with Python 3.12 (py -3.12)..."
    py -3.12 -m venv .venv
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Failed to create .\.venv with Python 3.12. Install Python 3.12 and ensure 'py -3.12' works."
    }
}

Assert-VenvPython312 -PythonExe $Python

# Never rely on activated conda/system PATH — always invoke .venv explicitly.
& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $Python -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "pip install -e . failed" }
& $Python -m pip install "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) { throw "pyinstaller install failed" }

$Icon = Join-Path $Root "icon.ico"
if (Test-Path -LiteralPath $Icon) {
    Write-Host "Using app icon: $Icon"
} else {
    Write-Warning "icon.ico not found in project root — EXE will use the default icon."
}

$HidDllSrc = Join-Path $Root ".venv\Lib\site-packages\pydualsense\hidapi.dll"
$HidDllDstDir = Join-Path $Root "packaging\bin"
$HidDllDst = Join-Path $HidDllDstDir "hidapi.dll"
if (Test-Path -LiteralPath $HidDllSrc) {
    New-Item -ItemType Directory -Force -Path $HidDllDstDir | Out-Null
    Copy-Item -Force -LiteralPath $HidDllSrc -Destination $HidDllDst
    Write-Host "Vendored hidapi.dll -> packaging\bin\hidapi.dll"
} elseif (Test-Path -LiteralPath $HidDllDst) {
    Write-Host "Using existing packaging\bin\hidapi.dll"
} else {
    Write-Warning "hidapi.dll not found under .venv pydualsense — DualSense may fail in the frozen EXE."
}

Write-Host "Building Kolbe v1.0.3 with .venv PyInstaller..."
& $Python -m PyInstaller "packaging\kolbe_win.spec" --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "Done. Run: dist\Kolbe v1.0.3\Kolbe v1.0.3.exe"
