#!/usr/bin/env bash
# ============================================================================
# FortiVPN Client — Universal Installer
# Supports: Ubuntu/Debian, Fedora/RHEL/CentOS, Arch Linux, openSUSE,
#           Alpine Linux, Void Linux. Hints for Gentoo and NixOS.
# Long-tail / unknown distros: prints required components and points to the
# Flatpak (FortiVPN/flatpak/) which works identically on every distribution.
# ============================================================================
set -euo pipefail

APP_NAME="fortivpn-client"
APP_ID="com.github.fortivpn_client"
INSTALL_PREFIX="/usr/local"
BIN_DIR="$INSTALL_PREFIX/bin"
SHARE_DIR="$INSTALL_PREFIX/share"
APP_DIR="$SHARE_DIR/$APP_NAME"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ---- Detect distro ----
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID="${ID:-unknown}"
        DISTRO_LIKE="${ID_LIKE:-$DISTRO_ID}"
    elif command -v lsb_release &>/dev/null; then
        DISTRO_ID=$(lsb_release -si | tr '[:upper:]' '[:lower:]')
        DISTRO_LIKE="$DISTRO_ID"
    else
        error "Cannot detect distribution. Install manually."
    fi
    info "Detected: $DISTRO_ID ($DISTRO_LIKE)"

    # NixOS bails out before any package work — install.sh cannot manage Nix.
    if [ -f /etc/NIXOS ] || [ "$DISTRO_ID" = "nixos" ]; then
        echo ""
        warn "NixOS detected."
        warn "install.sh cannot manage packages on NixOS."
        warn "Use one of:"
        warn "  • Flatpak (recommended):  see FortiVPN/flatpak/README.md"
        warn "  • Write a flake / package: bundle openfortivpn + python3 +"
        warn "    pygobject3 + gtk4 + libadwaita + polkit yourself."
        error "Aborting on NixOS."
    fi
}

# ---- Sanity: openfortivpn must be present after dep install ----
require_openfortivpn() {
    if ! command -v openfortivpn &>/dev/null; then
        error "openfortivpn was not installed/found in PATH. Install it via your package manager and re-run, or use the Flatpak."
    fi
}

# ---- Guarantee openfortivpn is installed, installing it if missing ----
# Safe to call from any entry point (install / fix-sudo / fix-permissions).
# Detects the distro on demand and installs ONLY openfortivpn.
ensure_openfortivpn() {
    if command -v openfortivpn &>/dev/null; then
        return 0
    fi

    info "openfortivpn not found in PATH — installing it now..."
    if [ -z "${DISTRO_ID:-}" ]; then
        detect_distro
    fi

    local SU
    case "$DISTRO_ID" in
        ubuntu|debian|linuxmint|pop|elementary|zorin)
            sudo apt-get update -qq
            sudo apt-get install -y openfortivpn ;;
        fedora|rhel|centos|rocky|alma)
            sudo dnf install -y openfortivpn ;;
        arch|manjaro|endeavouros|garuda)
            sudo pacman -Sy --noconfirm --needed openfortivpn ;;
        opensuse*|sles)
            sudo zypper install -y openfortivpn ;;
        alpine)
            SU=$(_pick_root_helper); $SU apk add openfortivpn ;;
        void)
            SU=$(_pick_root_helper); $SU xbps-install -Sy openfortivpn ;;
        gentoo)
            warn "Gentoo: install net-vpn/openfortivpn manually (review USE flags),"
            warn "or use the Flatpak — see FortiVPN/flatpak/README.md."
            error "openfortivpn is required and cannot be auto-installed on Gentoo." ;;
        *)
            case "$DISTRO_LIKE" in
                *debian*|*ubuntu*)
                    sudo apt-get update -qq
                    sudo apt-get install -y openfortivpn ;;
                *fedora*|*rhel*)
                    sudo dnf install -y openfortivpn ;;
                *arch*)
                    sudo pacman -Sy --noconfirm --needed openfortivpn ;;
                *suse*)
                    sudo zypper install -y openfortivpn ;;
                *alpine*)
                    SU=$(_pick_root_helper); $SU apk add openfortivpn ;;
                *void*)
                    SU=$(_pick_root_helper); $SU xbps-install -Sy openfortivpn ;;
                *)
                    warn "Unknown distro ($DISTRO_ID / $DISTRO_LIKE) — cannot auto-install openfortivpn."
                    warn "Install it manually with your distro's package manager, or use the"
                    warn "Flatpak — see FortiVPN/flatpak/README.md."
                    error "openfortivpn is required and could not be auto-installed." ;;
            esac
            ;;
    esac

    if ! command -v openfortivpn &>/dev/null; then
        error "openfortivpn install appeared to succeed but the binary is still not in PATH. Install it manually or use the Flatpak."
    fi
    success "openfortivpn is installed: $(command -v openfortivpn)"
}

