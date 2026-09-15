#!/bin/sh
set -eu

CHANNEL=rc
CHECK=0
NON_INTERACTIVE=0
ASSUME_YES=0
SOURCE_DIR=
BASE_URL=https://raw.githubusercontent.com/christophersix66/aven-install/main
COORDINATOR_SHA256=26468397efd38d46cdc5ecf76b67e0ad2231f5f1fe868c74499923a4b39dce8e
RC_MANIFEST_SHA256=4ff7d3739738983e639edd7c686e42b9aa122ad44d5e0bde3b0055529686fad5
STABLE_MANIFEST_SHA256=93ef9399559cbc444686917dca9c43ae93df1d0dd8abd0e97c3cc95c47891dd5

usage() {
  printf '%s\n' \
    'Install the exact approved private Aven release.' \
    '' \
    'Usage: install.sh [--channel rc|stable] [--check] [--non-interactive] [--yes]' \
    '' \
    '  --channel CHANNEL   Approved release channel (default: rc)' \
    '  --check             Check prerequisites and exact release without mutation' \
    '  --non-interactive   Disable prompts; installation also requires --yes' \
    '  --yes               Approve bounded prerequisite/install prompts' \
    '  --source-dir PATH   Use and verify files from an inspected local checkout' \
    '  --help              Show this help'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --channel)
      [ "$#" -ge 2 ] || { printf '%s\n' 'Aven Installer stopped: missing channel' >&2; exit 2; }
      CHANNEL=$2
      shift 2
      ;;
    --check) CHECK=1; shift ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    --source-dir)
      [ "$#" -ge 2 ] || { printf '%s\n' 'Aven Installer stopped: missing source directory' >&2; exit 2; }
      SOURCE_DIR=$2
      shift 2
      ;;
    --help|-h) usage; exit 0 ;;
    *) printf '%s\n' "Aven Installer stopped: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$CHANNEL" in
  rc|stable) ;;
  *) printf '%s\n' 'Aven Installer stopped: channel must be rc or stable' >&2; exit 2 ;;
esac

prompt_yes() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  [ "$NON_INTERACTIVE" -eq 0 ] || return 1
  if [ -r /dev/tty ]; then
    printf '%s' "$1 [y/N] " >/dev/tty
    IFS= read -r answer </dev/tty || return 1
  else
    printf '%s' "$1 [y/N] "
    IFS= read -r answer || return 1
  fi
  case "$answer" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}

python_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

find_python() {
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && python_supported "$candidate"; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

install_python() {
  command_text=
  if [ "$(uname -s 2>/dev/null || printf unknown)" = Darwin ] && command -v brew >/dev/null 2>&1; then
    command_text='brew install python@3.11'
  elif command -v apt-get >/dev/null 2>&1; then
    command_text='sudo apt-get install -y python3'
  elif command -v dnf >/dev/null 2>&1; then
    command_text='sudo dnf install -y python3'
  elif command -v pacman >/dev/null 2>&1; then
    command_text='sudo pacman -S --needed python'
  else
    printf '%s\n' 'Aven Installer stopped: PYTHON_TOO_OLD' 'Install Python 3.11 or newer, then run the installer again.' >&2
    exit 2
  fi
  printf '%s\n' 'Python 3.11 or newer is required.' "Proposed command: $command_text"
  prompt_yes 'Run this package-manager command? Elevation may be requested.' || {
    printf '%s\n' 'Aven Installer stopped: PREREQUISITE_INSTALL_DECLINED' >&2
    exit 2
  }
  case "$command_text" in
    'brew install python@3.11') brew install python@3.11 ;;
    'sudo apt-get install -y python3') sudo apt-get install -y python3 ;;
    'sudo dnf install -y python3') sudo dnf install -y python3 ;;
    'sudo pacman -S --needed python') sudo pacman -S --needed python ;;
    *) printf '%s\n' 'Aven Installer stopped: internal package command rejected' >&2; exit 2 ;;
  esac
}

PYTHON=$(find_python || true)
if [ -z "$PYTHON" ]; then
  if [ "$CHECK" -eq 1 ]; then
    printf '%s\n' 'Aven Installer stopped: PYTHON_TOO_OLD' 'Python 3.11 or newer is required.' >&2
    exit 2
  fi
  install_python
  PYTHON=$(find_python || true)
  [ -n "$PYTHON" ] || { printf '%s\n' 'Aven Installer stopped: PYTHON_TOO_OLD' >&2; exit 2; }
fi

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/aven-install-entry.XXXXXXXX")
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT HUP INT TERM

if [ -z "$SOURCE_DIR" ]; then
  script_name=$(basename -- "$0" 2>/dev/null || printf unknown)
  if [ "$script_name" = install.sh ]; then
    script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true)
    if [ -n "$script_dir" ] && [ -f "$script_dir/installer.py" ] && [ -f "$script_dir/channels/$CHANNEL.json" ]; then
      SOURCE_DIR=$script_dir
    fi
  fi
fi

if [ -n "$SOURCE_DIR" ]; then
  [ -f "$SOURCE_DIR/installer.py" ] && [ ! -L "$SOURCE_DIR/installer.py" ] || {
    printf '%s\n' 'Aven Installer stopped: installer source is unavailable' >&2
    exit 2
  }
  [ -f "$SOURCE_DIR/channels/$CHANNEL.json" ] && [ ! -L "$SOURCE_DIR/channels/$CHANNEL.json" ] || {
    printf '%s\n' 'Aven Installer stopped: channel manifest is unavailable' >&2
    exit 2
  }
  cp "$SOURCE_DIR/installer.py" "$WORK_DIR/installer.py"
  cp "$SOURCE_DIR/channels/$CHANNEL.json" "$WORK_DIR/channel.json"
else
  command -v curl >/dev/null 2>&1 || {
    printf '%s\n' 'Aven Installer stopped: CURL_NOT_FOUND' 'Download the public installer repository and run install.sh locally.' >&2
    exit 2
  }
  curl --proto '=https' --tlsv1.2 -fsSL "$BASE_URL/installer.py" -o "$WORK_DIR/installer.py"
  curl --proto '=https' --tlsv1.2 -fsSL "$BASE_URL/channels/$CHANNEL.json" -o "$WORK_DIR/channel.json"
fi

case "$CHANNEL" in
  rc) MANIFEST_SHA256=$RC_MANIFEST_SHA256 ;;
  stable) MANIFEST_SHA256=$STABLE_MANIFEST_SHA256 ;;
esac

verify_sha256() {
  "$PYTHON" -c 'import hashlib, pathlib, sys; actual=hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest(); raise SystemExit(0 if actual == sys.argv[2] else 1)' "$1" "$2"
}

verify_sha256 "$WORK_DIR/installer.py" "$COORDINATOR_SHA256" || {
  printf '%s\n' 'Aven Installer stopped: INSTALLER_INTEGRITY_MISMATCH' >&2
  exit 2
}
verify_sha256 "$WORK_DIR/channel.json" "$MANIFEST_SHA256" || {
  printf '%s\n' 'Aven Installer stopped: CHANNEL_INTEGRITY_MISMATCH' >&2
  exit 2
}

set -- "$PYTHON" "$WORK_DIR/installer.py" --manifest "$WORK_DIR/channel.json" --channel "$CHANNEL"
[ "$CHECK" -eq 0 ] || set -- "$@" --check
[ "$NON_INTERACTIVE" -eq 0 ] || set -- "$@" --non-interactive
[ "$ASSUME_YES" -eq 0 ] || set -- "$@" --yes
"$@"
exit $?
