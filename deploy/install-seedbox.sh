#!/usr/bin/env bash
# Install or update Starr Studio and Kometa on a seedbox (no root, no Docker), such as Ultra.cc.
#
#   bash install-seedbox.sh --port 34567 --username me --wheel ./starr_studio-0.1.0-py3-none-any.whl
#
# What it does, in this order, so Studio never answers without a password:
#   1. Kometa at the pinned tag in ~/kometa, with its own venv.
#   2. Studio in ~/starr-studio/.venv, from a release wheel (a file or a URL; default: the latest release's).
#   3. ~/.config/starr-studio/studio.env with STUDIO_ALLOW_LOCAL=false (kept if it already exists).
#   4. The username and password (starr-studio create-user), URL base and trusted proxy (starr-studio set-proxy),
#      written to Studio's database BEFORE its first start.
#   5. A systemd --user unit, enabled and started.
#   6. On Ultra.cc, the nginx location in ~/.apps/nginx/proxy.d/ and `app-nginx restart`; elsewhere it prints it.
#
# Run it again to update: Kometa moves to the pinned tag, the wheel is reinstalled, Studio restarts. The user,
# the env file and Studio's data are left as they are.
#
# Options (or the environment variable in brackets):
#   --port N            Studio's port [STUDIO_PORT]; on Ultra.cc pick one from `app-ports free`
#   --username NAME     the sign-in username [STUDIO_USERNAME]; the password is asked for (hidden), or read from
#                       STUDIO_PASSWORD when set (for scripted installs)
#   --wheel PATH|URL    the Studio wheel to install [STUDIO_WHEEL]; default: the latest GitHub release's
#   --url-base PATH     the path behind the proxy [STUDIO_URL_BASE], default /starr-studio
#   --kometa-dir DIR    default ~/kometa;  --studio-dir DIR  default ~/starr-studio
#   --python PATH       Python 3.12 or newer to build the venvs with; default: the first python3.1x found
#   --dry-run           print what would be done, change nothing
#   -h, --help
set -euo pipefail

KOMETA_TAG="v2.5.4"  # keep in step with the Dockerfile's KOMETA_TAG (tests/test_seedbox_script.py checks)
REPO="hasanxhq/starr-studio"

PORT="${STUDIO_PORT:-}"
USERNAME="${STUDIO_USERNAME:-}"
WHEEL="${STUDIO_WHEEL:-}"
URL_BASE="${STUDIO_URL_BASE:-/starr-studio}"
KOMETA_DIR="$HOME/kometa"
STUDIO_DIR="$HOME/starr-studio"
CONF_DIR="$HOME/.config/starr-studio"
PYTHON=""
DRY_RUN=0

die() { echo "error: $*" >&2; exit 1; }
say() { printf '\n==> %s\n' "$*"; }
run() {
  if (( DRY_RUN )); then printf '    would run: %s\n' "$*"; else "$@"; fi
}
write_file() {  # write_file PATH MODE < content
  local path="$1" mode="$2" content
  content="$(cat)"
  if (( DRY_RUN )); then printf '    would write %s\n' "$path"; return; fi
  mkdir -p "$(dirname "$path")"
  printf '%s\n' "$content" > "$path.tmp"
  chmod "$mode" "$path.tmp"
  mv "$path.tmp" "$path"
}

while (( $# )); do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --username) USERNAME="$2"; shift 2 ;;
    --wheel) WHEEL="$2"; shift 2 ;;
    --url-base) URL_BASE="$2"; shift 2 ;;
    --kometa-dir) KOMETA_DIR="$2"; shift 2 ;;
    --studio-dir) STUDIO_DIR="$2"; shift 2 ;;
    --python) PYTHON="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option $1 (see --help)" ;;
  esac
done

ENV_FILE="$CONF_DIR/studio.env"
UNIT_FILE="$HOME/.config/systemd/user/starr-studio.service"
ULTRA_PROXY_DIR="$HOME/.apps/nginx/proxy.d"