# ---- Sanity: Python >= 3.10 (Adw.NavigationView, modern libadwaita bits) ----
require_python_310() {
    if ! command -v python3 &>/dev/null; then
        error "python3 not found. Install Python >= 3.10 and re-run."
    fi
    local pyver
    pyver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0")
    local major minor
    major="${pyver%%.*}"
    minor="${pyver##*.}"
    if [ "${major:-0}" -lt 3 ] || { [ "${major:-0}" -eq 3 ] && [ "${minor:-0}" -lt 10 ]; }; then
        error "Python $pyver is too old. FortiVPN Client requires Python >= 3.10 (Adw.NavigationView and a recent libadwaita)."
    fi
    info "Python $pyver — OK."
}

# ---- Package manager helpers ----
# NOTE: No WebKit dependency — SAML auth uses the default system browser.

install_packages_apt() {
    info "Installing dependencies via apt..."
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends \
        openfortivpn \
        python3 \
        python3-gi \
        python3-gi-cairo \
        gir1.2-gtk-4.0 \
        gir1.2-adw-1 \
        gir1.2-ayatanaappindicator3-0.1 \
        libadwaita-1-0 \
        polkitd \
        pkexec
}

install_packages_dnf() {
    info "Installing dependencies via dnf..."
    sudo dnf install -y \
        openfortivpn \
        python3 \
        python3-gobject \
        gtk4 \
        libadwaita \
        libayatana-appindicator-gtk3 \
        gobject-introspection \
        polkit
    # Try to install the GI typelib for AyatanaAppIndicator (needed for tray)
    sudo dnf install -y \
        typelib-1_0-AyatanaAppIndicator3-0_1 2>/dev/null || \
        warn "AyatanaAppIndicator typelib not found in repos — tray icon may not work."
}

install_packages_pacman() {
    info "Installing dependencies via pacman..."
    sudo pacman -Sy --noconfirm --needed \
        openfortivpn \
        python \
        python-gobject \
        gtk4 \
        libadwaita \
        libayatana-appindicator \
        polkit
}

install_packages_zypper() {
    info "Installing dependencies via zypper..."
    sudo zypper install -y \
        openfortivpn \
        python3 \
        python3-gobject \
        python3-gobject-Gtk \
        gtk4 \
        libadwaita-1-0 \
        polkit
}

install_packages_apk() {
    info "Installing dependencies via apk (Alpine)..."
    # Alpine commonly ships doas instead of sudo — apk root invocation handled
    # by whichever wrapper exists.
    local SU
    SU=$(_pick_root_helper)
    $SU apk add --no-cache \
        openfortivpn \
        python3 \
        py3-gobject3 \
        gtk4.0 \
        libadwaita \
        polkit
}

install_packages_xbps() {
    info "Installing dependencies via xbps-install (Void)..."
    local SU
    SU=$(_pick_root_helper)
    $SU xbps-install -Sy \
        openfortivpn \
        python3 \
        python3-gobject \
        gtk4 \
        libadwaita \
        polkit
}

