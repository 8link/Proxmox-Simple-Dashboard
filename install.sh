#!/usr/bin/env bash
# Proxmox Simple Dashboard — Installer / Uninstaller
# Usage:
#   Install:   curl -fsSL https://raw.githubusercontent.com/8link/Proxmox-Simple-Dashboard/main/install.sh | bash
#   Uninstall: curl -fsSL https://raw.githubusercontent.com/8link/Proxmox-Simple-Dashboard/main/install.sh | bash -s -- --uninstall

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
REPO="8link/Proxmox-Simple-Dashboard"
BRANCH="main"
RAW_BASE="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
INSTALL_DIR="/opt/simple_dashboard"
SERVICE_NAME="proxmox-simple-dashboard"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
DASHBOARD_PORT="8888"

# ── Colors ────────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
  YELLOW='\033[1;33m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'
else
  RED=''; GREEN=''; CYAN=''; YELLOW=''; BOLD=''; DIM=''; RESET=''
fi

# ── Helpers ───────────────────────────────────────────────────────────────────
info()    { echo -e "  ${CYAN}→${RESET}  $*"; }
ok()      { echo -e "  ${GREEN}✓${RESET}  $*"; }
warn()    { echo -e "  ${YELLOW}!${RESET}  $*"; }
fail()    { echo -e "  ${RED}✗${RESET}  $*" >&2; }
header()  { echo -e "\n${BOLD}$*${RESET}"; }
divider() { echo -e "${DIM}  ────────────────────────────────────────${RESET}"; }
blank()   { echo; }

need_root() {
  if [[ $EUID -ne 0 ]]; then
    fail "This script must be run as root."
    echo -e "  Try: ${BOLD}sudo bash $0 $*${RESET}"
    exit 1
  fi
}

check_python() {
  if ! command -v python3 &>/dev/null; then
    fail "python3 not found. Please install Python 3 and re-run."
    exit 1
  fi
  ok "Python found: $(python3 --version)"
}

download() {
  local url="$1" dest="$2"
  if command -v curl &>/dev/null; then
    curl -fsSL "$url" -o "$dest"
  elif command -v wget &>/dev/null; then
    wget -q "$url" -O "$dest"
  else
    fail "Neither curl nor wget found. Cannot download files."
    exit 1
  fi
}

host_ips() {
  hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$' || echo "localhost"
}

# ── Install ───────────────────────────────────────────────────────────────────
do_install() {
  need_root
  blank
  echo -e "${BOLD}${CYAN}  ╔══════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}${CYAN}  ║   Proxmox Simple Dashboard — Installer   ║${RESET}"
  echo -e "${BOLD}${CYAN}  ╚══════════════════════════════════════════╝${RESET}"
  blank
  divider

  # ── Step 1: Python check ───────────────────────────────────────────────────
  header "  [1/4] Checking requirements"
  check_python

  # ── Step 2: Create directory ───────────────────────────────────────────────
  header "  [2/4] Preparing install directory"
  if [[ -d "$INSTALL_DIR" ]]; then
    warn "Directory already exists: ${INSTALL_DIR}"
  else
    mkdir -p "$INSTALL_DIR"
    ok "Created: ${INSTALL_DIR}"
  fi

  # ── Step 3: Download files ─────────────────────────────────────────────────
  header "  [3/4] Downloading files"
  local files=("dashboard.py" "favicon.svg" "dashboard.conf.example")
  for file in "${files[@]}"; do
    info "Fetching ${file} ..."
    download "${RAW_BASE}/${file}" "${INSTALL_DIR}/${file}"
    ok "${file}"
  done

  # Copy example config only if no config exists yet
  if [[ ! -f "${INSTALL_DIR}/dashboard.conf" ]]; then
    cp "${INSTALL_DIR}/dashboard.conf.example" "${INSTALL_DIR}/dashboard.conf"
    ok "Created dashboard.conf from example (edit before starting!)"
  else
    warn "dashboard.conf already exists — skipping (your config is preserved)"
  fi

  # ── Step 4: Systemd service ────────────────────────────────────────────────
  header "  [4/4] Installing systemd service"
  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Proxmox Simple Dashboard
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/dashboard.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}" &>/dev/null
  ok "Service registered: ${SERVICE_NAME}"
  ok "Enabled on boot"

  # ── Summary ────────────────────────────────────────────────────────────────
  blank
  divider
  blank
  echo -e "${GREEN}${BOLD}  ✓ Installation complete!${RESET}"
  blank
  echo -e "${YELLOW}${BOLD}  ⚠  Required: configure the dashboard before starting${RESET}"
  blank
  echo -e "  Edit your config:"
  echo -e "  ${BOLD}  nano ${INSTALL_DIR}/dashboard.conf${RESET}"
  blank
  echo -e "  Fill in these required values:"
  echo -e "${DIM}  ┌──────────────────────────────────────────────────┐${RESET}"
  echo -e "${DIM}  │  PROXMOX_BASE_URL     https://your-host:8006     │${RESET}"
  echo -e "${DIM}  │  PROXMOX_TOKEN_ID     user@pam!token-name        │${RESET}"
  echo -e "${DIM}  │  PROXMOX_TOKEN_SECRET your-api-token-secret      │${RESET}"
  echo -e "${DIM}  └──────────────────────────────────────────────────┘${RESET}"
  blank
  echo -e "  Then start the service:"
  echo -e "  ${BOLD}  systemctl start ${SERVICE_NAME}${RESET}"
  blank
  echo -e "  Dashboard will be available at:"
  while IFS= read -r ip; do
    echo -e "  ${CYAN}${BOLD}  http://${ip}:${DASHBOARD_PORT}${RESET}"
  done < <(host_ips)
  blank
  echo -e "  Useful commands:"
  echo -e "${DIM}  systemctl status  ${SERVICE_NAME}${RESET}"
  echo -e "${DIM}  systemctl restart ${SERVICE_NAME}${RESET}"
  echo -e "${DIM}  journalctl -u ${SERVICE_NAME} -f${RESET}"
  blank
  divider
  blank
}

