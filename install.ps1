[CmdletBinding()]
param(
    [ValidateSet("rc", "stable")]
    [string]$Channel = "rc",
    [switch]$Check,
    [switch]$NonInteractive,
    [switch]$Yes,
    [string]$SourceDir,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$BaseUrl = "https://raw.githubusercontent.com/christophersix66/aven-install/main"
$CoordinatorSha256 = "29b88efc1de9f0816a40954e9f4a9cb4df47a33b710369d03aafa41e07afec84"
$RcManifestSha256 = "17bcfd00b198e56bdcb866558d785339d91fee72563fd08dc3bdc9386c6fa3a1"
$StableManifestSha256 = "93ef9399559cbc444686917dca9c43ae93df1d0dd8abd0e97c3cc95c47891dd5"

function Show-Usage {
    Write-Output "Install the exact approved private Aven release."
    Write-Output ""
    Write-Output "Usage: .\install.ps1 [-Channel rc|stable] [-Check] [-NonInteractive] [-Yes]"
    Write-Output "  -Check            Check prerequisites and exact release without mutation"
    Write-Output "  -NonInteractive   Disable prompts; installation also requires -Yes"
    Write-Output "  -Yes              Approve bounded prerequisite/install prompts"
    Write-Output "  -SourceDir PATH   Use and verify files from an inspected local checkout"
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
    $EffectiveSourceDir = $SourceDir
    if (-not $EffectiveSourceDir -and $PSScriptRoot -and
        (Test-Path -LiteralPath (Join-Path $PSScriptRoot "installer.py") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $PSScriptRoot "channels\$Channel.json") -PathType Leaf)) {
        $EffectiveSourceDir = $PSScriptRoot
    }
    if ($EffectiveSourceDir) {
        $sourceCore = Join-Path $EffectiveSourceDir "installer.py"
        $sourceManifest = Join-Path $EffectiveSourceDir "channels\$Channel.json"
        if (-not (Test-Path -LiteralPath $sourceCore -PathType Leaf) -or -not (Test-Path -LiteralPath $sourceManifest -PathType Leaf)) {
            throw "installer source or channel manifest is unavailable"
        }
        Copy-Item -LiteralPath $sourceCore -Destination $Core
        Copy-Item -LiteralPath $sourceManifest -Destination $Manifest
    } else {
        Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/installer.py" -OutFile $Core
        Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/channels/$Channel.json" -OutFile $Manifest
    }

    $ManifestSha256 = if ($Channel -eq "rc") { $RcManifestSha256 } else { $StableManifestSha256 }
    $ObservedCoordinatorSha256 = (Get-FileHash -LiteralPath $Core -Algorithm SHA256).Hash.ToLowerInvariant()
    $ObservedManifestSha256 = (Get-FileHash -LiteralPath $Manifest -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ObservedCoordinatorSha256 -ne $CoordinatorSha256) {
        throw "INSTALLER_INTEGRITY_MISMATCH"
    }
    if ($ObservedManifestSha256 -ne $ManifestSha256) {
        throw "CHANNEL_INTEGRITY_MISMATCH"
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
