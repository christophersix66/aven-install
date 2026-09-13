# Installer security model

`aven-install` is a public entrypoint to a private release. It is intentionally small and does not contain the Aven runtime or any Intelligence Engineering component source.

## Trust boundaries

- The public entrypoints pin the coordinator and channel-file SHA-256 values. The coordinator independently pins every security-sensitive field of the exact approved private GitHub release.
- GitHub CLI owns authentication and credential storage.
- The installer separately verifies repository access, tag target, release posture, asset identity, size, GitHub digest when available, downloaded SHA-256, checksum-file binding, and build-report identity.
- The downloaded bootstrap self-verifies again and owns component acquisition and machine installation.
- Installed Aven owns version, status, doctor, reinstall, and uninstall semantics.

Installer success is not Program Authority, Verification, Trust, host authentication, production approval, or permission for repository mutation.

## Pipe-to-shell

`curl | bash` and `irm | iex` optimize convenience. They execute the entrypoint retrieved at that moment and should not be described as intrinsically trusted. For stronger review, clone this repository, select an exact commit, inspect the entrypoint, Python coordinator, and channel manifest, then execute locally. Local execution uses those adjacent inspected files and verifies their content hashes before Python runs.

## Extraction protections

Before any archive content is executed, the coordinator rejects:

- absolute or parent-traversal paths;
- backslash path ambiguity;
- symbolic links, hard links, devices, and other special members;
- duplicate and case-colliding names;
- files resolving outside the new extraction directory;
- excessive member count or expanded size.

Regular files are copied into a newly created owned temporary directory rather than extracted through an unbounded archive API.

## Commands and privilege

External commands are resolved once to absolute paths and invoked as argument arrays with `shell=False`; current-directory executables and manifest shell fragments are rejected. The installed Aven lifecycle is checked only through its conventional owned launcher. Package-manager commands are selected from fixed command arrays. Missing prerequisite installation is shown before execution and requires explicit approval. No silent `sudo` or administrator elevation occurs.

The shell and PowerShell entrypoints do not enable trace logging and do not evaluate downloaded manifest values as code.

## Secrets

The installer must never log or persist GitHub credentials, provider keys, ElevenLabs secrets, Codex credentials, or Claude credentials. `gh auth login` runs as GitHub CLI's own interactive flow. Voice configuration remains an optional Aven responsibility after installation.

Security reports should describe the exact affected commit and may be sent privately to the repository owner. Do not include credentials or private component source in a public report.