# ── Uninstall ─────────────────────────────────────────────────────────────────
do_uninstall() {
  need_root
  blank
  echo -e "${BOLD}${RED}  ╔══════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}${RED}  ║  Proxmox Simple Dashboard — Uninstaller  ║${RESET}"
  echo -e "${BOLD}${RED}  ╚══════════════════════════════════════════╝${RESET}"
  blank
  divider

  # ── Step 1: Stop service ───────────────────────────────────────────────────
  header "  [1/3] Stopping service"
  if systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    systemctl stop "${SERVICE_NAME}"
    ok "Service stopped"
  else
    warn "Service was not running"
  fi
  if systemctl is-enabled --quiet "${SERVICE_NAME}" 2>/dev/null; then
    systemctl disable "${SERVICE_NAME}" &>/dev/null
    ok "Service disabled"
  fi

  # ── Step 2: Remove service file ────────────────────────────────────────────
  header "  [2/3] Removing service file"
  if [[ -f "$SERVICE_FILE" ]]; then
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
    ok "Removed: ${SERVICE_FILE}"
  else
    warn "Service file not found — skipping"
  fi

  # ── Step 3: Remove install directory ──────────────────────────────────────
  header "  [3/3] Removing install directory"
  if [[ -d "$INSTALL_DIR" ]]; then
    if [[ -f "${INSTALL_DIR}/dashboard.conf" ]]; then
      cp "${INSTALL_DIR}/dashboard.conf" "/tmp/dashboard.conf.bak"
      warn "Config backed up to: /tmp/dashboard.conf.bak"
    fi
    rm -rf "$INSTALL_DIR"
    ok "Removed: ${INSTALL_DIR}"
  else
    warn "Install directory not found — skipping"
  fi

  blank
  divider
  blank
  echo -e "${GREEN}${BOLD}  ✓ Uninstall complete.${RESET}"
  blank
  divider
  blank
}

# ── Argument parsing ──────────────────────────────────────────────────────────
ACTION="install"
for arg in "$@"; do
  case "$arg" in
    --install)   ACTION="install" ;;
    --uninstall) ACTION="uninstall" ;;
    -h|--help)
      echo "Usage: $0 [--install|--uninstall]"
      echo "  --install    Install the dashboard (default)"
      echo "  --uninstall  Remove the dashboard and service"
      exit 0
      ;;
    *)
      fail "Unknown argument: ${arg}"
      echo "  Usage: $0 [--install|--uninstall]"
      exit 1
      ;;
  esac
done

case "$ACTION" in
  install)   do_install ;;
  uninstall) do_uninstall ;;
esac
