#!/usr/bin/env python3
"""
FortiVPN GUI — GNOME-native style VPN client
Libadwaita-inspired design: headerbar, rounded cards, blue accent
"""

import sys, os, json, subprocess, threading, time, webbrowser
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
    QDialog, QFormLayout, QDialogButtonBox, QSystemTrayIcon, QMenu,
    QFrame, QCheckBox, QSpinBox, QMessageBox, QSizePolicy, QScrollArea,
    QStackedWidget, QAbstractItemView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QRect
from PyQt6.QtGui import (
    QFont, QColor, QIcon, QPixmap, QPainter, QPen, QBrush,
    QPainterPath, QLinearGradient, QAction, QFontDatabase
)

# ── Paths ──────────────────────────────────────────────────────────────────
APP_NAME      = "FortiVPN"
CONFIG_DIR    = Path.home() / ".config" / "fortivpn-gui"
PROFILES_FILE = CONFIG_DIR / "profiles.json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

ICON_PATHS = [
    Path(__file__).parent / "vpn-icon-256.png",
    Path("/opt/fortivpn-gui/vpn-icon-256.png"),
    Path("/usr/share/pixmaps/fortivpn-gui.png"),
]
APP_ICON = next((p for p in ICON_PATHS if p.exists()), None)

# ── GNOME / Adwaita colour tokens ─────────────────────────────────────────
# Dark variant (matches GNOME dark mode)
C = {
    # Window layers
    "window_bg":        "#1e1e2e",   # base window
    "headerbar_bg":     "#252535",   # headerbar / topbar
    "sidebar_bg":       "#1a1a2a",   # left panel
    "card_bg":          "#2a2a3e",   # card / row background
    "card_bg_hover":    "#32324a",   # row hover
    "card_bg_selected": "#1c3a6e",   # selected row
    "popover_bg":       "#2e2e42",   # dialogs / popovers
    "view_bg":          "#13131f",   # text views / terminals

    # Borders
    "border":           "rgba(255,255,255,0.08)",
    "border_strong":    "rgba(255,255,255,0.15)",
    "separator":        "rgba(255,255,255,0.06)",

    # Accent — GNOME Blue
    "accent":           "#3584e4",
    "accent_hover":     "#4a95f5",
    "accent_bg":        "rgba(53,132,228,0.20)",
    "accent_bg_hover":  "rgba(53,132,228,0.30)",

    # Semantic
    "success":          "#57e389",
    "success_bg":       "rgba(87,227,137,0.15)",
    "warning":          "#f8b83c",
    "warning_bg":       "rgba(248,184,60,0.15)",
    "error":            "#ff7b7b",
    "error_bg":         "rgba(255,123,123,0.15)",
    "destructive":      "#e01b24",
    "destructive_bg":   "rgba(224,27,36,0.15)",

    # Text
    "text":             "#ffffff",
    "text_secondary":   "rgba(255,255,255,0.55)",
    "text_disabled":    "rgba(255,255,255,0.25)",
    "text_on_accent":   "#ffffff",
}

