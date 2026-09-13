# Troubleshooting

The installer prints a stable error code followed by the next useful action.

| Code | Meaning | Next action |
| --- | --- | --- |
| `PYTHON_TOO_OLD` | Python 3.11+ is absent | Install a supported Python, then rerun `--check` |
| `PREREQUISITE_MISSING` | Git or GitHub CLI is absent/unusable | Approve the displayed package command or install manually |
| `GITHUB_NOT_AUTHENTICATED` | GitHub CLI has no usable authentication | Run `gh auth login` or approve the guided login |
| `GITHUB_REPOSITORY_ACCESS_DENIED` | Authentication exists but cannot read private Aven | Ask the repository owner for access, then rerun `--check` |
| `STABLE_RELEASE_UNAVAILABLE` | Stable Aven has not been released | Select `rc` only if you intend to install the release candidate |
| `RELEASE_MANIFEST_INVALID` | Channel input is malformed or unsafe | Re-download the installer from the canonical public repository |
| `RELEASE_TAG_MISMATCH` | The private tag/release does not match the approved commit | Stop; do not substitute another release |
| `RELEASE_ASSET_NOT_FOUND` | Required reviewed release material is missing | Stop and contact the release owner |
| `ARTIFACT_SHA256_MISMATCH` | Downloaded bytes or checksum differ | Stop; delete the temporary download and investigate |
| `ARCHIVE_UNSAFE` | Archive paths/types/bounds are unsafe | Stop; do not extract or execute the artifact |
| `AVEN_DIFFERENT_INSTALLATION` | Another Aven version/lock already exists | Use explicit Aven lifecycle guidance; no silent update/downgrade occurs |
| `AVEN_REPAIR_REQUIRED` | The same installation is present but unhealthy | Run `aven status`; repair remains a distinct lifecycle action |
| `AVEN_SETUP_PLAN_FAILED` | Aven rejected or could not produce its setup plan | Read Aven's preceding diagnostic and resolve its prerequisite |
| `AVEN_SETUP_APPLY_FAILED` | Aven setup apply did not complete | Read Aven's diagnostic; rerun the plan before another apply |
| `AVEN_POST_INSTALL_UNHEALTHY` | Version/status/doctor did not confirm a healthy exact install | Run the installed launcher's `aven status` and `aven doctor` |

## PATH

Linux and macOS normally use `~/.local/bin`. Windows normally uses `%LOCALAPPDATA%\aven\bin`. If the directory is not already in the user PATH, the installer prints the exact directory to add. It does not silently rewrite shell profiles.

## Optional services

Codex, Claude, PostgreSQL, and ElevenLabs may be absent without invalidating base Aven installation. Configure them through their own supported mechanisms or Aven's documented setup. The installer does not custody their credentials.