# Gentoo: print suggested ebuilds; do NOT auto-emerge (USE flags are user choice).
install_packages_gentoo_hint() {
    warn "Gentoo detected — auto-emerge is intentionally disabled."
    warn "Suggested ebuilds (review USE flags first):"
    warn "  net-vpn/openfortivpn"
    warn "  dev-lang/python  (>=3.10)"
    warn "  dev-python/pygobject"
    warn "  gui-libs/gtk:4"
    warn "  gui-libs/libadwaita"
    warn "  sys-auth/polkit"
    warn ""
    warn "Then re-run: ./install.sh install   to copy app files into place."
}

# Generic fallback when we cannot identify the package manager.
generic_fallback_message() {
    warn "No supported package manager matched."
    warn ""
    warn "Install these components with whatever your distro provides:"
    warn "  • openfortivpn          (>= 1.17)"
    warn "  • python3               (>= 3.10)"
    warn "  • PyGObject             (python3-gi / py3-gobject3 / python-gobject)"
    warn "  • GTK 4                 (gtk4 / gtk4.0)"
    warn "  • libadwaita            (>= 1.4 for Adw.NavigationView)"
    warn "  • polkit                (for pkexec; or doas + sudoers as alt)"
    warn ""
    warn "Or skip distro packaging entirely and use the Flatpak — it works"
    warn "identically on every distribution:"
    warn "  see FortiVPN/flatpak/README.md"
}

# Pick `sudo` or `doas` (Alpine/Void typically use doas). Fall back to running
# as root directly if neither exists and uid==0.
_pick_root_helper() {
    if command -v sudo &>/dev/null; then
        echo "sudo"
    elif command -v doas &>/dev/null; then
        echo "doas"
    elif [ "$(id -u)" -eq 0 ]; then
        echo ""
    else
        error "Neither sudo nor doas is installed, and you are not root."
    fi
}

install_deps() {
    case "$DISTRO_ID" in
        ubuntu|debian|linuxmint|pop|elementary|zorin)
            install_packages_apt ;;
        fedora|rhel|centos|rocky|alma)
            install_packages_dnf ;;
        arch|manjaro|endeavouros|garuda)
            install_packages_pacman ;;
        opensuse*|sles)
            install_packages_zypper ;;
        alpine)
            install_packages_apk ;;
        void)
            install_packages_xbps ;;
        gentoo)
            install_packages_gentoo_hint
            return 0 ;;
        *)
            case "$DISTRO_LIKE" in
                *debian*|*ubuntu*)  install_packages_apt ;;
                *fedora*|*rhel*)    install_packages_dnf ;;
                *arch*)             install_packages_pacman ;;
                *suse*)             install_packages_zypper ;;
                *alpine*)           install_packages_apk ;;
                *void*)             install_packages_xbps ;;
                *gentoo*)           install_packages_gentoo_hint; return 0 ;;
                *)
                    generic_fallback_message
                    return 0 ;;
            esac
            ;;
    esac

    # After any real install, openfortivpn must be present.
    require_python_310
    # Final guarantee: openfortivpn is the one binary the GUI cannot live without.
    # If the bulk dep install above missed it for any reason, install it here.
    ensure_openfortivpn
}