STYLESHEET = f"""
/* ── Base ── */
* {{
    font-family: 'Cantarell', 'Ubuntu', 'Noto Sans', 'DejaVu Sans', sans-serif;
    font-size: 13px;
    color: {C['text']};
    outline: none;
}}

QMainWindow, QWidget#root {{
    background: {C['window_bg']};
}}

/* ── Headerbar ── */
QWidget#headerbar {{
    background: {C['headerbar_bg']};
    border-bottom: 1px solid {C['border']};
    min-height: 47px;
    max-height: 47px;
}}

QLabel#app_title {{
    font-size: 14px;
    font-weight: bold;
    color: {C['text']};
}}

/* ── Sidebar ── */
QWidget#sidebar {{
    background: {C['sidebar_bg']};
    border-right: 1px solid {C['separator']};
}}

QLabel#sidebar_section {{
    font-size: 11px;
    font-weight: bold;
    color: {C['text_secondary']};
    padding: 16px 12px 4px 16px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}}

/* ── Profile list ── */
QListWidget {{
    background: transparent;
    border: none;
    padding: 4px 8px;
    outline: none;
}}
QListWidget::item {{
    background: transparent;
    border-radius: 8px;
    padding: 0px;
    margin: 1px 0;
    border: none;
    min-height: 56px;
}}
QListWidget::item:hover {{
    background: {C['card_bg_hover']};
}}
QListWidget::item:selected {{
    background: {C['card_bg_selected']};
}}
QListWidget::item:selected:hover {{
    background: {C['card_bg_selected']};
}}

/* ── Content area ── */
QWidget#content {{
    background: {C['window_bg']};
}}

/* ── Cards ── */
QWidget#card {{
    background: {C['card_bg']};
    border-radius: 12px;
    border: 1px solid {C['border']};
}}

/* ── Buttons ── */
QPushButton {{
    background: {C['card_bg']};
    color: {C['text']};
    border: 1px solid {C['border_strong']};
    border-radius: 6px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: 500;
    min-height: 32px;
}}
QPushButton:hover {{
    background: {C['card_bg_hover']};
    border-color: rgba(255,255,255,0.2);
}}
QPushButton:pressed {{ background: {C['window_bg']}; }}
QPushButton:disabled {{
    color: {C['text_disabled']};
    border-color: {C['border']};
    background: transparent;
}}

QPushButton#btn_suggested {{
    background: {C['accent']};
    color: {C['text_on_accent']};
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 6px;
    font-weight: bold;
    padding: 7px 20px;
    min-height: 32px;
}}
QPushButton#btn_suggested:hover {{
    background: {C['accent_hover']};
}}
QPushButton#btn_suggested:disabled {{
    background: rgba(53,132,228,0.3);
    color: rgba(255,255,255,0.4);
}}

QPushButton#btn_destructive {{
    background: {C['destructive_bg']};
    color: {C['error']};
    border: 1px solid rgba(224,27,36,0.3);
    border-radius: 6px;
    padding: 7px 16px;
    min-height: 32px;
}}
QPushButton#btn_destructive:hover {{
    background: rgba(224,27,36,0.25);
    color: #ff9090;
}}

QPushButton#btn_pill_connect {{
    background: {C['accent']};
    color: {C['text_on_accent']};
    border: none;
    border-radius: 20px;
    font-size: 14px;
    font-weight: bold;
    padding: 10px 36px;
    min-height: 40px;
    min-width: 140px;
}}
QPushButton#btn_pill_connect:hover {{ background: {C['accent_hover']}; }}
QPushButton#btn_pill_connect:disabled {{
    background: rgba(53,132,228,0.25);
    color: rgba(255,255,255,0.35);
}}

QPushButton#btn_pill_disconnect {{
    background: {C['destructive_bg']};
    color: {C['error']};
    border: 1px solid rgba(224,27,36,0.3);
    border-radius: 20px;
    font-size: 14px;
    font-weight: bold;
    padding: 10px 36px;
    min-height: 40px;
    min-width: 140px;
}}
QPushButton#btn_pill_disconnect:hover {{
    background: rgba(224,27,36,0.25);
    color: #ff9090;
    border-color: rgba(224,27,36,0.5);
}}

QPushButton#btn_flat {{
    background: transparent;
    border: none;
    color: {C['text_secondary']};
    border-radius: 6px;
    padding: 6px 10px;
}}
QPushButton#btn_flat:hover {{
    background: {C['card_bg_hover']};
    color: {C['text']};
}}

QPushButton#btn_add_profile {{
    background: transparent;
    color: {C['accent']};
    border: 1px dashed rgba(53,132,228,0.4);
    border-radius: 8px;
    padding: 10px;
    margin: 4px 8px;
    font-size: 12px;
}}
QPushButton#btn_add_profile:hover {{
    background: {C['accent_bg']};
    border-color: {C['accent']};
}}

/* ── Inputs ── */
QLineEdit, QSpinBox {{
    background: {C['view_bg']};
    color: {C['text']};
    border: 1px solid {C['border_strong']};
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 13px;
    selection-background-color: {C['accent_bg']};
    min-height: 32px;
}}
QLineEdit:focus, QSpinBox:focus {{
    border: 2px solid {C['accent']};
    padding: 7px 9px;
}}
QLineEdit::placeholder {{ color: {C['text_disabled']}; }}

/* ── Terminal / Log ── */
QTextEdit#terminal {{
    background: {C['view_bg']};
    color: rgba(255,255,255,0.80);
    border: none;
    border-radius: 12px;
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'DejaVu Sans Mono', monospace;
    font-size: 12px;
    padding: 12px;
    selection-background-color: {C['accent_bg']};
    line-height: 1.5;
}}

/* ── Status pill ── */
QLabel#status_pill_connected {{
    background: {C['success_bg']};
    color: {C['success']};
    border: 1px solid rgba(87,227,137,0.3);
    border-radius: 10px;
    padding: 3px 12px;
    font-size: 11px;
    font-weight: bold;
}}
QLabel#status_pill_connecting {{
    background: {C['warning_bg']};
    color: {C['warning']};
    border: 1px solid rgba(248,184,60,0.3);
    border-radius: 10px;
    padding: 3px 12px;
    font-size: 11px;
    font-weight: bold;
}}
QLabel#status_pill_disconnected {{
    background: {C['error_bg']};
    color: {C['error']};
    border: 1px solid rgba(255,123,123,0.3);
    border-radius: 10px;
    padding: 3px 12px;
    font-size: 11px;
    font-weight: bold;
}}

/* ── Checkbox ── */
QCheckBox {{
    color: {C['text']};
    spacing: 10px;
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border-radius: 5px;
    border: 1px solid {C['border_strong']};
    background: {C['view_bg']};
}}
QCheckBox::indicator:checked {{
    background: {C['accent']};
    border-color: {C['accent']};
}}

/* ── Scrollbar ── */
QScrollBar:vertical {{
    background: transparent; width: 7px; border: none; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255,255,255,0.2);
    border-radius: 3px; min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.35); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

/* ── Dialog ── */
QDialog {{
    background: {C['popover_bg']};
    border: 1px solid {C['border_strong']};
    border-radius: 12px;
}}
QDialogButtonBox QPushButton {{ min-width: 88px; }}
QFormLayout QLabel {{
    color: {C['text_secondary']};
    font-size: 12px;
}}

/* ── Menu ── */
QMenu {{
    background: {C['popover_bg']};
    border: 1px solid {C['border_strong']};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{ padding: 8px 20px; border-radius: 5px; color: {C['text']}; }}
QMenu::item:selected {{ background: {C['accent_bg']}; color: {C['accent']}; }}
QMenu::separator {{ height: 1px; background: {C['separator']}; margin: 4px 0; }}
QMessageBox {{ background: {C['popover_bg']}; }}

/* ── Separator ── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {C['separator']};
    border: none;
    background: {C['separator']};
    max-height: 1px;
}}
"""

