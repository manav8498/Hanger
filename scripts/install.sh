#!/bin/sh
#
# Hangar installer
#
# What this script does:
# - Checks that the host is macOS or Linux.
# - Checks that git, curl, openssl, Docker, and Docker Compose v2 are available.
# - Clones https://github.com/manav8498/Hangar.git into $HOME/hangar, or
#   $HANGAR_DIR if that environment variable is set.
# - Refuses to overwrite a non-empty install directory unless --force is passed.
# - Copies .env.example to .env and replaces HANGAR_ADMIN_TOKEN=change-me with a
#   random 32-character hex token.
# - Runs docker compose up -d and waits for http://localhost:8080/healthz.
#
# What this script does not do:
# - It never runs sudo.
# - It never writes outside the chosen install directory.
# - It never installs Docker, Git, or other system packages for you.
# - It never sets ANTHROPIC_API_KEY; edit .env after install to add one.

set -e

REPO_URL="https://github.com/manav8498/Hangar.git"
INSTALL_DIR="${HANGAR_DIR:-$HOME/hangar}"
FORCE=0

usage() {
  cat <<'EOF'
Usage: install.sh [--force] [--help]

Environment:
  HANGAR_DIR=/path/to/install  Install somewhere other than $HOME/hangar.

Flags:
  --force  Remove the install directory first if it already exists.
  --help   Show this help.
EOF
}

say() {
  printf '%s\n' "$1"
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    say "$2"
    exit 1
  fi
}

run() {
  say "$1"
  shift
  "$@"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --force)
      FORCE=1
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 1
      ;;
  esac
  shift
done

cat <<EOF
This script will:
  - Clone github.com/manav8498/Hangar to $INSTALL_DIR
  - Generate a random admin token
  - Run docker compose up -d
Press Ctrl-C in the next 3 seconds to cancel.
EOF
sleep 3

say "Step 1: checking host and required tools."
OS_NAME="$(uname -s)"
case "$OS_NAME" in
  Darwin)
    DOCKER_HINT="Install Docker Desktop: https://www.docker.com/products/docker-desktop"
    ;;
  Linux)
    DOCKER_HINT="Install Docker Engine: https://docs.docker.com/engine/install/"
    ;;
  *)
    say "Unsupported OS: $OS_NAME. Hangar install supports macOS and Linux."
    exit 1
    ;;
esac

need_cmd git "git is required. Install Git, then rerun this script."
need_cmd curl "curl is required. Install curl, then rerun this script."
need_cmd openssl "openssl is required to generate HANGAR_ADMIN_TOKEN."
need_cmd docker "docker is required. $DOCKER_HINT"

if ! docker compose version >/dev/null 2>&1; then
  if command -v docker-compose >/dev/null 2>&1; then
    say "Docker Compose v2 is required. Legacy docker-compose is not enough."
  else
    say "Docker Compose v2 is required. $DOCKER_HINT"
  fi
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  say "Docker is installed, but the daemon is not reachable. Start Docker and rerun this script."
  exit 1
fi

say "Step 2: using install directory $INSTALL_DIR."
if [ -d "$INSTALL_DIR" ] && [ "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | sed -n '1p')" ]; then
  if [ "$FORCE" -ne 1 ]; then
    say "$INSTALL_DIR exists, use --force to overwrite or set HANGAR_DIR=..."
    exit 1
  fi
  run "Removing existing install directory." rm -rf "$INSTALL_DIR"
fi

say "Step 3: cloning Hangar."
run "Running git clone --depth 1 $REPO_URL $INSTALL_DIR" git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"

say "Step 4: writing .env."
cd "$INSTALL_DIR"
run "Copying .env.example to .env." cp .env.example .env
ADMIN_TOKEN="$(openssl rand -hex 16)"
say "Updating HANGAR_ADMIN_TOKEN in .env."
sed -i.bak "s/^HANGAR_ADMIN_TOKEN=.*/HANGAR_ADMIN_TOKEN=$ADMIN_TOKEN/" .env
run "Removing temporary .env backup." rm -f .env.bak
say "Generated random HANGAR_ADMIN_TOKEN. Stored in .env."
say "ANTHROPIC_API_KEY is not set. Without it, agents will use the deterministic fallback harness. To use real Claude responses, edit .env and add your key."

say "Step 5: starting Docker Compose."
run "Running docker compose up -d." docker compose up -d

say "Step 6: waiting for Hangar health."
i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS http://localhost:8080/healthz >/dev/null 2>&1; then
    printf '\n'
    break
  fi
  printf '.'
  i=$((i + 1))
  sleep 1
done

if [ "$i" -ge 60 ]; then
  printf '\n'
  say "Hangar stack did not come up within 60 seconds."
  exit 1
fi

cat <<EOF
Hangar is running.

Dashboard:  http://localhost:8080/dashboard/
API:        http://localhost:8080/

Security note: this stack accepts \`hgr_test_key\` as a
valid API key by default for local development. Before
exposing port 8080 beyond localhost, add
\`HANGAR_ACCEPT_TEST_KEY=0\` to .env and \`docker compose
restart api\`.

To create your first API key:
  cd $INSTALL_DIR
  docker compose exec api hangar admin create-api-key --name dev

To stop the stack:
  cd $INSTALL_DIR
  docker compose down

To use the Anthropic SDK pointed at this instance:
  from anthropic import Anthropic
  client = Anthropic(
      base_url="http://localhost:8080",
      api_key="<your-key-from-create-api-key>",
  )
EOF