# --- Checks ---------------------------------------------------------------------------------------

[[ "$(id -u)" != 0 ]] || die "run this as your own user, not root"
command -v git >/dev/null || die "git is needed"
command -v systemctl >/dev/null || die "systemctl is needed (systemd --user)"

if [[ -z "$PYTHON" ]]; then
  for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then
      PYTHON="$(command -v "$candidate")"; break
    fi
  done
fi
[[ -n "$PYTHON" ]] || die "Python 3.12 or newer is needed. On Ultra.cc, install it with pyenv (see their Python guide), then pass --python"

[[ "$PORT" =~ ^[0-9]+$ ]] || {
  command -v app-ports >/dev/null && { echo "Free ports on this slot:"; app-ports free || true; }
  die "give Studio's port with --port"
}
[[ "$URL_BASE" =~ ^/[A-Za-z0-9._~-]+(/[A-Za-z0-9._~-]+)*$ ]] || die "--url-base looks like /starr-studio"

FIRST_INSTALL=1
[[ -f "$ENV_FILE" ]] && FIRST_INSTALL=0
if (( FIRST_INSTALL )) && [[ -z "$USERNAME" ]]; then
  read -r -p "Username to sign in to Studio: " USERNAME
fi
if (( FIRST_INSTALL )) && [[ -z "${STUDIO_PASSWORD:-}" ]] && (( ! DRY_RUN )); then
  read -r -s -p "Password (8 characters or more): " STUDIO_PASSWORD; echo
  read -r -s -p "Password again: " again; echo
  [[ "$STUDIO_PASSWORD" == "$again" ]] || die "the two passwords don't match"