# ── Data ──────────────────────────────────────────────────────────────────
def load_profiles():
    if PROFILES_FILE.exists():
        try:
            with open(PROFILES_FILE) as f: return json.load(f)
        except: pass
    return []

def save_profiles(p):
    with open(PROFILES_FILE, "w") as f: json.dump(p, f, indent=2)

# ── VPN Worker ────────────────────────────────────────────────────────────
class VpnWorker(QThread):
    log    = pyqtSignal(str, str)   # msg, level
    status = pyqtSignal(str)
    done   = pyqtSignal()

    def __init__(self, profile):
        super().__init__()
        self.profile = profile
        self._proc   = None
        self._stop   = False

    def run(self):
        h    = self.profile.get("host","")
        port = self.profile.get("port","443")
        user = self.profile.get("username","")
        cert = self.profile.get("trusted_cert","")
        realm= self.profile.get("realm","")
        saml = self.profile.get("saml", True)

        cmd = ["sudo","openfortivpn", f"{h}:{port}"]
        if saml:   cmd.append("--saml-login")
        elif user: cmd += ["--username", user]
        if cert:   cmd += [f"--trusted-cert={cert}"]
        if realm and not saml: cmd += [f"--realm={realm}"]

        self.log.emit("$ " + " ".join(cmd), "cmd")
        self.status.emit("connecting")

        if saml:
            self.log.emit("SAML flow started — opening browser for authentication…", "info")
            url = f"https://{h}:{port}/remote/saml/start?redirect=1"
            threading.Timer(2.5, lambda: webbrowser.open(url)).start()

        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
            connected = False
            for line in iter(self._proc.stdout.readline, ""):
                if self._stop: break
                line = line.rstrip()
                if not line: continue
                low = line.lower()
                lvl = "info"
                if any(k in low for k in ["error","failed","refused","denied","unrecognized"]): lvl = "error"
                elif "warn" in low: lvl = "warn"
                elif any(k in low for k in ["tunnel is up","ppp session","established","connected"]):
                    lvl = "ok"
                    if not connected:
                        connected = True
                        self.status.emit("connected")
                        self.log.emit("Tunnel established — VPN is UP", "ok")
                self.log.emit(line, lvl)

            self._proc.wait()
            rc = self._proc.returncode
            if rc != 0 and not self._stop:
                self.log.emit(f"openfortivpn exited with code {rc}", "error")
                self.status.emit("error")
            else:
                self.log.emit("VPN disconnected cleanly", "warn")
        except FileNotFoundError:
            self.log.emit("openfortivpn not found — run install.sh to install it", "error")
            self.status.emit("error")
        except Exception as e:
            self.log.emit(f"Error: {e}", "error")
            self.status.emit("error")
        finally:
            self.status.emit("disconnected")
            self.done.emit()

    def stop(self):
        self._stop = True
        if self._proc:
            try:
                self._proc.terminate()
                time.sleep(0.4)
                if self._proc.poll() is None: self._proc.kill()
            except: pass

