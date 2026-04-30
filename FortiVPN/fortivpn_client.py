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

from gi.repository import Gtk, Adw, Gio, GLib

APP_ID = "com.github.fortivpn_client"
APP_NAME = "FortiVPN Client"
APP_VERSION = "1.2.0"
CONFIG_DIR = Path(GLib.get_user_config_dir()) / "fortivpn-client"
CONFIG_FILE = CONFIG_DIR / "profiles.json"

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fortivpn")


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

    @staticmethod
    def find_binary() -> str | None:
        return shutil.which("openfortivpn")

    def connect(self, host: str, port: str, saml: bool = True,
                realm: str = "", trusted_cert: str = "",
                extra_args: list[str] | None = None):
        if self.process and self.process.poll() is None:
            self._emit_log("Already connected or connecting.")
            return

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
        cmd = ["sudo", "--non-interactive", binary] + vpn_args

        # If sudo non-interactive fails (no NOPASSWD rule), fall back to pkexec
        self._use_pkexec_fallback = False
        self._binary = binary
        self._vpn_args = vpn_args

        self._emit_log(f">> Starting: sudo {binary} {' '.join(vpn_args)}")
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
            cmd = ["pkexec", self._binary] + self._vpn_args
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
                # First try sudo kill (works if NOPASSWD is set up)
                subprocess.run(["sudo", "--non-interactive", "kill", "-INT", str(pid)],
                               timeout=3, check=False, capture_output=True)
            except Exception:
                pass
            try:
                # Also try pkexec kill as fallback
                subprocess.run(["pkexec", "kill", "-INT", str(pid)],
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


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, vpn: VPNController):
        super().__init__(application=app, title=APP_NAME, default_width=480, default_height=640)
        self.vpn = vpn
        self.vpn.on_status_change = self._on_vpn_status
        self.vpn.on_log_line = self._on_vpn_log
        self.vpn.on_traffic_update = self._on_traffic_update
        self.profiles = load_profiles()
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
        add_btn.connect("clicked", self._on_add_profile)
        header.pack_start(add_btn)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("About", "app.about")
        menu.append("Quit", "app.quit")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)
        main_box.append(header)

        # Status banner
        self._status_banner = Adw.Banner(title="Disconnected", revealed=True)
        self._status_banner.add_css_class("error")
        main_box.append(self._status_banner)

        # Scrollable content
        scroll = Gtk.ScrolledWindow(vexpand=True)
        clamp = Adw.Clamp(maximum_size=600)
        scroll.set_child(clamp)
        main_box.append(scroll)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                        margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        clamp.set_child(inner)

        # Profiles
        self._profiles_group = Adw.PreferencesGroup(title="VPN Profiles")
        self._profile_rows: list[Adw.ActionRow] = []
        inner.append(self._profiles_group)

        # Traffic (hidden until connected)
        self._traffic_group = Adw.PreferencesGroup(title="Traffic")
        self._traffic_row = Adw.ActionRow(
            title="\u2191 Sent: 0 B",
            subtitle="\u2193 Received: 0 B",
        )
        self._traffic_row.add_prefix(Gtk.Image(icon_name="network-transmit-receive-symbolic"))
        self._traffic_group.add(self._traffic_row)
        self._traffic_group.set_visible(False)
        inner.append(self._traffic_group)

        # Disconnect button (hidden until connected)
        self._disconnect_btn = Gtk.Button(label="Disconnect")
        self._disconnect_btn.add_css_class("destructive-action")
        self._disconnect_btn.add_css_class("pill")
        self._disconnect_btn.set_halign(Gtk.Align.CENTER)
        self._disconnect_btn.set_margin_top(8)
        self._disconnect_btn.set_visible(False)
        self._disconnect_btn.connect("clicked", lambda *_: self.vpn.disconnect())
        inner.append(self._disconnect_btn)

        # Connection log
        log_group = Adw.PreferencesGroup(title="Connection Log")
        inner.append(log_group)

        log_scroll = Gtk.ScrolledWindow(min_content_height=180, max_content_height=300)
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        tv = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                          monospace=True, top_margin=8, bottom_margin=8,
                          left_margin=8, right_margin=8)
        tv.add_css_class("card")
        log_scroll.set_child(tv)
        log_group.add(log_scroll)
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
            row = Adw.ActionRow(title="No profiles yet", subtitle="Click + to add one")
            row.set_sensitive(False)
            self._profiles_group.add(row)
            self._profile_rows.append(row)
            return

        for i, p in enumerate(self.profiles):
            saml = p.get("saml", True)
            sub = f"{p.get('host', '')}:{p.get('port', '443')}"
            if saml:
                sub += "  \u2022  SAML"

            row = Adw.ActionRow(title=p.get("name", "Unnamed"), subtitle=sub, activatable=True)
            row.add_prefix(Gtk.Image(icon_name="network-vpn-symbolic"))

            for icon, tip, cb in [
                ("media-playback-start-symbolic", "Connect", lambda _b, idx=i: self._on_connect(idx)),
                ("document-edit-symbolic", "Edit", lambda _b, idx=i: self._open_editor(idx)),
                ("user-trash-symbolic", "Delete", lambda _b, idx=i: self._on_delete(idx)),
            ]:
                btn = Gtk.Button(icon_name=icon, valign=Gtk.Align.CENTER, tooltip_text=tip)
                btn.add_css_class("flat")
                btn.connect("clicked", cb)
                row.add_suffix(btn)

            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
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
        cert_r = Adw.EntryRow(title="Trusted Cert Hash (optional)")
        cert_r.set_text(p.get("trusted_cert", ""))
        g2.add(cert_r)
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
    def _on_connect(self, idx):
        if self.vpn.connected:
            self.vpn.disconnect()
            return

        p = self.profiles[idx]
        extra = p.get("extra_args", "").split() if p.get("extra_args") else []

        self.vpn.connect(
            host=p["host"],
            port=p.get("port", "443"),
            saml=p.get("saml", True),
            realm=p.get("realm", ""),
            trusted_cert=p.get("trusted_cert", ""),
            extra_args=extra,
        )
        self._toast("Starting connection...")

    # ---- Callbacks ----
    def _on_vpn_status(self, connected: bool):
        if connected:
            self._status_banner.set_title("  Connected")
            self._status_banner.remove_css_class("error")
            self._status_banner.add_css_class("success")
            self._traffic_group.set_visible(True)
            self._disconnect_btn.set_visible(True)
            self._toast("VPN tunnel is up!")
        else:
            self._status_banner.set_title("  Disconnected")
            self._status_banner.remove_css_class("success")
            self._status_banner.add_css_class("error")
            self._traffic_group.set_visible(False)
            self._disconnect_btn.set_visible(False)

    def _on_vpn_log(self, line: str):
        end = self._log_buf.get_end_iter()
        self._log_buf.insert(end, line + "\n")
        mark = self._log_buf.create_mark(None, self._log_buf.get_end_iter(), False)
        self._log_tv.scroll_to_mark(mark, 0.0, False, 0.0, 1.0)

    def _on_traffic_update(self, tx: int, rx: int):
        self._traffic_row.set_title(f"\u2191  Sent: {fmt_bytes(tx)}")
        self._traffic_row.set_subtitle(f"\u2193  Received: {fmt_bytes(rx)}")

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
            self.win = MainWindow(self, self.vpn)
        self.win.present()

    def _on_about(self, *_):
        Adw.AboutDialog(
            application_name=APP_NAME, application_icon="network-vpn",
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