# ---- Install application files ----
install_app() {
    info "Installing application to $APP_DIR..."

    sudo mkdir -p "$APP_DIR"
    sudo mkdir -p "$BIN_DIR"
    sudo mkdir -p "$SHARE_DIR/applications"
    sudo mkdir -p "$SHARE_DIR/icons/hicolor/scalable/apps"
    sudo mkdir -p "$SHARE_DIR/icons/hicolor/symbolic/apps"
    sudo mkdir -p "/etc/polkit-1/rules.d"

    # Main script — find it relative to installer location
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SRC_PY=""
    for candidate in \
        "$SCRIPT_DIR/src/fortivpn_client.py" \
        "$SCRIPT_DIR/fortivpn_client.py" \
        "$SCRIPT_DIR/src/fortivpn-client.py" \
        "$SCRIPT_DIR/fortivpn-client.py"; do
        if [ -f "$candidate" ]; then
            SRC_PY="$candidate"
            break
        fi
    done
    if [ -z "$SRC_PY" ]; then
        error "Cannot find fortivpn_client.py — expected in src/ or next to install.sh"
    fi
    info "Source found: $SRC_PY"
    sudo cp "$SRC_PY" "$APP_DIR/fortivpn_client.py"
    sudo chmod 644 "$APP_DIR/fortivpn_client.py"

    # Launcher
    sudo tee "$BIN_DIR/fortivpn-client" > /dev/null << 'LAUNCHER'
#!/usr/bin/env bash
exec python3 /usr/local/share/fortivpn-client/fortivpn_client.py "$@"
LAUNCHER
    sudo chmod 755 "$BIN_DIR/fortivpn-client"

    # Desktop file
    sudo tee "$SHARE_DIR/applications/$APP_ID.desktop" > /dev/null << DESKTOP
[Desktop Entry]
Type=Application
Name=FortiVPN Client
GenericName=VPN Client
Comment=SAML-based OpenFortiVPN client for GNOME
Exec=fortivpn-client
Icon=$APP_ID
Terminal=false
Categories=Network;Security;
Keywords=vpn;fortinet;saml;sso;openfortivpn;
StartupNotify=true
X-GNOME-UsesNotifications=true
DESKTOP

    # Install SVG icon — search in data/ or root
    ICON_SVG=""
    for candidate in \
        "$SCRIPT_DIR/data/$APP_ID.svg" \
        "$SCRIPT_DIR/$APP_ID.svg" \
        "$SCRIPT_DIR/data/icon.svg" \
        "$SCRIPT_DIR/icon.svg"; do
        if [ -f "$candidate" ]; then
            ICON_SVG="$candidate"
            break
        fi
    done
    if [ -n "$ICON_SVG" ]; then
        sudo cp "$ICON_SVG" "$SHARE_DIR/icons/hicolor/scalable/apps/$APP_ID.svg"
        sudo chmod 644 "$SHARE_DIR/icons/hicolor/scalable/apps/$APP_ID.svg"
    else
        warn "No icon SVG found, generating default..."
        _generate_icon
    fi

    # Polkit rule: allow openfortivpn without repeated password for wheel/sudo group
    sudo tee "/etc/polkit-1/rules.d/50-$APP_NAME.rules" > /dev/null << 'POLKIT'
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.policykit.exec" &&
        action.lookup("program") == "/usr/bin/openfortivpn" &&
        (subject.isInGroup("wheel") || subject.isInGroup("sudo"))) {
        return polkit.Result.AUTH_ADMIN_KEEP;
    }
    if (action.id == "org.freedesktop.policykit.exec" &&
        action.lookup("program") == "/usr/sbin/openfortivpn" &&
        (subject.isInGroup("wheel") || subject.isInGroup("sudo"))) {
        return polkit.Result.AUTH_ADMIN_KEEP;
    }
});
POLKIT
    sudo chmod 644 "/etc/polkit-1/rules.d/50-$APP_NAME.rules"

    # Update icon cache
    if command -v gtk-update-icon-cache &>/dev/null; then
        sudo gtk-update-icon-cache -f "$SHARE_DIR/icons/hicolor/" 2>/dev/null || true
    fi

    # Update desktop database
    if command -v update-desktop-database &>/dev/null; then
        sudo update-desktop-database "$SHARE_DIR/applications/" 2>/dev/null || true
    fi
}

_generate_icon() {
    info "Generating application icon..."
    sudo tee "$SHARE_DIR/icons/hicolor/scalable/apps/$APP_ID.svg" > /dev/null << 'SVG'
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#3584e4"/>
      <stop offset="100%" stop-color="#1a5fb4"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="14" fill="url(#bg)"/>
  <g transform="translate(32,32)" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
    <path d="M0-18 C10-18 16-14 16-6 C16 8 8 16 0 20 C-8 16-16 8-16-6 C-16-14-10-18 0-18Z" fill="rgba(255,255,255,0.15)"/>
    <rect x="-7" y="-2" width="14" height="12" rx="2" fill="rgba(255,255,255,0.3)" stroke="#fff"/>
    <path d="M-4-2 L-4-6 C-4-9 4-9 4-6 L4-2" fill="none"/>
    <circle cx="0" cy="4" r="2" fill="#fff"/>
    <line x1="0" y1="6" x2="0" y2="8"/>
  </g>
</svg>
SVG
    sudo chmod 644 "$SHARE_DIR/icons/hicolor/scalable/apps/$APP_ID.svg"
}