# ── Animated status dot ────────────────────────────────────────────────────
class StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = "disconnected"
        self._phase  = 0.0
        self._timer  = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(10, 10)

    def set_status(self, s):
        self._status = s
        if s == "connecting": self._timer.start(35)
        else: self._timer.stop(); self._phase = 0.0
        self.update()

    def _tick(self):
        import math
        self._phase = (self._phase + 0.1) % (2 * math.pi)
        self.update()

    def paintEvent(self, ev):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        colors = {
            "connected":    C["success"],
            "disconnected": C["error"],
            "connecting":   C["warning"],
            "error":        C["error"],
        }
        base = QColor(colors.get(self._status, C["error"]))
        if self._status == "connecting":
            pulse = (math.sin(self._phase) + 1) / 2
            base.setAlpha(int(80 + 175 * pulse))
        glow = QColor(base); glow.setAlpha(25)
        p.setBrush(QBrush(glow)); p.drawEllipse(0,0,10,10)
        p.setBrush(QBrush(base)); p.drawEllipse(2,2,6,6)

# ── Profile row widget ─────────────────────────────────────────────────────
class ProfileRow(QWidget):
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        hl = QHBoxLayout(self)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.setSpacing(12)

        # Icon circle
        icon_lbl = QLabel("🔒")
        icon_lbl.setFixedSize(36, 36)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            f"background:{C['accent_bg']}; border-radius:18px; font-size:16px;"
        )
        hl.addWidget(icon_lbl)

        col = QVBoxLayout(); col.setSpacing(2)
        name = QLabel(profile.get("name","Unnamed"))
        name.setStyleSheet(f"font-size:13px; font-weight:600; color:{C['text']};")
        host = QLabel(f"{profile.get('host','')}:{profile.get('port','443')}")
        host.setStyleSheet(f"font-size:11px; color:{C['text_secondary']};")
        col.addWidget(name); col.addWidget(host)
        hl.addLayout(col)
        hl.addStretch()

        if profile.get("saml"):
            badge = QLabel("SSO")
            badge.setStyleSheet(
                f"background:{C['accent_bg']}; color:{C['accent']};"
                f"border-radius:8px; font-size:10px; font-weight:bold;"
                f"padding:2px 8px;"
            )
            hl.addWidget(badge)

