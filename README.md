# Install Aven

Aven is distributed privately. This public, inspectable installer establishes normal GitHub authentication, verifies one exact approved private release, and hands installation to Aven's own bootstrap.

## Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/christophersix66/aven-install/main/install.sh | bash
```

## Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/christophersix66/aven-install/main/install.ps1 | iex
```

The current default channel is explicitly `rc`: Aven `1.0.0-rc.2`. Stable `1.0.0` does not exist and is not silently substituted.

## What the installer does

1. Detects Linux, macOS, or Windows and the supported machine architecture.
2. Requires Python 3.11+, Git, and GitHub CLI; it can offer a bounded package-manager command for a missing prerequisite.
3. Uses `gh auth login` when the operator approves normal GitHub authentication.
4. Verifies authenticated read access to the private Aven repository.
5. Verifies that the coordinator and channel bytes match the entrypoint's compiled SHA-256 values, then requires the channel to equal the exact owner-approved RC identity.
6. Resolves the exact tag, commit, pre-release, asset name, size, and digest from `channels/rc.json`.
7. Downloads the private release with GitHub CLI into an owned temporary directory.
8. Verifies the local SHA-256, checksum file, and build report.
9. Rejects unsafe archive paths, links, devices, collisions, or expansion beyond the fixed bound.
10. Runs Aven's authoritative `setup --plan`, asks for confirmation, then runs `setup --apply`.
11. Runs the installed `aven version`, `aven status`, and `aven doctor` and prints first-use commands.

The installer does not acquire or arrange the seven components itself. It stops being responsible once it invokes the verified Aven bootstrap.

## Requirements

- Linux, macOS, or Windows PowerShell on `x86_64`/`amd64` or `arm64`/`aarch64`
- Python 3.11 or newer
- Git
- [GitHub CLI](https://cli.github.com/)
- GitHub read access to `christophersix66/intelligence-workbench`

Codex, Claude, Ollama, LM Studio, OpenCode, PostgreSQL, ElevenLabs, and local models are optional for base installation. The installer does not install model hosts, download models, configure hosted-provider keys, install host credentials, or handle ElevenLabs secrets.

Recognized prerequisite package managers are Homebrew, winget, apt, dnf, and pacman. Every package mutation is displayed and requires explicit approval. The installer never silently invokes `sudo` or administrator elevation.

## Check without installing

Download the entrypoint, inspect it, then run:

```bash
./install.sh --check --channel rc
```

```powershell
.\install.ps1 -Check -Channel rc
```

Check mode performs no installation or authentication mutation. It reports missing prerequisites, GitHub authentication/access, the exact selected release, existing Aven state, and whether installation can proceed.

## Higher-assurance installation

Pipe-to-shell is convenient, not intrinsically trusted. To inspect and execute locally:

```bash
git clone https://github.com/christophersix66/aven-install.git
cd aven-install
git rev-parse HEAD
less install.sh installer.py channels/rc.json
./install.sh --check --channel rc
./install.sh --channel rc
```

When run from a checkout, the entrypoint automatically uses the adjacent coordinator and channel files and verifies their compiled SHA-256 values. For a reproducible review, check out the exact installer commit accepted by your organization before inspection. The coordinator also fails closed unless the channel is the exact approved private Aven `v1.0.0-rc.2` identity and its tag, source commit, release posture, asset identity, and SHA-256 all match.

## Non-interactive use

Non-interactive mutation requires both flags:

```bash
./install.sh --channel rc --non-interactive --yes
```

```powershell
.\install.ps1 -Channel rc -NonInteractive -Yes
```

Without explicit `--yes`/`-Yes`, non-interactive installation stops before mutation.

## GitHub authentication

The installer checks `gh auth status`, offers `gh auth login` when needed, and then tests actual private repository access. GitHub CLI owns the authentication flow and credential storage. The installer never asks for, reads, stores, or logs a GitHub token.

Authentication does not by itself prove authorization; private repository read access is checked separately.

## Already installed

If the exact Aven version, runtime commit, installation lock, and health are already present, the installer returns `ALREADY INSTALLED` without reinstalling.

If a different version or lock is present, it stops. It never silently upgrades or downgrades Aven. Use Aven's own lifecycle commands for deliberate changes.

## First use

```bash
aven
aven analyze
aven improve --plan
aven doctor
```

For a new local project:

```bash
mkdir my-project
cd my-project
aven create --plan --objective "Build me a project"
```

## Uninstall

The entrypoint does not duplicate lifecycle logic. Use Aven itself:

```bash
aven uninstall --plan
aven uninstall --apply
```

Aven preserves user configuration by default according to its released lifecycle contract.

## Security and troubleshooting

- [Security model](docs/SECURITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

This repository contains no private Aven source, component repository content, credentials, project state, Program Authority, or provider secrets.
