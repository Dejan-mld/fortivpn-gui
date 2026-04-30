#!/usr/bin/env python3
"""
FortiVPN SAML Client — A native GNOME client for openfortivpn with SAML support.

Uses openfortivpn's built-in --saml-login which:
  1. Starts a local HTTP server on port 8020
  2. User opens https://host:port/remote/saml/start?redirect=1 in browser
  3. After SAML auth, FortiGate redirects to http://127.0.0.1:8020/?id=<session>
  4. openfortivpn catches the session ID and establishes the tunnel
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

import json
import os
import sys
import signal
import subprocess
import threading
import time
import re
import logging
import shutil
import webbrowser
from pathlib import Path

from gi.repository import Gtk, Adw, Gio, GLib, Gdk

APP_ID = "com.github.fortivpn_client"
APP_NAME = "FortiVPN Client"
APP_VERSION = "1.2.0"
APP_ICON = "network-vpn-symbolic"
CONFIG_DIR = Path(GLib.get_user_config_dir()) / "fortivpn-client"
CONFIG_FILE = CONFIG_DIR / "profiles.json"

CSS = b"""
.hero-card {
    border-radius: 14px;
    padding: 22px 20px;
    margin: 4px 0 4px 0;
    transition: background 200ms ease;
}
.hero-card.connected {
    background: alpha(@success_bg_color, 0.55);
    color: @success_fg_color;
}
.hero-card.disconnected {
    background: alpha(@card_bg_color, 1.0);
}
.hero-card.connecting {
    background: alpha(@accent_bg_color, 0.55);
    color: @accent_fg_color;
}
.hero-icon {
    -gtk-icon-size: 56px;
    opacity: 0.9;
    margin-bottom: 6px;
}
.hero-title {
    font-size: 20pt;
    font-weight: 700;
    letter-spacing: -0.01em;
}
.hero-subtitle {
    opacity: 0.75;
    font-size: 11pt;
}
.hero-card button.disconnect-pill {
    margin-top: 12px;
}
"""

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fortivpn")


# ---------------------------------------------------------------------------
# Trusted-cert auto-capture
#
# When connecting to a gateway whose certificate is not yet whitelisted,
# openfortivpn refuses the tunnel and prints the gateway's SHA-256 digest in
# one of two forms:
#   1. 64 contiguous hex chars, e.g. `sha256:abcdef...64hex`
#   2. 32 colon-separated hex byte pairs, e.g. `AB:CD:EF:...:89` (×32)
# CERT_DIGEST_RE matches either form. The lookarounds prevent partial matches
# inside a longer hex/colon run. Captured strings are normalised by stripping
# colons and lowercasing — the result is always 64 hex chars.
#
# CERT_ERROR_MARKERS gates the digest pickup: we only treat a hex match as a
# digest when it appears AFTER one of these substrings has been seen on the
# current process's output, so unrelated hex (PIDs, addresses, debug dumps)
# never poisons the profile.
# ---------------------------------------------------------------------------

CERT_DIGEST_RE = re.compile(
    r"(?<![0-9a-fA-F:])"
    r"(?:[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){31}|[0-9a-fA-F]{64})"
    r"(?![0-9a-fA-F:])"
)

CERT_ERROR_MARKERS = (
    "certificate validation failed",
    "gateway certificate",
    "trusted-cert",
    "certificate digest",
)


# ---------------------------------------------------------------------------
# Flatpak sandbox awareness
#
# When the app runs inside a Flatpak sandbox we cannot exec openfortivpn
# directly: it needs root and access to /dev/net/tun on the host.  Every
# privileged command must therefore be routed through `flatpak-spawn --host`
# (which talks to the org.freedesktop.Flatpak portal — finish-args grants the
# `--talk-name=org.freedesktop.Flatpak` permission for exactly this).
#
# The native install path is unchanged: outside Flatpak `host_cmd` is a
# no-op, so subprocess invocations look identical to before.
# ---------------------------------------------------------------------------

def is_flatpak() -> bool:
    return Path("/.flatpak-info").exists() or bool(os.environ.get("FLATPAK_ID"))


def host_cmd(cmd: list[str]) -> list[str]:
    """Wrap a command list so it runs on the host when we are sandboxed."""
    if is_flatpak():
        return ["flatpak-spawn", "--host"] + cmd
    return cmd


# ---------------------------------------------------------------------------
# Profile storage
# ---------------------------------------------------------------------------

def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def load_profiles() -> list[dict]:
    ensure_dirs()
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return []
    return []

def save_profiles(profiles: list[dict]):
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(profiles, indent=2))


# ---------------------------------------------------------------------------
# Byte formatter
# ---------------------------------------------------------------------------

def fmt_bytes(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    elif b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    elif b < 1024 ** 3:
        return f"{b / 1024**2:.1f} MB"
    else:
        return f"{b / 1024**3:.2f} GB"


def fmt_rate(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.0f} B/s"
    elif bps < 1024 ** 2:
        return f"{bps / 1024:.1f} KB/s"
    elif bps < 1024 ** 3:
        return f"{bps / 1024**2:.1f} MB/s"
    else:
        return f"{bps / 1024**3:.2f} GB/s"


# ---------------------------------------------------------------------------
# VPN Controller
# ---------------------------------------------------------------------------

class VPNController:
    """Wraps openfortivpn process. For SAML, uses --saml-login and auto-opens browser."""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.connected = False
        self._ppp_iface: str | None = None
        self.bytes_tx: int = 0
        self.bytes_rx: int = 0

        # Callbacks (called on GLib main thread)
        self.on_status_change: callable = None
        self.on_log_line: callable = None
        self.on_traffic_update: callable = None
        self.on_cert_captured: callable = None

        # Trusted-cert auto-capture state.
        # _cert_retry_done: latched True after a digest is emitted, so a
        #   second cert error during the same user-initiated connect cycle
        #   never triggers a second auto-retry. Reset on user-initiated
        #   connect() (i.e. _is_retry=False), preserved on auto-retry.
        # _cert_error_seen: per-process flag — True once a cert-error marker
        #   has been seen, so unrelated hex never gets picked up.
        self._cert_retry_done = False
        self._cert_error_seen = False

    @staticmethod
    def find_binary() -> str | None:
        # Inside Flatpak `shutil.which` only sees the sandbox PATH where
        # openfortivpn is absent. Ask the host instead.
        if is_flatpak():
            try:
                r = subprocess.run(
                    ["flatpak-spawn", "--host", "which", "openfortivpn"],
                    capture_output=True, text=True, timeout=5, check=False,
                )
                path = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
                return path or None
            except Exception:
                return None
        return shutil.which("openfortivpn")

    def connect(self, host: str, port: str, saml: bool = True,
                realm: str = "", trusted_cert: str = "",
                extra_args: list[str] | None = None,
                _is_retry: bool = False):
        if self.process and self.process.poll() is None:
            self._emit_log("Already connected or connecting.")
            return

        # Loop guard: only reset on a fresh user-initiated connect. The auto
        # cert-retry path passes _is_retry=True, preserving _cert_retry_done
        # so a second cert mismatch during the retry cannot re-trigger.
        if not _is_retry:
            self._cert_retry_done = False
        self._cert_error_seen = False

        binary = self.find_binary()
        if not binary:
            self._emit_log("ERROR: openfortivpn not found! Install it with your package manager.")
            return

        # Build the openfortivpn argument list (without pkexec/sudo yet)
        vpn_args = [f"{host}:{port}"]

        if saml:
            vpn_args.append("--saml-login")

        if realm:
            vpn_args += ["--realm", realm]
        if trusted_cert:
            vpn_args += ["--trusted-cert", trusted_cert]

        # Filter extra_args: remove stale "saml" entries and empty strings
        if extra_args:
            filtered = [a for a in extra_args if a and a.lower() != "saml"]
            vpn_args += filtered

        # We use sudo instead of pkexec because pkexec does NOT relay
        # stdout/stderr back to the calling process reliably.
        # The installer's fix-sudo command sets up NOPASSWD for openfortivpn.
        # Inside Flatpak the whole thing is wrapped by flatpak-spawn --host so
        # the actual openfortivpn execution happens on the host (it needs
        # /dev/net/tun and root, neither of which exist in the sandbox).
        cmd = host_cmd(["sudo", "--non-interactive", binary] + vpn_args)

        # If sudo non-interactive fails (no NOPASSWD rule), fall back to pkexec
        self._use_pkexec_fallback = False
        self._binary = binary
        self._vpn_args = vpn_args

        self._emit_log(f">> Starting: {' '.join(cmd)}")
        self._stop.clear()
        self.bytes_tx = 0
        self.bytes_rx = 0
        self._ppp_iface = None

        try:
            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except Exception as e:
            self._emit_log(f"ERROR: {e}")
            return

        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        browser_opened = False
        saml_url = None
        sudo_failed = False
        try:
            for line in self.process.stdout:
                line = line.rstrip("\n")

                # Detect sudo failure (no NOPASSWD rule)
                if "sudo" in line.lower() and ("password" in line.lower() or "sorry" in line.lower()):
                    sudo_failed = True
                    self._emit_log(">> sudo without password not available, falling back to pkexec...")
                    break

                self._emit_log(line)
                self._scan_cert(line)

                # Detect the SAML auth URL from openfortivpn output
                # openfortivpn prints: INFO: Authenticate at 'https://host:port/remote/saml/start?redirect=1'
                if not browser_opened and ("Authenticate at" in line or "saml/start" in line):
                    url_match = re.search(r"'(https?://[^']+)'", line)
                    if not url_match:
                        url_match = re.search(r"(https?://\S+)", line)
                    if url_match:
                        saml_url = url_match.group(1)
                        self._emit_log(f">> Opening browser for SAML login...")
                        webbrowser.open(saml_url)
                        browser_opened = True

                # Also detect "Listening for SAML login on port XXXX"
                # If we see this but haven't opened browser yet, build the URL ourselves
                if not browser_opened and "Listening for SAML" in line:
                    # openfortivpn is ready, open browser proactively
                    port_match = re.search(r"port\s+(\d+)", line)
                    # We'll wait for the "Authenticate at" line which comes next
                    pass

                # Detect tunnel up
                if "Tunnel is up and running" in line:
                    self.connected = True
                    self._emit_status()
                    self._detect_interface()
                    threading.Thread(target=self._traffic_loop, daemon=True).start()

                # Detect tunnel down
                if any(s in line.lower() for s in ("logged out", "tunnel is shutting down",
                                                    "terminated", "gateway does not support")):
                    self.connected = False
                    self._emit_status()

                if self._stop.is_set():
                    break
        except Exception as e:
            self._emit_log(f">> Reader error: {e}")
        finally:
            self.connected = False
            self._emit_status()

        # Fallback: if sudo failed, retry with pkexec
        if sudo_failed:
            # Kill the stuck sudo process
            try:
                self.process.kill()
            except Exception:
                pass
            self._emit_log(">> Retrying with pkexec (you will see a password dialog)...")
            cmd = host_cmd(["pkexec", self._binary] + self._vpn_args)
            self._emit_log(f">> Starting: {' '.join(cmd)}")
            try:
                self.process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                )
                # Re-run reader for pkexec (non-recursive, just loop again)
                self._reader_pkexec()
            except Exception as e:
                self._emit_log(f"ERROR: {e}")

    def _reader_pkexec(self):
        """Reader for pkexec fallback. pkexec may not relay output well, so also open browser proactively."""
        browser_opened = False
        try:
            # With pkexec, openfortivpn output may not come through.
            # Open browser proactively after a short delay if SAML is enabled.
            if "--saml-login" in self._vpn_args:
                host_port = self._vpn_args[0]
                saml_url = f"https://{host_port}/remote/saml/start?redirect=1"
                # Give openfortivpn 2 seconds to start its HTTP server on port 8020
                time.sleep(2)
                self._emit_log(f">> Opening browser: {saml_url}")
                webbrowser.open(saml_url)
                browser_opened = True

            for line in self.process.stdout:
                line = line.rstrip("\n")
                self._emit_log(line)
                self._scan_cert(line)

                if not browser_opened and ("Authenticate at" in line or "saml/start" in line):
                    url_match = re.search(r"'(https?://[^']+)'", line)
                    if not url_match:
                        url_match = re.search(r"(https?://\S+)", line)
                    if url_match:
                        webbrowser.open(url_match.group(1))
                        browser_opened = True

                if "Tunnel is up and running" in line:
                    self.connected = True
                    self._emit_status()
                    self._detect_interface()
                    threading.Thread(target=self._traffic_loop, daemon=True).start()

                if any(s in line.lower() for s in ("logged out", "tunnel is shutting down", "terminated")):
                    self.connected = False
                    self._emit_status()

                if self._stop.is_set():
                    break
        except Exception:
            pass
        finally:
            self.connected = False
            self._emit_status()

    def _detect_interface(self):
        """Find ppp/tun interface."""
        try:
            r = subprocess.run(["ip", "-brief", "link"], capture_output=True, text=True, timeout=3)
            for iline in r.stdout.strip().splitlines():
                name = iline.split()[0]
                if name.startswith(("ppp", "tun")):
                    self._ppp_iface = name
                    self._emit_log(f">> Detected interface: {name}")
                    return
        except Exception:
            pass
        for n in ("ppp0", "ppp1", "tun0"):
            if Path(f"/sys/class/net/{n}").exists():
                self._ppp_iface = n
                return

    def _traffic_loop(self):
        """Poll TX/RX from sysfs every 2s while connected."""
        while self.connected and not self._stop.is_set():
            iface = self._ppp_iface
            if iface:
                try:
                    tx = int(Path(f"/sys/class/net/{iface}/statistics/tx_bytes").read_text().strip())
                    rx = int(Path(f"/sys/class/net/{iface}/statistics/rx_bytes").read_text().strip())
                    self.bytes_tx = tx
                    self.bytes_rx = rx
                    if self.on_traffic_update:
                        GLib.idle_add(self.on_traffic_update, tx, rx)
                except Exception:
                    pass
            time.sleep(2)

    def disconnect(self):
        self._stop.set()
        if self.process and self.process.poll() is None:
            self._emit_log(">> Disconnecting...")
            pid = self.process.pid
            # Try sending SIGINT to the process group (openfortivpn runs as root)
            try:
                # First try sudo kill (works if NOPASSWD is set up).
                # Note: inside Flatpak, `pid` is the local flatpak-spawn pid,
                # not the host openfortivpn pid. flatpak-spawn forwards the
                # signal to its host child, so this still terminates the
                # tunnel correctly.
                subprocess.run(host_cmd(["sudo", "--non-interactive", "kill", "-INT", str(pid)]),
                               timeout=3, check=False, capture_output=True)
            except Exception:
                pass
            try:
                # Also try pkexec kill as fallback
                subprocess.run(host_cmd(["pkexec", "kill", "-INT", str(pid)]),
                               timeout=5, check=False, capture_output=True)
            except Exception:
                pass
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    self.process.kill()
                except Exception:
                    pass
        self.connected = False
        self._ppp_iface = None
        self._emit_status()

    def _emit_log(self, text: str):
        if self.on_log_line:
            GLib.idle_add(self.on_log_line, text)

    def _emit_status(self):
        if self.on_status_change:
            GLib.idle_add(self.on_status_change, self.connected)

    def _scan_cert(self, line: str):
        """Watch a single output line for an openfortivpn cert-validation
        error and the SHA-256 digest that follows. Fires on_cert_captured
        at most once per user-initiated connect attempt."""
        if self._cert_retry_done:
            return
        low = line.lower()
        if not self._cert_error_seen:
            for marker in CERT_ERROR_MARKERS:
                if marker in low:
                    self._cert_error_seen = True
                    break
        if not self._cert_error_seen:
            return
        m = CERT_DIGEST_RE.search(line)
        if not m:
            return
        digest = m.group(0).replace(":", "").lower()
        if len(digest) != 64:
            return
        self._cert_retry_done = True
        if self.on_cert_captured:
            GLib.idle_add(self.on_cert_captured, digest)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, vpn: VPNController):
        super().__init__(application=app, title=APP_NAME, default_width=440, default_height=680)
        self.set_icon_name(APP_ICON)
        self.vpn = vpn
        self.vpn.on_status_change = self._on_vpn_status
        self.vpn.on_log_line = self._on_vpn_log
        self.vpn.on_traffic_update = self._on_traffic_update
        self.vpn.on_cert_captured = self._on_cert_captured
        self.profiles = load_profiles()

        # UI state
        self._connecting = False
        self._connect_started: float | None = None
        self._tick_source: int | None = None
        self._active_host: str = ""
        self._last_sample: tuple[int, int, float] | None = None  # (tx, rx, t)
        self._tx_rate: float = 0.0
        self._rx_rate: float = 0.0

        # Auto cert-capture retry coordination.
        # _connecting_idx: which profile the most recent connect attempt
        #   targets — needed by the cert-capture callback so it can write the
        #   digest into the right profile.
        # _cert_retry_pending: set in _on_cert_captured, drained in
        #   _on_vpn_status(False) — we wait for the failed openfortivpn to
        #   exit before respawning, otherwise the second sudo/pkexec races
        #   the still-dying first one.
        self._connecting_idx: int | None = None
        self._cert_retry_pending: bool = False

        self._build_ui()

    def _build_ui(self):
        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        self._nav = Adw.NavigationView()
        self._toast_overlay.set_child(self._nav)

        # Main page
        main_page = Adw.NavigationPage(title=APP_NAME)
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_page.set_child(main_box)

        # Header
        header = Adw.HeaderBar()
        add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add Profile")
        add_btn.add_css_class("flat")
        add_btn.connect("clicked", self._on_add_profile)
        header.pack_start(add_btn)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Main Menu")
        menu_btn.add_css_class("flat")
        menu = Gio.Menu()
        menu.append("About FortiVPN Client", "app.about")
        menu.append("Quit", "app.quit")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)
        main_box.append(header)

        # Scrollable content
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        clamp = Adw.Clamp(maximum_size=560)
        scroll.set_child(clamp)
        main_box.append(scroll)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                        margin_top=18, margin_bottom=18, margin_start=14, margin_end=14)
        clamp.set_child(inner)

        # ---- Hero status card ----
        self._hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                             halign=Gtk.Align.FILL, valign=Gtk.Align.START)
        self._hero.add_css_class("hero-card")
        self._hero.add_css_class("disconnected")

        self._hero_icon = Gtk.Image(icon_name="network-vpn-disconnected-symbolic")
        self._hero_icon.add_css_class("hero-icon")
        self._hero_icon.set_halign(Gtk.Align.CENTER)
        self._hero.append(self._hero_icon)

        self._hero_title = Gtk.Label(label="Disconnected", halign=Gtk.Align.CENTER)
        self._hero_title.add_css_class("hero-title")
        self._hero.append(self._hero_title)

        self._hero_subtitle = Gtk.Label(label="No active connection",
                                        halign=Gtk.Align.CENTER, wrap=True,
                                        justify=Gtk.Justification.CENTER)
        self._hero_subtitle.add_css_class("hero-subtitle")
        self._hero.append(self._hero_subtitle)

        self._disconnect_btn = Gtk.Button(label="Disconnect")
        self._disconnect_btn.add_css_class("destructive-action")
        self._disconnect_btn.add_css_class("pill")
        self._disconnect_btn.add_css_class("disconnect-pill")
        self._disconnect_btn.set_halign(Gtk.Align.CENTER)
        self._disconnect_btn.set_visible(False)
        self._disconnect_btn.connect("clicked", lambda *_: self.vpn.disconnect())
        self._hero.append(self._disconnect_btn)

        inner.append(self._hero)

        # ---- Profiles ----
        self._profiles_stack = Gtk.Stack()
        self._profiles_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._profiles_stack.set_transition_duration(150)

        # Empty state
        empty = Adw.StatusPage(
            icon_name="network-vpn-symbolic",
            title="No VPN profiles",
            description="Add your first profile to get started",
        )
        empty.set_vexpand(False)
        empty_btn = Gtk.Button(label="Add Profile")
        empty_btn.add_css_class("suggested-action")
        empty_btn.add_css_class("pill")
        empty_btn.set_halign(Gtk.Align.CENTER)
        empty_btn.connect("clicked", self._on_add_profile)
        empty.set_child(empty_btn)
        self._profiles_stack.add_named(empty, "empty")

        # Populated state
        self._profiles_group = Adw.PreferencesGroup(
            title="Profiles",
            description="Select a profile to connect",
        )
        self._profile_rows: list[Adw.ActionRow] = []
        self._profiles_stack.add_named(self._profiles_group, "list")

        inner.append(self._profiles_stack)

        # ---- Traffic ----
        self._traffic_group = Adw.PreferencesGroup(title="Traffic")

        self._tx_row = Adw.ActionRow(title="0 B", subtitle="0 B/s")
        tx_icon = Gtk.Image(icon_name="go-up-symbolic")
        tx_icon.add_css_class("dim-label")
        self._tx_row.add_prefix(tx_icon)
        self._traffic_group.add(self._tx_row)

        self._rx_row = Adw.ActionRow(title="0 B", subtitle="0 B/s")
        rx_icon = Gtk.Image(icon_name="go-down-symbolic")
        rx_icon.add_css_class("dim-label")
        self._rx_row.add_prefix(rx_icon)
        self._traffic_group.add(self._rx_row)

        self._traffic_group.set_visible(False)
        inner.append(self._traffic_group)

        # ---- Log (collapsed by default) ----
        log_group = Adw.PreferencesGroup()
        self._log_expander = Adw.ExpanderRow(
            title="Show log",
            subtitle="Connection diagnostics from openfortivpn",
        )
        log_group.add(self._log_expander)
        inner.append(log_group)

        log_scroll = Gtk.ScrolledWindow(min_content_height=180, max_content_height=320)
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroll.set_margin_top(2)
        log_scroll.set_margin_bottom(8)
        log_scroll.set_margin_start(12)
        log_scroll.set_margin_end(12)
        tv = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                          monospace=True, top_margin=8, bottom_margin=8,
                          left_margin=8, right_margin=8)
        tv.add_css_class("card")
        log_scroll.set_child(tv)

        log_holder = Gtk.ListBoxRow(activatable=False, selectable=False)
        log_holder.set_child(log_scroll)
        self._log_expander.add_row(log_holder)

        self._log_buf = tv.get_buffer()
        self._log_tv = tv

        self._nav.push(main_page)
        self._refresh_profiles()

    # ---- Profiles list ----
    def _refresh_profiles(self):
        # Remove previously tracked rows
        for row in self._profile_rows:
            self._profiles_group.remove(row)
        self._profile_rows.clear()

        if not self.profiles:
            self._profiles_stack.set_visible_child_name("empty")
            return

        self._profiles_stack.set_visible_child_name("list")

        for i, p in enumerate(self.profiles):
            saml = p.get("saml", True)
            sub = f"{p.get('host', '')}:{p.get('port', '443')}"
            if saml:
                sub += "  \u2022  SAML"

            row = Adw.ActionRow(title=p.get("name", "Unnamed"), subtitle=sub, activatable=True)
            row.add_prefix(Gtk.Image(icon_name="network-vpn-symbolic"))
            row.connect("activated", lambda _r, idx=i: self._on_connect(idx))

            # Per-row action menu (Edit / Delete) collapsed under view-more
            popover = Gtk.Popover()
            pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            pop_box.set_margin_top(4)
            pop_box.set_margin_bottom(4)
            pop_box.set_margin_start(4)
            pop_box.set_margin_end(4)
            popover.set_child(pop_box)

            edit_btn = Gtk.Button(label="Edit")
            edit_btn.add_css_class("flat")
            edit_btn.connect("clicked", lambda _b, idx=i, pop=popover:
                             (pop.popdown(), self._open_editor(idx)))
            pop_box.append(edit_btn)

            del_btn = Gtk.Button(label="Delete")
            del_btn.add_css_class("flat")
            del_btn.add_css_class("destructive-action")
            del_btn.connect("clicked", lambda _b, idx=i, pop=popover:
                            (pop.popdown(), self._on_delete(idx)))
            pop_box.append(del_btn)

            mb = Gtk.MenuButton(
                icon_name="view-more-symbolic",
                valign=Gtk.Align.CENTER,
                tooltip_text="More actions",
            )
            mb.add_css_class("flat")
            mb.set_popover(popover)
            row.add_suffix(mb)

            self._profiles_group.add(row)
            self._profile_rows.append(row)

    # ---- CRUD ----
    def _on_add_profile(self, *_):
        self._open_editor(None)

    def _on_delete(self, idx):
        d = Adw.AlertDialog(heading="Delete Profile?",
                            body=f"Delete '{self.profiles[idx].get('name', '')}'?")
        d.add_response("cancel", "Cancel")
        d.add_response("delete", "Delete")
        d.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda dlg, r: self._do_delete(idx) if r == "delete" else None)
        d.present(self)

    def _do_delete(self, idx):
        self.profiles.pop(idx)
        save_profiles(self.profiles)
        self._refresh_profiles()

    def _open_editor(self, idx: int | None):
        is_new = idx is None
        p = {} if is_new else dict(self.profiles[idx])

        page = Adw.NavigationPage(title="New Profile" if is_new else "Edit Profile")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.set_child(box)

        hdr = Adw.HeaderBar()
        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        hdr.pack_end(save_btn)
        box.append(hdr)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        clamp = Adw.Clamp(maximum_size=500)
        scroll.set_child(clamp)
        box.append(scroll)

        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        clamp.set_child(form)

        # Connection
        g1 = Adw.PreferencesGroup(title="Connection")
        name_r = Adw.EntryRow(title="Profile Name")
        name_r.set_text(p.get("name", ""))
        g1.add(name_r)
        host_r = Adw.EntryRow(title="Host / Gateway")
        host_r.set_text(p.get("host", ""))
        g1.add(host_r)
        port_r = Adw.EntryRow(title="Port")
        port_r.set_text(p.get("port", "443"))
        g1.add(port_r)
        form.append(g1)

        # Authentication
        g2 = Adw.PreferencesGroup(title="Authentication")
        saml_r = Adw.SwitchRow(title="SAML / SSO",
                               subtitle="Uses --saml-login and opens your browser automatically")
        saml_r.set_active(p.get("saml", True))
        g2.add(saml_r)
        realm_r = Adw.EntryRow(title="Realm (optional)")
        realm_r.set_text(p.get("realm", ""))
        g2.add(realm_r)
        cert_r = Adw.EntryRow(title="Trusted Cert Hash")
        cert_r.set_text(p.get("trusted_cert", ""))
        g2.add(cert_r)
        # Hint row explaining auto-capture
        cert_hint = Adw.ActionRow(
            title="Captured automatically on first connection",
            subtitle="Usually empty — openfortivpn will fill this for you",
            sensitive=False,
        )
        cert_hint.add_css_class("dim-label")
        info_icon = Gtk.Image(icon_name="dialog-information-symbolic")
        info_icon.add_css_class("dim-label")
        cert_hint.add_prefix(info_icon)
        g2.add(cert_hint)
        form.append(g2)

        # Advanced
        g3 = Adw.PreferencesGroup(title="Advanced")
        extra_r = Adw.EntryRow(title="Extra openfortivpn args (space-separated)")
        extra_r.set_text(p.get("extra_args", ""))
        g3.add(extra_r)
        form.append(g3)

        def _save(*_):
            data = {
                "name": name_r.get_text().strip() or "Unnamed",
                "host": host_r.get_text().strip(),
                "port": port_r.get_text().strip() or "443",
                "saml": saml_r.get_active(),
                "realm": realm_r.get_text().strip(),
                "trusted_cert": cert_r.get_text().strip(),
                "extra_args": extra_r.get_text().strip(),
            }
            if not data["host"]:
                self._toast("Host is required")
                return
            if is_new:
                self.profiles.append(data)
            else:
                self.profiles[idx] = data
            save_profiles(self.profiles)
            self._refresh_profiles()
            self._nav.pop()

        save_btn.connect("clicked", _save)
        self._nav.push(page)

    # ---- Connect ----
    def _on_connect(self, idx, _auto: bool = False):
        if self.vpn.connected:
            self.vpn.disconnect()
            return

        p = self.profiles[idx]
        extra = p.get("extra_args", "").split() if p.get("extra_args") else []

        self._active_host = f"{p.get('host', '')}:{p.get('port', '443')}"
        self._connecting = True
        self._connecting_idx = idx
        self._set_hero_state("connecting")

        self.vpn.connect(
            host=p["host"],
            port=p.get("port", "443"),
            saml=p.get("saml", True),
            realm=p.get("realm", ""),
            trusted_cert=p.get("trusted_cert", ""),
            extra_args=extra,
            _is_retry=_auto,
        )
        if not _auto:
            self._toast("Connecting\u2026")

    # ---- Hero card state ----
    def _set_hero_state(self, state: str):
        for cls in ("connected", "disconnected", "connecting"):
            self._hero.remove_css_class(cls)
        self._hero.add_css_class(state)

        if state == "connected":
            self._hero_icon.set_from_icon_name("network-vpn-symbolic")
            self._hero_title.set_label("Connected")
            self._hero_subtitle.set_label(self._active_host or "")
            self._disconnect_btn.set_visible(True)
            self._traffic_group.set_visible(True)
            self._start_tick()
        elif state == "connecting":
            self._hero_icon.set_from_icon_name("network-vpn-acquiring-symbolic")
            self._hero_title.set_label("Connecting\u2026")
            self._hero_subtitle.set_label(self._active_host or "Establishing tunnel")
            self._disconnect_btn.set_visible(False)
            self._traffic_group.set_visible(False)
            self._stop_tick()
        else:  # disconnected
            self._hero_icon.set_from_icon_name("network-vpn-disconnected-symbolic")
            self._hero_title.set_label("Disconnected")
            self._hero_subtitle.set_label("No active connection")
            self._disconnect_btn.set_visible(False)
            self._traffic_group.set_visible(False)
            self._stop_tick()
            self._reset_traffic_view()

    def _start_tick(self):
        self._connect_started = time.monotonic()
        if self._tick_source is None:
            self._tick_source = GLib.timeout_add_seconds(1, self._tick)
        self._tick()

    def _stop_tick(self):
        if self._tick_source is not None:
            GLib.source_remove(self._tick_source)
            self._tick_source = None
        self._connect_started = None

    def _tick(self):
        if not self.vpn.connected or self._connect_started is None:
            return False
        elapsed = int(time.monotonic() - self._connect_started)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        time_str = f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        host = self._active_host or ""
        self._hero_subtitle.set_label(f"{host}  \u2022  {time_str}" if host else time_str)
        return True

    def _reset_traffic_view(self):
        self._tx_row.set_title("0 B")
        self._tx_row.set_subtitle("0 B/s")
        self._rx_row.set_title("0 B")
        self._rx_row.set_subtitle("0 B/s")
        self._last_sample = None
        self._tx_rate = 0.0
        self._rx_rate = 0.0

    # ---- Callbacks ----
    def _on_vpn_status(self, connected: bool):
        self._connecting = False
        if connected:
            self._cert_retry_pending = False
            self._set_hero_state("connected")
            self._toast("Connected")
            return
        if self._cert_retry_pending:
            # The failed openfortivpn just exited. Wait for the OS to fully
            # reap it, then respawn with the freshly-captured trusted_cert.
            self._set_hero_state("connecting")
            GLib.timeout_add(150, self._retry_after_exit)
            return
        self._set_hero_state("disconnected")

    def _on_cert_captured(self, digest: str):
        """Controller callback: openfortivpn refused the gateway cert and we
        scraped the digest out of its log. Persist it into the profile and
        queue a one-shot reconnect."""
        idx = self._connecting_idx
        if idx is None or not (0 <= idx < len(self.profiles)):
            return
        # Persist BEFORE the retry: a crash between save and respawn must
        # still leave the profile fixed for next time.
        self.profiles[idx]["trusted_cert"] = digest
        save_profiles(self.profiles)
        self._refresh_profiles()
        self._toast("Trusted certificate saved — reconnecting…")
        self._cert_retry_pending = True
        return False  # safe whether called via idle_add or directly

    def _retry_after_exit(self):
        proc = self.vpn.process
        if proc is not None and proc.poll() is None:
            return True  # still alive — keep polling
        self._cert_retry_pending = False
        idx = self._connecting_idx
        if idx is not None and 0 <= idx < len(self.profiles):
            self._on_connect(idx, _auto=True)
        return False

    def _on_vpn_log(self, line: str):
        end = self._log_buf.get_end_iter()
        self._log_buf.insert(end, line + "\n")
        mark = self._log_buf.create_mark(None, self._log_buf.get_end_iter(), False)
        self._log_tv.scroll_to_mark(mark, 0.0, False, 0.0, 1.0)

    def _on_traffic_update(self, tx: int, rx: int):
        now = time.monotonic()
        if self._last_sample is not None:
            ptx, prx, pt = self._last_sample
            dt = now - pt
            if dt > 0:
                self._tx_rate = max(0.0, (tx - ptx) / dt)
                self._rx_rate = max(0.0, (rx - prx) / dt)
        self._last_sample = (tx, rx, now)

        self._tx_row.set_title(fmt_bytes(tx))
        self._tx_row.set_subtitle(fmt_rate(self._tx_rate))
        self._rx_row.set_title(fmt_bytes(rx))
        self._rx_row.set_subtitle(fmt_rate(self._rx_rate))

    def _toast(self, msg: str):
        self._toast_overlay.add_toast(Adw.Toast(title=msg, timeout=3))


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class FortiVPNApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.vpn = VPNController()
        self.win: MainWindow | None = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        for name, cb in [("about", self._on_about), ("quit", self._on_quit)]:
            a = Gio.SimpleAction(name=name)
            a.connect("activate", cb)
            self.add_action(a)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_activate(self):
        if not self.win:
            self._install_css()
            self.win = MainWindow(self, self.vpn)
        self.win.present()

    def _install_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _on_about(self, *_):
        Adw.AboutDialog(
            application_name=APP_NAME, application_icon=APP_ICON,
            version=APP_VERSION, developer_name="FortiVPN Client Contributors",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/fortivpn-client/fortivpn-client",
            issue_url="https://github.com/fortivpn-client/fortivpn-client/issues",
            comments="Native GNOME client for openfortivpn with SAML support.\n\n"
                     "SAML uses openfortivpn's --saml-login flag which starts a\n"
                     "local server on port 8020 and opens your default browser.",
        ).present(self.win)

    def _on_quit(self, *_):
        if self.vpn.connected:
            self.vpn.disconnect()
        self.quit()


# ---------------------------------------------------------------------------
# Tray icon (best-effort)
# ---------------------------------------------------------------------------

def try_setup_tray(app: FortiVPNApp):
    try:
        gi.require_version('AyatanaAppIndicator3', '0.1')
        from gi.repository import AyatanaAppIndicator3 as AI
    except (ValueError, ImportError):
        try:
            gi.require_version('AppIndicator3', '0.1')
            from gi.repository import AppIndicator3 as AI
        except (ValueError, ImportError):
            log.info("No AppIndicator lib found - tray disabled.")
            return None

    ind = AI.Indicator.new(APP_ID, "network-vpn-disconnected-symbolic",
                           AI.IndicatorCategory.APPLICATION_STATUS)
    ind.set_status(AI.IndicatorStatus.ACTIVE)
    ind.set_title(APP_NAME)

    orig = app.vpn.on_status_change
    def _cb(connected):
        ind.set_icon_full(
            "network-vpn-symbolic" if connected else "network-vpn-disconnected-symbolic",
            "VPN Connected" if connected else "VPN Disconnected")
        if orig:
            orig(connected)
    app.vpn.on_status_change = _cb
    return ind


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = FortiVPNApp()
    try_setup_tray(app)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.quit)
    sys.exit(app.run(sys.argv))

if __name__ == "__main__":
    main()
