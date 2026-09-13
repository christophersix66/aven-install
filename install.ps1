[CmdletBinding()]
param(
    [ValidateSet("rc", "stable")]
    [string]$Channel = "rc",
    [switch]$Check,
    [switch]$NonInteractive,
    [switch]$Yes,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$BaseUrl = if ($env:AVEN_INSTALL_BASE_URL) { $env:AVEN_INSTALL_BASE_URL } else { "https://raw.githubusercontent.com/christophersix66/aven-install/main" }

function Show-Usage {
    Write-Output "Install the exact approved private Aven release."
    Write-Output ""
    Write-Output "Usage: .\install.ps1 [-Channel rc|stable] [-Check] [-NonInteractive] [-Yes]"
    Write-Output "  -Check            Check prerequisites and exact release without mutation"
    Write-Output "  -NonInteractive   Disable prompts; installation also requires -Yes"
    Write-Output "  -Yes              Approve bounded prerequisite/install prompts"
}

if ($Help) {
    Show-Usage
    exit 0
}

function Test-Python([string]$Executable, [string[]]$Prefix) {
    try {
        & $Executable @Prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and (Test-Python $py.Source @("-3.11"))) {
        return @{ Executable = $py.Source; Prefix = @("-3.11") }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Test-Python $python.Source @())) {
        return @{ Executable = $python.Source; Prefix = @() }
    }
    return $null
}

function Confirm-BoundedAction([string]$Question) {
    if ($Yes) { return $true }
    if ($NonInteractive) { return $false }
    $answer = Read-Host "$Question [y/N]"
    return $answer -match '^(?i:y|yes)$'
}

$Python = Find-Python
if (-not $Python) {
    if ($Check) {
        [Console]::Error.WriteLine("Aven Installer stopped: PYTHON_TOO_OLD`nPython 3.11 or newer is required.")
        exit 2
    }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        [Console]::Error.WriteLine("Aven Installer stopped: PYTHON_TOO_OLD`nInstall Python 3.11 or newer, then run the installer again.")
        exit 2
    }
    $commandText = "winget install --id Python.Python.3.11 --exact --accept-package-agreements --accept-source-agreements"
    Write-Output "Python 3.11 or newer is required."
    Write-Output "Proposed command: $commandText"
    if (-not (Confirm-BoundedAction "Run this package-manager command? An OS approval prompt may appear.")) {
        [Console]::Error.WriteLine("Aven Installer stopped: PREREQUISITE_INSTALL_DECLINED")
        exit 2
    }
    & $winget.Source install --id Python.Python.3.11 --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        [Console]::Error.WriteLine("Aven Installer stopped: PREREQUISITE_INSTALL_FAILED")
        exit 2
    }
    $Python = Find-Python
    if (-not $Python) {
        [Console]::Error.WriteLine("Aven Installer stopped: PYTHON_TOO_OLD")
        exit 2
    }
}

$TempBase = if ($env:AVEN_INSTALL_TMPDIR) { $env:AVEN_INSTALL_TMPDIR } else { [System.IO.Path]::GetTempPath() }
$WorkDir = Join-Path $TempBase ("aven-install-entry-" + [Guid]::NewGuid().ToString("N"))
[System.IO.Directory]::CreateDirectory($WorkDir) | Out-Null
try {
    $Core = Join-Path $WorkDir "installer.py"
    $Manifest = Join-Path $WorkDir "channel.json"
    if ($env:AVEN_INSTALL_SOURCE_DIR) {
        $sourceCore = Join-Path $env:AVEN_INSTALL_SOURCE_DIR "installer.py"
        $sourceManifest = Join-Path $env:AVEN_INSTALL_SOURCE_DIR "channels\$Channel.json"
        if (-not (Test-Path -LiteralPath $sourceCore -PathType Leaf) -or -not (Test-Path -LiteralPath $sourceManifest -PathType Leaf)) {
            throw "installer source or channel manifest is unavailable"
        }
        Copy-Item -LiteralPath $sourceCore -Destination $Core
        Copy-Item -LiteralPath $sourceManifest -Destination $Manifest
    } else {
        if (-not $BaseUrl.StartsWith("https://", [StringComparison]::OrdinalIgnoreCase)) {
            throw "installer source URL must use HTTPS"
        }
        Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/installer.py" -OutFile $Core
        Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/channels/$Channel.json" -OutFile $Manifest
    }

    $Arguments = @($Python.Prefix) + @($Core, "--manifest", $Manifest, "--channel", $Channel)
    if ($Check) { $Arguments += "--check" }
    if ($NonInteractive) { $Arguments += "--non-interactive" }
    if ($Yes) { $Arguments += "--yes" }
    & $Python.Executable @Arguments
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine("Aven Installer stopped: ENTRYPOINT_FAILED`n$($_.Exception.Message)")
    exit 2
} finally {
    if (Test-Path -LiteralPath $WorkDir) {
        Remove-Item -LiteralPath $WorkDir -Recurse -Force
    }
}