fi
if (( FIRST_INSTALL )) && (( ! DRY_RUN )); then
  [[ -n "$USERNAME" ]] || die "a username is needed"
  (( ${#STUDIO_PASSWORD} >= 8 )) || die "use a password of 8 characters or more"
fi

if [[ -z "$WHEEL" ]]; then
  command -v curl >/dev/null || die "curl is needed to find the latest release (or pass --wheel)"
  WHEEL="$(curl -fsSL "https://api.github.com/repos/$REPO/releases?per_page=10" \
    | "$PYTHON" -c 'import json, sys
for release in json.load(sys.stdin):
    for asset in release.get("assets", []):
        if asset["name"].endswith(".whl"):
            print(asset["browser_download_url"]); sys.exit(0)
sys.exit(1)')" || die "no release with a wheel found; pass --wheel with a wheel file"
fi

# --- 1. Kometa ------------------------------------------------------------------------------------

say "Kometa $KOMETA_TAG in $KOMETA_DIR"
if [[ -d "$KOMETA_DIR/.git" ]]; then
  run git -C "$KOMETA_DIR" fetch --quiet --tags origin
  run git -C "$KOMETA_DIR" checkout --quiet "$KOMETA_TAG"
else
  run git clone --quiet --branch "$KOMETA_TAG" --depth 1 https://github.com/Kometa-Team/Kometa.git "$KOMETA_DIR"
fi
[[ -x "$KOMETA_DIR/.venv/bin/python" ]] || run "$PYTHON" -m venv "$KOMETA_DIR/.venv"
run "$KOMETA_DIR/.venv/bin/python" -m pip install --quiet --upgrade pip
run "$KOMETA_DIR/.venv/bin/python" -m pip install --quiet -r "$KOMETA_DIR/requirements.txt"
run mkdir -p "$KOMETA_DIR/config"

# --- 2. Studio ------------------------------------------------------------------------------------

say "Starr Studio in $STUDIO_DIR"
[[ -x "$STUDIO_DIR/.venv/bin/python" ]] || run "$PYTHON" -m venv "$STUDIO_DIR/.venv"
run "$STUDIO_DIR/.venv/bin/python" -m pip install --quiet --upgrade pip
run "$STUDIO_DIR/.venv/bin/python" -m pip install --quiet --upgrade --force-reinstall --no-deps "$WHEEL"
run "$STUDIO_DIR/.venv/bin/python" -m pip install --quiet "$WHEEL"  # its dependencies
STUDIO="$STUDIO_DIR/.venv/bin/starr-studio"

# --- 3. Settings ----------------------------------------------------------------------------------

if (( FIRST_INSTALL )); then
  say "Settings in $ENV_FILE"
  write_file "$ENV_FILE" 600 <<EOF
# Starr Studio settings (deploy/install-seedbox.sh). Restart after a change: systemctl --user restart starr-studio
STUDIO_HOST=127.0.0.1
STUDIO_PORT=$PORT
STUDIO_DATA_DIR=$CONF_DIR/data
STUDIO_KOMETA_PYTHON=$KOMETA_DIR/.venv/bin/python
STUDIO_KOMETA_ENTRY=$KOMETA_DIR/kometa.py
STUDIO_KOMETA_CONFIG=$KOMETA_DIR/config/config.yml
# A shared server: loopback and the private network are other customers, so no address skips sign-in.
STUDIO_ALLOW_LOCAL=false
EOF
else
  say "Keeping $ENV_FILE as it is"
fi

# --- 4. Sign-in and proxy, before the first start ---------------------------------------------------

with_env() {  # run a starr-studio command with the env file's settings
  if (( DRY_RUN )); then printf '    would run: %s\n' "$*"; return; fi
  ( set -a; . "$ENV_FILE"; set +a; "$@" )
}
if (( FIRST_INSTALL )); then
  say "Sign-in for $USERNAME"
  if (( DRY_RUN )); then
    printf '    would run: %s create-user --username %s --if-missing --password-stdin\n' "$STUDIO" "$USERNAME"
  else
    printf '%s\n' "$STUDIO_PASSWORD" | with_env "$STUDIO" create-user --username "$USERNAME" --if-missing --password-stdin
  fi
  unset STUDIO_PASSWORD
  with_env "$STUDIO" set-proxy --url-base "$URL_BASE" --trusted 127.0.0.1
fi

# --- 5. The service -------------------------------------------------------------------------------

say "systemd --user unit $UNIT_FILE"
write_file "$UNIT_FILE" 644 <<EOF
[Unit]
Description=Starr Studio
After=network-online.target

[Service]
Type=simple
EnvironmentFile=$ENV_FILE
ExecStart=$STUDIO serve
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
run systemctl --user daemon-reload
run systemctl --user enable --quiet starr-studio
run systemctl --user restart starr-studio

# --- 6. The proxy ---------------------------------------------------------------------------------

PORT_IN_ENV="$PORT"
if (( ! FIRST_INSTALL )) && [[ -f "$ENV_FILE" ]]; then
  PORT_IN_ENV="$(sed -n 's/^STUDIO_PORT=//p' "$ENV_FILE" | tail -n 1)"
fi
LOCATION="location $URL_BASE/ {
    proxy_pass http://127.0.0.1:$PORT_IN_ENV;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_buffering off;              # live logs are server-sent events
    proxy_http_version 1.1;
    proxy_read_timeout 1h;
    client_max_body_size 12m;         # poster uploads (10 MB)
}"
if [[ -d "$ULTRA_PROXY_DIR" ]]; then
  say "nginx location in $ULTRA_PROXY_DIR/starr-studio.conf"
  write_file "$ULTRA_PROXY_DIR/starr-studio.conf" 644 <<<"$LOCATION"
  if command -v app-nginx >/dev/null; then run app-nginx restart; fi
  echo
  echo "Open $URL_BASE/ at your slot's address (https://<username>.<server>.usbx.me$URL_BASE/) and sign in."
else
  say "Add this to your reverse proxy (see docs/reverse-proxy.md), then open $URL_BASE/ and sign in:"
  echo "$LOCATION"
fi
(( DRY_RUN )) && echo && echo "Dry run: nothing was changed."
exit 0