# ── Profile dialog ─────────────────────────────────────────────────────────
class ProfileDialog(QDialog):
    def __init__(self, parent=None, profile=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Profile" if profile else "New Profile")
        self.setMinimumWidth(460)
        self.setModal(True)
        self.profile = profile or {}
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setSpacing(16); vl.setContentsMargins(24, 24, 24, 20)

        title = QLabel("Edit Profile" if self.profile else "New VPN Profile")
        title.setStyleSheet(f"font-size:17px; font-weight:bold; color:{C['text']}; padding-bottom:4px;")
        vl.addWidget(title)

        form = QFormLayout(); form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def inp(ph="", val=""):
            w = QLineEdit(); w.setPlaceholderText(ph)
            if val: w.setText(val)
            return w

        self.f_name  = inp("My Company VPN",             self.profile.get("name",""))
        self.f_host  = inp("vpn.company.com",             self.profile.get("host",""))
        self.f_port  = QSpinBox()
        self.f_port.setRange(1, 65535)
        self.f_port.setValue(int(self.profile.get("port", 443)))
        self.f_user  = inp("username (optional for SAML)", self.profile.get("username",""))
        self.f_realm = inp("sso  (leave blank if none)",   self.profile.get("realm",""))
        self.f_cert  = inp("sha256 digest (optional)",     self.profile.get("trusted_cert",""))
        self.f_saml  = QCheckBox("Use SAML / SSO authentication")
        self.f_saml.setChecked(self.profile.get("saml", True))

        form.addRow("Profile Name",  self.f_name)
        form.addRow("Host",          self.f_host)
        form.addRow("Port",          self.f_port)
        form.addRow("Username",      self.f_user)
        form.addRow("Realm",         self.f_realm)
        form.addRow("Trusted Cert",  self.f_cert)
        form.addRow("",              self.f_saml)
        vl.addLayout(form)

        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"background:{C['separator']}; border:none; max-height:1px;")
        vl.addWidget(div)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        vl.addWidget(btns)

    def get_profile(self):
        return {
            "name":         self.f_name.text().strip() or "Unnamed",
            "host":         self.f_host.text().strip(),
            "port":         str(self.f_port.value()),
            "username":     self.f_user.text().strip(),
            "realm":        self.f_realm.text().strip(),
            "trusted_cert": self.f_cert.text().strip(),
            "saml":         self.f_saml.isChecked(),
        }