# ---- Fix permissions on installed files ----
fix_permissions() {
    info "Fixing file permissions..."

    # The GUI is useless without openfortivpn — guarantee it's installed
    # rather than silently passing here.
    ensure_openfortivpn

    sudo chmod 644 "$APP_DIR/fortivpn_client.py" 2>/dev/null || true
    sudo chmod 755 "$BIN_DIR/fortivpn-client" 2>/dev/null || true
    sudo chmod 644 "$SHARE_DIR/icons/hicolor/scalable/apps/$APP_ID.svg" 2>/dev/null || true
    sudo chmod 644 "$SHARE_DIR/applications/$APP_ID.desktop" 2>/dev/null || true
    sudo chmod 644 "/etc/polkit-1/rules.d/50-$APP_NAME.rules" 2>/dev/null || true

    # Make sure the icon directory is traversable
    sudo chmod 755 "$SHARE_DIR/icons/hicolor/scalable/apps/" 2>/dev/null || true
    sudo chmod 755 "$SHARE_DIR/icons/hicolor/scalable/" 2>/dev/null || true
    sudo chmod 755 "$SHARE_DIR/icons/hicolor/" 2>/dev/null || true

    success "Permissions fixed."
}

# ---- Fix sudo / polkit for openfortivpn ----
fix_sudo() {
    info "Setting up passwordless openfortivpn via polkit + sudoers..."

    # 0. fix-sudo is meaningless without the binary — guarantee it first.
    ensure_openfortivpn

    # 1. Polkit rule (for pkexec) — works regardless of sudo/doas choice.
    sudo mkdir -p "/etc/polkit-1/rules.d" 2>/dev/null \
        || doas mkdir -p "/etc/polkit-1/rules.d"
    _root_tee "/etc/polkit-1/rules.d/50-$APP_NAME.rules" << 'POLKIT'
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.policykit.exec" &&
        (action.lookup("program") == "/usr/bin/openfortivpn" ||
         action.lookup("program") == "/usr/sbin/openfortivpn") &&
        (subject.isInGroup("wheel") || subject.isInGroup("sudo"))) {
        return polkit.Result.YES;
    }
});
POLKIT
    _root_chmod 644 "/etc/polkit-1/rules.d/50-$APP_NAME.rules"
    success "Polkit rule installed: openfortivpn via pkexec without password."

    # 2. Sudoers rule — only if `sudo` is the system's privilege tool.
    # Alpine/Void typically use doas; configuring sudoers on those is wrong.
    if ! command -v sudo &>/dev/null && command -v doas &>/dev/null; then
        warn "System uses doas (no sudo found) — skipping sudoers step."
        warn "If you want passwordless openfortivpn under doas, add to /etc/doas.conf:"
        warn "  permit nopass :wheel cmd $(command -v openfortivpn 2>/dev/null || echo openfortivpn)"
    else
        OPENFORTIVPN_PATH=$(command -v openfortivpn 2>/dev/null || echo "/usr/bin/openfortivpn")
        sudo tee "/etc/sudoers.d/fortivpn-client" > /dev/null << SUDOERS
