#!/data/data/com.termux/files/usr/bin/env bash
# Astro Data Lake — Termux (Android) setup.
#
#   pkg install git
#   git clone <repo> && cd Star
#   bash scripts/termux-setup.sh
#
# Installs the pure-Python core (pull / links / status / tui / doctor /
# spacetrack) which needs no compiler. `astro build` additionally needs
# polars; see the note at the end.

set -euo pipefail

info()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

if [ -z "${PREFIX:-}" ] || [ ! -d "/data/data/com.termux" ]; then
    warn "This doesn't look like Termux. The script still works on plain Linux,"
    warn "but the Termux-specific package names below will not resolve."
fi

info "Installing system packages (python, git, openssl for TLS)"
pkg install -y python git openssl || die "pkg install failed — run 'pkg update' first"

info "Upgrading pip tooling"
python -m pip install --upgrade pip wheel setuptools

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

info "Installing astro-datalake (core, pure-Python)"
python -m pip install -e .

# Termux's single-user filesystem: keep data out of $PREFIX so an app
# upgrade or a `pkg reinstall python` can't take the catalogues with it.
DATA_HOME="${ASTRO_DL_HOME:-$HOME/astro-datalake}"
mkdir -p "$DATA_HOME"

PROFILE="$HOME/.bashrc"
if ! grep -q "ASTRO_DL_HOME" "$PROFILE" 2>/dev/null; then
    info "Pointing ASTRO_DL_HOME at $DATA_HOME (added to $PROFILE)"
    {
        echo ""
        echo "# Astro Data Lake"
        echo "export ASTRO_DL_HOME=\"$DATA_HOME\""
        echo "export TERM=\${TERM:-xterm-256color}"
    } >> "$PROFILE"
else
    info "ASTRO_DL_HOME already configured in $PROFILE"
fi
export ASTRO_DL_HOME="$DATA_HOME"
export TERM="${TERM:-xterm-256color}"

info "Running environment check"
astro doctor || warn "doctor reported findings — read the table above"

cat <<'NOTE'

Done. Try:

  astro doctor            # re-check this device
  astro links --tier 1    # test every download link
  astro tui               # interactive UI (auto-switches to phone layout)
  astro pull celestrak_gp_stations
  astro spacetrack policy

Space-Track (optional, free account at space-track.org/auth/createAccount):

  export ASTRO_DL_SPACETRACK_USER='your-email'
  export ASTRO_DL_SPACETRACK_PASS='your-password'

`astro build` needs polars, which has no prebuilt Termux wheel. Either:

  pkg install rust binutils && pip install 'astro-datalake[build]'
      (slow: compiles polars from Rust source, needs ~4 GB free)

  or run `astro build` on a laptop and copy data/ over — `astro pull`
  and the TUI work on-device either way.

Storage tip: `termux-setup-storage` grants access to shared storage if you
want the data lake on the SD card (then set ASTRO_DL_HOME accordingly).
NOTE