# ── Main Window ────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.profiles    = load_profiles()
        self.current_idx = None
        self.worker      = None

        self.setWindowTitle("FortiVPN")
        self.setMinimumSize(820, 560)
        self.resize(960, 620)
        if APP_ICON:
            self.setWindowIcon(QIcon(str(APP_ICON)))

        self._build_ui()
        self._build_tray()
        self._refresh_list()
        if self.profiles:
            self.profile_list.setCurrentRow(0)

    # ── Layout ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget(); root.setObjectName("root")
        self.setCentralWidget(root)
        vl_root = QVBoxLayout(root)
        vl_root.setContentsMargins(0,0,0,0); vl_root.setSpacing(0)

        vl_root.addWidget(self._headerbar())

        body = QWidget()
        body_hl = QHBoxLayout(body)
        body_hl.setContentsMargins(0,0,0,0); body_hl.setSpacing(0)
        body_hl.addWidget(self._sidebar())
        body_hl.addWidget(self._content(), 1)
        vl_root.addWidget(body, 1)

    def _headerbar(self):
        hb = QWidget(); hb.setObjectName("headerbar")
        hl = QHBoxLayout(hb); hl.setContentsMargins(16,0,16,0); hl.setSpacing(12)

        # Window controls (GNOME-style: close left)
        for color, fn in [("#ed6a5e", self.close), ("#f4bf4f", self.showMinimized), ("#61c554", self.showMaximized)]:
            btn = QPushButton()
            btn.setFixedSize(13, 13)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color}; border-radius: 6px; border: none;
                }}
                QPushButton:hover {{ background: white; }}
            """)
            btn.clicked.connect(fn)
            hl.addWidget(btn)

        hl.addStretch()

        title = QLabel("FortiVPN"); title.setObjectName("app_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(title)

        hl.addStretch()

        # Status pill in headerbar
        self.status_dot  = StatusDot()
        self.status_pill = QLabel("Disconnected")
        self.status_pill.setObjectName("status_pill_disconnected")
        st_row = QHBoxLayout(); st_row.setSpacing(6)
        st_row.addWidget(self.status_dot)
        st_row.addWidget(self.status_pill)
        hl.addLayout(st_row)

        return hb

    def _sidebar(self):
        sb = QWidget(); sb.setObjectName("sidebar"); sb.setFixedWidth(220)
        vl = QVBoxLayout(sb); vl.setContentsMargins(0,0,0,0); vl.setSpacing(0)

        lbl = QLabel("Profiles"); lbl.setObjectName("sidebar_section")
        vl.addWidget(lbl)

        self.profile_list = QListWidget()
        self.profile_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.profile_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.profile_list.currentRowChanged.connect(self._on_select)
        vl.addWidget(self.profile_list)

        add_btn = QPushButton("+ Add Profile"); add_btn.setObjectName("btn_add_profile")
        add_btn.clicked.connect(self._add_profile)
        vl.addWidget(add_btn)

        vl.addStretch()

        ver = QLabel("openfortivpn ≥ 1.23")
        ver.setStyleSheet(f"color:{C['text_disabled']}; font-size:10px; padding:10px 16px;")
        vl.addWidget(ver)

        return sb

    def _content(self):
        cw = QWidget(); cw.setObjectName("content")
        vl = QVBoxLayout(cw); vl.setContentsMargins(24,24,24,24); vl.setSpacing(16)

        # ── Profile header card ──
        self.header_card = QWidget(); self.header_card.setObjectName("card")
        hc_hl = QHBoxLayout(self.header_card)
        hc_hl.setContentsMargins(20,16,20,16); hc_hl.setSpacing(16)

        info_col = QVBoxLayout(); info_col.setSpacing(4)
        self.lbl_name = QLabel("Select a profile")
        self.lbl_name.setStyleSheet(f"font-size:18px; font-weight:bold; color:{C['text']};")
        self.lbl_host = QLabel("")
        self.lbl_host.setStyleSheet(f"font-size:12px; color:{C['text_secondary']};")
        info_col.addWidget(self.lbl_name); info_col.addWidget(self.lbl_host)
        hc_hl.addLayout(info_col)
        hc_hl.addStretch()

        btn_col = QHBoxLayout(); btn_col.setSpacing(8)
        self.btn_edit   = QPushButton("Edit");   self.btn_edit.setObjectName("btn_flat")
        self.btn_delete = QPushButton("Delete"); self.btn_delete.setObjectName("btn_destructive")
        self.btn_edit.clicked.connect(self._edit_profile)
        self.btn_delete.clicked.connect(self._delete_profile)
        btn_col.addWidget(self.btn_edit); btn_col.addWidget(self.btn_delete)
        hc_hl.addLayout(btn_col)
        vl.addWidget(self.header_card)

        # ── Connect button row ──
        btn_row = QHBoxLayout(); btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_connect    = QPushButton("Connect");    self.btn_connect.setObjectName("btn_pill_connect")
        self.btn_disconnect = QPushButton("Disconnect"); self.btn_disconnect.setObjectName("btn_pill_disconnect")
        self.btn_connect.clicked.connect(self._connect)
        self.btn_disconnect.clicked.connect(self._disconnect)
        self.btn_disconnect.setVisible(False)
        btn_row.addWidget(self.btn_connect)
        btn_row.addWidget(self.btn_disconnect)
        vl.addLayout(btn_row)

        # ── Log card ──
        log_card = QWidget(); log_card.setObjectName("card")
        lc_vl = QVBoxLayout(log_card); lc_vl.setContentsMargins(0,0,0,0); lc_vl.setSpacing(0)

        # Log header
        log_hdr = QWidget()
        log_hdr.setStyleSheet(
            f"background:transparent; border-bottom:1px solid {C['separator']};"
        )
        lh_hl = QHBoxLayout(log_hdr); lh_hl.setContentsMargins(16,10,8,10)
        lh_lbl = QLabel("Log")
        lh_lbl.setStyleSheet(f"font-size:13px; font-weight:600; color:{C['text']};")
        lh_hl.addWidget(lh_lbl); lh_hl.addStretch()
        clear_btn = QPushButton("Clear"); clear_btn.setObjectName("btn_flat")
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self._clear_log)
        lh_hl.addWidget(clear_btn)
        lc_vl.addWidget(log_hdr)

        self.terminal = QTextEdit(); self.terminal.setObjectName("terminal")
        self.terminal.setReadOnly(True)
        lc_vl.addWidget(self.terminal)

        vl.addWidget(log_card, 1)
        self._log_welcome()
        return cw

    # ── Tray ──────────────────────────────────────────────────────────────
    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable(): return

        def _icon(color):
            pix = QPixmap(22,22); pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing)
            if APP_ICON:
                src = QPixmap(str(APP_ICON)).scaled(22,22,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                p.drawPixmap(0,0,src)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(C["window_bg"]))); p.drawEllipse(13,13,8,8)
            p.setBrush(QBrush(QColor(color)));           p.drawEllipse(14,14,6,6)
            p.end(); return QIcon(pix)

        self.tray = QSystemTrayIcon(self)
        self._tray_off = _icon(C["error"]); self._tray_on = _icon(C["success"])
        self.tray.setIcon(self._tray_off); self.tray.setToolTip("FortiVPN")

        menu = QMenu()
        for label, fn in [
            ("Show FortiVPN", self.show_and_raise), (None,None),
            ("Connect",    self._connect),
            ("Disconnect", self._disconnect),
            (None,None),
            ("Quit", self._quit)
        ]:
            if label is None: menu.addSeparator()
            else:
                a = QAction(label, self); a.triggered.connect(fn); menu.addAction(a)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.show_and_raise()
            if r == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        self.tray.show()

    # ── Profile management ─────────────────────────────────────────────────
    def _refresh_list(self):
        self.profile_list.clear()
        for p in self.profiles:
            item = QListWidgetItem(); item.setSizeHint(QSize(0, 60))
            self.profile_list.addItem(item)
            self.profile_list.setItemWidget(item, ProfileRow(p))

    def _on_select(self, idx):
        self.current_idx = idx
        if 0 <= idx < len(self.profiles):
            p = self.profiles[idx]
            self.lbl_name.setText(p.get("name","Unnamed"))
            badge = "  ·  SSO" if p.get("saml") else ""
            self.lbl_host.setText(f"{p.get('host','')} : {p.get('port','443')}{badge}")
        self._update_buttons()

    def _add_profile(self):
        d = ProfileDialog(self)
        if d.exec():
            self.profiles.append(d.get_profile()); save_profiles(self.profiles)
            self._refresh_list(); self.profile_list.setCurrentRow(len(self.profiles)-1)

    def _edit_profile(self):
        idx = self.current_idx
        if idx is None or idx >= len(self.profiles): return
        d = ProfileDialog(self, self.profiles[idx])
        if d.exec():
            self.profiles[idx] = d.get_profile(); save_profiles(self.profiles)
            self._refresh_list(); self.profile_list.setCurrentRow(idx); self._on_select(idx)

    def _delete_profile(self):
        idx = self.current_idx
        if idx is None or idx >= len(self.profiles): return
        name = self.profiles[idx].get("name","this profile")
        mb = QMessageBox(self); mb.setWindowTitle("Delete Profile")
        mb.setText(f"Delete <b>{name}</b>?\nThis cannot be undone.")
        mb.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        mb.button(QMessageBox.StandardButton.Yes).setObjectName("btn_destructive")
        if mb.exec() == QMessageBox.StandardButton.Yes:
            self.profiles.pop(idx); save_profiles(self.profiles)
            self._refresh_list()
            if self.profiles: self.profile_list.setCurrentRow(max(0,idx-1))
            else: self.lbl_name.setText("Select a profile"); self.lbl_host.setText("")

    # ── VPN ────────────────────────────────────────────────────────────────
    def _connect(self):
        idx = self.current_idx
        if idx is None or idx >= len(self.profiles):
            self._emit("No profile selected","warn"); return
        if self.worker and self.worker.isRunning(): return
        p = self.profiles[idx]
        self._divider(f"Connecting to {p.get('name','?')}")
        self._set_status("connecting")
        self.worker = VpnWorker(p)
        self.worker.log.connect(self._emit)
        self.worker.status.connect(self._set_status)
        self.worker.done.connect(lambda: self._set_status("disconnected"))
        self.worker.start()

    def _disconnect(self):
        if self.worker and self.worker.isRunning():
            self._divider("Disconnecting…"); self.worker.stop()

    def _set_status(self, s):
        self.status_dot.set_status(s)

        labels = {
            "connected":    ("Connected",    "status_pill_connected"),
            "disconnected": ("Disconnected", "status_pill_disconnected"),
            "connecting":   ("Connecting…",  "status_pill_connecting"),
            "error":        ("Error",        "status_pill_disconnected"),
        }
        text, obj = labels.get(s, ("Disconnected","status_pill_disconnected"))
        self.status_pill.setText(text)
        self.status_pill.setObjectName(obj)
        # Force style refresh
        self.status_pill.style().unpolish(self.status_pill)
        self.status_pill.style().polish(self.status_pill)

        if hasattr(self, "tray"):
            self.tray.setIcon(self._tray_on if s == "connected" else self._tray_off)
            self.tray.setToolTip(f"FortiVPN — {text}")

        self._update_buttons()

    def _update_buttons(self):
        has     = self.current_idx is not None and len(self.profiles) > 0
        running = self.worker is not None and self.worker.isRunning()
        self.btn_connect.setVisible(not running); self.btn_disconnect.setVisible(running)
        self.btn_connect.setEnabled(has and not running)
        self.btn_edit.setEnabled(has and not running)
        self.btn_delete.setEnabled(has and not running)

    # ── Log ────────────────────────────────────────────────────────────────
    def _log_welcome(self):
        self.terminal.setHtml(
            f'<span style="color:rgba(255,255,255,0.25); font-family:monospace; font-size:12px;">'
            f'FortiVPN ready · select a profile and press Connect'
            f'</span>'
        )

    def _clear_log(self): self.terminal.clear(); self._log_welcome()

    def _divider(self, label):
        self._raw(f'<span style="color:rgba(255,255,255,0.2);">─── {label} ───</span>')

    def _emit(self, msg, level="info"):
        ts  = datetime.now().strftime("%H:%M:%S")
        col = {
            "ok":   C["success"],
            "error":C["error"],
            "warn": C["warning"],
            "cmd":  C["accent"],
            "info": "rgba(255,255,255,0.7)",
        }.get(level,"rgba(255,255,255,0.7)")
        pre = {"ok":"✓","error":"✗","warn":"⚠","cmd":"$","info":"·"}.get(level,"·")
        self._raw(
            f'<span style="color:rgba(255,255,255,0.3); font-size:11px;">{ts}</span> '
            f'<span style="color:{col}; font-size:12px;">{pre} {self._esc(msg)}</span>'
        )

    def _raw(self, html):
        c = self.terminal.textCursor()
        c.movePosition(c.MoveOperation.End)
        self.terminal.setTextCursor(c)
        self.terminal.insertHtml(html + "<br>")
        sb = self.terminal.verticalScrollBar(); sb.setValue(sb.maximum())

    @staticmethod
    def _esc(s):
        return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    # ── Window ─────────────────────────────────────────────────────────────
    def show_and_raise(self):
        self.show(); self.raise_(); self.activateWindow()

    def closeEvent(self, ev):
        if hasattr(self, "tray") and self.tray.isVisible():
            self.hide(); ev.ignore()
            self.tray.showMessage("FortiVPN","Running in system tray",
                QSystemTrayIcon.MessageIcon.Information, 1800)
        else:
            self._quit()

    def _quit(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop(); self.worker.wait(3000)
        QApplication.quit()


# ── Entry point ────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLESHEET)
    if APP_ICON:
        app.setWindowIcon(QIcon(str(APP_ICON)))

    for fname in ["Cantarell","Ubuntu","Noto Sans","DejaVu Sans","Sans Serif"]:
        f = QFont(fname, 13)
        if f.exactMatch() or fname == "Sans Serif":
            app.setFont(f); break

    win = MainWindow(); win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