# Allow members of wheel/sudo to run openfortivpn without password
%wheel ALL=(root) NOPASSWD: $OPENFORTIVPN_PATH
%sudo  ALL=(root) NOPASSWD: $OPENFORTIVPN_PATH
SUDOERS
        sudo chmod 440 "/etc/sudoers.d/fortivpn-client"

        # Validate sudoers
        if sudo visudo -cf "/etc/sudoers.d/fortivpn-client" &>/dev/null; then
            success "Sudoers rule installed: $OPENFORTIVPN_PATH without password."
        else
            warn "Sudoers syntax check failed — removing the rule."
            sudo rm -f "/etc/sudoers.d/fortivpn-client"
        fi
    fi

    echo ""
    # When fix-sudo is invoked via `sudo bash install.sh fix-sudo`, plain
    # `groups` reports root's groups. Always check the invoking user instead.
    local INVOKING_USER="${SUDO_USER:-${USER:-$(id -un)}}"
    local USER_GROUPS
    USER_GROUPS=$(id -nG "$INVOKING_USER" 2>/dev/null || echo "")
    info "Your user must be in the 'wheel' or 'sudo' group:"
    info "  User: $INVOKING_USER"
    info "  Groups: $USER_GROUPS"
    if echo " $USER_GROUPS " | grep -qwE 'wheel|sudo'; then
        success "You are in the correct group."
    else
        warn "$INVOKING_USER is NOT in wheel/sudo. Add yourself:"
        warn "  sudo usermod -aG wheel $INVOKING_USER   # Fedora/Arch"
        warn "  sudo usermod -aG sudo $INVOKING_USER    # Ubuntu/Debian"
        warn "Then log out and back in."
    fi
}

# Tee a heredoc into a root-owned file using whichever helper is available.
_root_tee() {
    local target="$1"
    if command -v sudo &>/dev/null; then
        sudo tee "$target" > /dev/null
    elif command -v doas &>/dev/null; then
        doas tee "$target" > /dev/null
    else
        tee "$target" > /dev/null
    fi
}

_root_chmod() {
    local mode="$1"; shift
    if command -v sudo &>/dev/null; then
        sudo chmod "$mode" "$@"
    elif command -v doas &>/dev/null; then
        doas chmod "$mode" "$@"
    else
        chmod "$mode" "$@"
    fi
}

# ---- Uninstall ----
uninstall_app() {
    info "Uninstalling FortiVPN Client..."
    sudo rm -f "$BIN_DIR/fortivpn-client"
    sudo rm -rf "$APP_DIR"
    sudo rm -f "$SHARE_DIR/applications/$APP_ID.desktop"
    sudo rm -f "$SHARE_DIR/icons/hicolor/scalable/apps/$APP_ID.svg"
    sudo rm -f "/etc/polkit-1/rules.d/50-$APP_NAME.rules"
    sudo rm -f "/etc/sudoers.d/fortivpn-client"
    if command -v gtk-update-icon-cache &>/dev/null; then
        sudo gtk-update-icon-cache -f "$SHARE_DIR/icons/hicolor/" 2>/dev/null || true
    fi
    success "FortiVPN Client has been uninstalled."
}

# ---- Main ----
print_banner() {
    echo -e "${BOLD}"
    echo "╔═══════════════════════════════════════════╗"
    echo "║       FortiVPN Client — Installer         ║"
    echo "║   Native GNOME client for openfortivpn    ║"
    echo "╚═══════════════════════════════════════════╝"
    echo -e "${NC}"
}

usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  install           Install dependencies + application (default)"
    echo "  uninstall         Remove application files"
    echo "  deps-only         Only install system dependencies"
    echo "  fix-permissions   Fix file permission issues"
    echo "  fix-sudo          Set up passwordless openfortivpn (polkit + sudoers)"
    echo "  help              Show this help"
}

main() {
    print_banner

    local action="${1:-install}"

    case "$action" in
        install)
            detect_distro
            install_deps
            install_app
            echo ""
            success "Installation complete!"
            echo ""
            info "Launch from your app grid or run: ${BOLD}fortivpn-client${NC}"
            info ""
            info "Optional next steps:"
            info "  ${BOLD}./install.sh fix-sudo${NC}  — skip password prompt when connecting"
            info ""
            info "For tray icon on GNOME, install the AppIndicator extension:"
            info "  https://extensions.gnome.org/extension/615/appindicator-support/"
            ;;
        uninstall)
            uninstall_app
            ;;
        deps-only)
            detect_distro
            install_deps
            success "Dependencies installed."
            ;;
        fix-permissions|fix-perms)
            fix_permissions
            ;;
        fix-sudo|fix-auth)
            fix_sudo
            ;;
        -h|--help|help)
            usage
            ;;
        *)
            error "Unknown action: $action. Run '$0 help' for usage."
            ;;
    esac
}

main "$@"
