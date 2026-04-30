#!/usr/bin/env python3
"""
FortiVPN GUI - A modern GTK-style VPN client for openfortivpn
Supports SAML login, profile management, live logs, system tray
"""

import sys
import os
import json
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
    QDialog, QFormLayout, QDialogButtonBox, QSystemTrayIcon, QMenu,
    QSplitter, QFrame, QStackedWidget, QCheckBox, QSpinBox, QMessageBox,
    QGraphicsDropShadowEffect, QScrollArea
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve,
    QSize, QPoint, QRect, pyqtProperty, QObject
)
from PyQt6.QtGui import (
    QFont, QColor, QPalette, QIcon, QPixmap, QPainter, QPen, QBrush,
    QLinearGradient, QFontDatabase, QCursor, QAction, QKeySequence
)


# ─── Constants ────────────────────────────────────────────────────────────────

APP_NAME = "FortiVPN"
CONFIG_DIR = Path.home() / ".config" / "fortivpn-gui"
PROFILES_FILE = CONFIG_DIR / "profiles.json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Icon search paths (installer places it in /opt/fortivpn-gui/)
ICON_PATHS = [
    Path(__file__).parent / "vpn-icon-256.png",
    Path("/opt/fortivpn-gui/vpn-icon-256.png"),
    Path("/usr/share/pixmaps/fortivpn-gui.png"),
]
APP_ICON = next((p for p in ICON_PATHS if p.exists()), None)

COLORS = {
    "bg":           "#0d0f14",
    "bg_panel":     "#111318",
    "bg_card":      "#161a22",
    "bg_hover":     "#1c2030",
    "bg_input":     "#0a0c10",
    "border":       "#1e2535",
    "border_focus": "#2d6a4f",
    "accent":       "#00ff88",
    "accent_dim":   "#00cc6a",
    "accent_dark":  "#003322",
    "accent_glow":  "rgba(0,255,136,0.15)",
    "red":          "#ff4444",
    "red_dim":      "#cc2222",
    "yellow":       "#ffaa00",
    "blue":         "#4488ff",
    "text":         "#e0e6f0",
    "text_dim":     "#6b7a96",
    "text_muted":   "#3a4455",
    "connected":    "#00ff88",
    "disconnected": "#ff4444",
    "connecting":   "#ffaa00",
}

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['text']};
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 13px;
}}

/* Sidebar */
#sidebar {{
    background-color: {COLORS['bg_panel']};
    border-right: 1px solid {COLORS['border']};
    min-width: 220px;
    max-width: 220px;
}}

#logo_label {{
    color: {COLORS['accent']};
    font-size: 18px;
    font-weight: bold;
    letter-spacing: 3px;
    padding: 24px 20px 8px 20px;
}}

#logo_sub {{
    color: {COLORS['text_muted']};
    font-size: 10px;
    letter-spacing: 2px;
    padding: 0px 20px 20px 20px;
}}

/* Profile list */
QListWidget {{
    background-color: transparent;
    border: none;
    outline: none;
    padding: 4px 8px;
}}

QListWidget::item {{
    background-color: transparent;
    color: {COLORS['text_dim']};
    border-radius: 6px;
    padding: 10px 12px;
    margin: 2px 0;
    border: 1px solid transparent;
}}

QListWidget::item:hover {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
}}

QListWidget::item:selected {{
    background-color: {COLORS['accent_dark']};
    color: {COLORS['accent']};
    border: 1px solid {COLORS['border_focus']};
}}

/* Buttons */
QPushButton {{
    background-color: {COLORS['bg_card']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 8px 16px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 12px;
    letter-spacing: 1px;
}}

QPushButton:hover {{
    background-color: {COLORS['bg_hover']};
    border-color: {COLORS['text_muted']};
}}

QPushButton:pressed {{
    background-color: {COLORS['bg']};
}}

#btn_connect {{
    background-color: {COLORS['accent_dark']};
    color: {COLORS['accent']};
    border: 1px solid {COLORS['border_focus']};
    font-weight: bold;
    font-size: 13px;
    padding: 12px 24px;
    letter-spacing: 2px;
    border-radius: 8px;
}}

#btn_connect:hover {{
    background-color: {COLORS['accent']};
    color: {COLORS['bg']};
    border-color: {COLORS['accent']};
}}

#btn_connect:disabled {{
    background-color: {COLORS['bg_card']};
    color: {COLORS['text_muted']};
    border-color: {COLORS['border']};
}}

#btn_disconnect {{
    background-color: rgba(255,68,68,0.12);
    color: {COLORS['red']};
    border: 1px solid rgba(255,68,68,0.3);
    font-weight: bold;
    font-size: 13px;
    padding: 12px 24px;
    letter-spacing: 2px;
    border-radius: 8px;
}}

#btn_disconnect:hover {{
    background-color: {COLORS['red']};
    color: {COLORS['bg']};
}}

#btn_add {{
    background-color: transparent;
    color: {COLORS['text_dim']};
    border: 1px dashed {COLORS['border']};
    border-radius: 6px;
    padding: 8px;
    margin: 4px 8px;
}}

#btn_add:hover {{
    color: {COLORS['accent']};
    border-color: {COLORS['border_focus']};
}}

#btn_danger {{
    background-color: transparent;
    color: {COLORS['red_dim']};
    border: 1px solid rgba(255,68,68,0.2);
}}

#btn_danger:hover {{
    background-color: rgba(255,68,68,0.1);
    color: {COLORS['red']};
    border-color: rgba(255,68,68,0.5);
}}

/* Inputs */
QLineEdit, QSpinBox {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 8px 12px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    selection-background-color: {COLORS['accent_dark']};
}}

QLineEdit:focus, QSpinBox:focus {{
    border-color: {COLORS['border_focus']};
    background-color: {COLORS['bg_card']};
}}

QLineEdit::placeholder {{
    color: {COLORS['text_muted']};
}}

/* Log terminal */
#log_terminal {{
    background-color: {COLORS['bg_input']};
    color: #7fba84;
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 12px;
    padding: 8px;
    selection-background-color: {COLORS['accent_dark']};
}}

/* Status indicator */
#status_dot_connected {{
    color: {COLORS['connected']};
}}
#status_dot_disconnected {{
    color: {COLORS['disconnected']};
}}
#status_dot_connecting {{
    color: {COLORS['connecting']};
}}

/* Cards / panels */
#main_panel {{
    background-color: {COLORS['bg_panel']};
    border-left: 1px solid {COLORS['border']};
}}

#card {{
    background-color: {COLORS['bg_card']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
}}

#section_label {{
    color: {COLORS['text_muted']};
    font-size: 10px;
    letter-spacing: 3px;
    font-weight: bold;
    padding: 4px 0;
}}

#profile_name_display {{
    color: {COLORS['text']};
    font-size: 20px;
    font-weight: bold;
    letter-spacing: 1px;
}}

#host_display {{
    color: {COLORS['text_dim']};
    font-size: 12px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border']};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLORS['text_muted']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

/* Checkbox */
QCheckBox {{
    color: {COLORS['text_dim']};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    background: {COLORS['bg_input']};
}}
QCheckBox::indicator:checked {{
    background: {COLORS['accent_dark']};
    border-color: {COLORS['border_focus']};
}}

/* Splitter */
QSplitter::handle {{
    background-color: {COLORS['border']};
    width: 1px;
}}

/* Context menu */
QMenu {{
    background-color: {COLORS['bg_card']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 8px 20px;
    border-radius: 4px;
    color: {COLORS['text']};
}}
QMenu::item:selected {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['accent']};
}}
QMenu::separator {{
    height: 1px;
    background: {COLORS['border']};
    margin: 4px 0;
}}

/* Dialog */
QDialog {{
    background-color: {COLORS['bg_panel']};
    border: 1px solid {COLORS['border']};
}}
QDialogButtonBox QPushButton {{
    min-width: 80px;
}}

/* Form labels */
QFormLayout QLabel {{
    color: {COLORS['text_dim']};
    font-size: 12px;
    letter-spacing: 1px;
}}

QMessageBox {{
    background-color: {COLORS['bg_panel']};
}}
"""


# ─── Data Models ──────────────────────────────────────────────────────────────

def load_profiles():
    if PROFILES_FILE.exists():
        try:
            with open(PROFILES_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_profiles(profiles):
    with open(PROFILES_FILE, "w") as f:
        json.dump(profiles, f, indent=2)


# ─── VPN Worker Thread ────────────────────────────────────────────────────────

class VpnWorker(QThread):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)   # "connecting" | "connected" | "disconnected" | "error"
    finished_signal = pyqtSignal()

    def __init__(self, profile):
        super().__init__()
        self.profile = profile
        self._process = None
        self._stop = False

    def run(self):
        host = self.profile.get("host", "")
        port = self.profile.get("port", "443")
        username = self.profile.get("username", "")
        trusted_cert = self.profile.get("trusted_cert", "")
        realm = self.profile.get("realm", "")
        use_saml = self.profile.get("saml", True)

        cmd = ["sudo", "openfortivpn", f"{host}:{port}"]

        if use_saml:
            cmd.append("--saml-login")
            self.log_signal.emit(f"[{self._ts()}] ▶ Launching SAML login flow...")
            self.log_signal.emit(f"[{self._ts()}] ℹ  Your browser will open for authentication.")
            # Open browser after a short delay
            saml_url = f"https://{host}:{port}/remote/saml/start?redirect=1"
            if realm:
                saml_url = f"https://{host}:{port}/{realm}/remote/saml/start?redirect=1"
            timer = threading.Timer(2.0, lambda: webbrowser.open(saml_url))
            timer.start()
        else:
            if username:
                cmd += ["--username", username]

        if trusted_cert:
            cmd += [f"--trusted-cert={trusted_cert}"]
        if realm and not use_saml:
            cmd += [f"--realm={realm}"]

        self.log_signal.emit(f"[{self._ts()}] $ {' '.join(cmd)}")
        self.status_signal.emit("connecting")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            connected = False
            for line in iter(self._process.stdout.readline, ""):
                if self._stop:
                    break
                line = line.rstrip()
                if not line:
                    continue

                # Colorize log lines by content
                self.log_signal.emit(f"[{self._ts()}] {line}")

                if any(kw in line.lower() for kw in ["tunnel is up", "ppp session", "connected", "established"]):
                    if not connected:
                        connected = True
                        self.status_signal.emit("connected")
                        self.log_signal.emit(f"[{self._ts()}] ✓ VPN CONNECTED")

                if any(kw in line.lower() for kw in ["error", "failed", "refused", "denied"]):
                    self.status_signal.emit("error")

            self._process.wait()
            rc = self._process.returncode

            if rc == 0 or self._stop:
                self.log_signal.emit(f"[{self._ts()}] ✗ VPN disconnected (exit {rc})")
            else:
                self.log_signal.emit(f"[{self._ts()}] ✗ openfortivpn exited with code {rc}")
                self.status_signal.emit("error")

        except FileNotFoundError:
            self.log_signal.emit(f"[{self._ts()}] ✗ ERROR: openfortivpn not found. Install with: sudo dnf install openfortivpn")
            self.status_signal.emit("error")
        except Exception as e:
            self.log_signal.emit(f"[{self._ts()}] ✗ Exception: {e}")
            self.status_signal.emit("error")
        finally:
            self.status_signal.emit("disconnected")
            self.finished_signal.emit()

    def stop(self):
        self._stop = True
        if self._process:
            try:
                self._process.terminate()
                time.sleep(0.5)
                if self._process.poll() is None:
                    self._process.kill()
            except Exception:
                pass

    def _ts(self):
        return datetime.now().strftime("%H:%M:%S")


# ─── Profile Dialog ───────────────────────────────────────────────────────────

class ProfileDialog(QDialog):
    def __init__(self, parent=None, profile=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Profile" if profile else "New VPN Profile")
        self.setMinimumWidth(460)
        self.setModal(True)
        self.profile = profile or {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(28, 28, 28, 24)

        # Title
        title = QLabel("EDIT PROFILE" if self.profile else "NEW PROFILE")
        title.setObjectName("section_label")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def make_input(placeholder="", password=False, value=""):
            w = QLineEdit()
            w.setPlaceholderText(placeholder)
            if password:
                w.setEchoMode(QLineEdit.EchoMode.Password)
            if value:
                w.setText(value)
            return w

        self.name_input = make_input("My Company VPN", value=self.profile.get("name", ""))
        self.host_input = make_input("vpn.company.com", value=self.profile.get("host", ""))
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(int(self.profile.get("port", 443)))
        self.username_input = make_input("username (optional for SAML)", value=self.profile.get("username", ""))
        self.realm_input = make_input("sso  (leave blank if not needed)", value=self.profile.get("realm", ""))
        self.cert_input = make_input("sha256 digest (optional)", value=self.profile.get("trusted_cert", ""))

        self.saml_check = QCheckBox("Use SAML / SSO authentication")
        self.saml_check.setChecked(self.profile.get("saml", True))

        form.addRow("Profile Name", self.name_input)
        form.addRow("Host", self.host_input)
        form.addRow("Port", self.port_input)
        form.addRow("Username", self.username_input)
        form.addRow("Realm", self.realm_input)
        form.addRow("Trusted Cert", self.cert_input)
        form.addRow("", self.saml_check)

        layout.addLayout(form)

        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"color: {COLORS['border']};")
        layout.addWidget(divider)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_profile(self):
        return {
            "name": self.name_input.text().strip() or "Unnamed",
            "host": self.host_input.text().strip(),
            "port": str(self.port_input.value()),
            "username": self.username_input.text().strip(),
            "realm": self.realm_input.text().strip(),
            "trusted_cert": self.cert_input.text().strip(),
            "saml": self.saml_check.isChecked(),
        }


# ─── Status Widget ────────────────────────────────────────────────────────────

class StatusWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = "disconnected"
        self._anim_step = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self.setFixedSize(14, 14)

    def set_status(self, status):
        self._status = status
        if status == "connecting":
            self._timer.start(120)
        else:
            self._timer.stop()
            self._anim_step = 0
        self.update()

    def _animate(self):
        self._anim_step = (self._anim_step + 1) % 8
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        color_map = {
            "connected":    QColor(COLORS["connected"]),
            "disconnected": QColor(COLORS["disconnected"]),
            "connecting":   QColor(COLORS["connecting"]),
            "error":        QColor(COLORS["red"]),
        }
        color = color_map.get(self._status, QColor(COLORS["disconnected"]))

        if self._status == "connecting":
            alpha = int(120 + 135 * abs((self._anim_step - 4) / 4))
            color.setAlpha(alpha)

        # Glow ring
        glow = QColor(color)
        glow.setAlpha(40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(1, 1, 12, 12)

        # Core dot
        p.setBrush(QBrush(color))
        p.drawEllipse(3, 3, 8, 8)


# ─── Main Window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.profiles = load_profiles()
        self.current_profile_idx = None
        self.vpn_worker = None
        self.vpn_status = "disconnected"

        self.setWindowTitle("FortiVPN")
        self.setMinimumSize(880, 580)
        self.resize(980, 640)
        if APP_ICON:
            self.setWindowIcon(QIcon(str(APP_ICON)))

        self._build_ui()
        self._build_tray()
        self._refresh_profile_list()
        if self.profiles:
            self.profile_list.setCurrentRow(0)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        logo = QLabel("FORTI")
        logo.setObjectName("logo_label")
        logo_sub = QLabel("VPN CLIENT")
        logo_sub.setObjectName("logo_sub")
        sidebar_layout.addWidget(logo)
        sidebar_layout.addWidget(logo_sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {COLORS['border']}; margin: 0 12px;")
        sidebar_layout.addWidget(sep)

        profiles_label = QLabel("  PROFILES")
        profiles_label.setObjectName("section_label")
        profiles_label.setContentsMargins(20, 14, 0, 4)
        sidebar_layout.addWidget(profiles_label)

        self.profile_list = QListWidget()
        self.profile_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.profile_list.currentRowChanged.connect(self._on_profile_selected)
        sidebar_layout.addWidget(self.profile_list)

        btn_add = QPushButton("＋  New Profile")
        btn_add.setObjectName("btn_add")
        btn_add.clicked.connect(self._add_profile)
        sidebar_layout.addWidget(btn_add)

        sidebar_layout.addStretch()

        # Version tag
        ver_label = QLabel("openfortivpn · gtk gui")
        ver_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 10px; padding: 12px 20px;")
        sidebar_layout.addWidget(ver_label)

        root.addWidget(sidebar)

        # ── Main Panel ──
        main_panel = QWidget()
        main_panel.setObjectName("main_panel")
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(20)

        # Top bar: profile info + status
        top_bar = QHBoxLayout()

        info_col = QVBoxLayout()
        info_col.setSpacing(4)
        self.profile_name_label = QLabel("Select a Profile")
        self.profile_name_label.setObjectName("profile_name_display")
        self.host_label = QLabel("")
        self.host_label.setObjectName("host_display")
        info_col.addWidget(self.profile_name_label)
        info_col.addWidget(self.host_label)
        top_bar.addLayout(info_col)

        top_bar.addStretch()

        # Status badge
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_dot = StatusWidget()
        self.status_label = QLabel("DISCONNECTED")
        self.status_label.setStyleSheet(f"color: {COLORS['red']}; font-size: 11px; letter-spacing: 2px; font-weight: bold;")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label)
        top_bar.addLayout(status_row)

        main_layout.addLayout(top_bar)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"color: {COLORS['border']};")
        main_layout.addWidget(div)

        # Connect / Disconnect buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_connect = QPushButton("▶  CONNECT")
        self.btn_connect.setObjectName("btn_connect")
        self.btn_connect.clicked.connect(self._connect)
        self.btn_connect.setFixedHeight(44)

        self.btn_disconnect = QPushButton("■  DISCONNECT")
        self.btn_disconnect.setObjectName("btn_disconnect")
        self.btn_disconnect.clicked.connect(self._disconnect)
        self.btn_disconnect.setFixedHeight(44)
        self.btn_disconnect.setVisible(False)

        self.btn_edit = QPushButton("✎  Edit")
        self.btn_edit.clicked.connect(self._edit_profile)
        self.btn_edit.setFixedHeight(44)

        self.btn_delete = QPushButton("✕  Delete")
        self.btn_delete.setObjectName("btn_danger")
        self.btn_delete.clicked.connect(self._delete_profile)
        self.btn_delete.setFixedHeight(44)

        btn_row.addWidget(self.btn_connect)
        btn_row.addWidget(self.btn_disconnect)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_edit)
        btn_row.addWidget(self.btn_delete)
        main_layout.addLayout(btn_row)

        # Log terminal
        log_label = QLabel("TERMINAL OUTPUT")
        log_label.setObjectName("section_label")
        main_layout.addWidget(log_label)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_terminal")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(260)
        self.log_view.setFont(QFont("JetBrains Mono", 11))
        main_layout.addWidget(self.log_view)

        # Bottom bar
        bottom_bar = QHBoxLayout()
        btn_clear = QPushButton("Clear Log")
        btn_clear.setFixedWidth(100)
        btn_clear.clicked.connect(self.log_view.clear)
        bottom_bar.addStretch()
        bottom_bar.addWidget(btn_clear)
        main_layout.addLayout(bottom_bar)

        root.addWidget(main_panel, 1)

        self._update_buttons()

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("FortiVPN")

        def _make_tray_icon(dot_color):
            """Real app icon with a small status dot overlay."""
            if APP_ICON:
                base = QPixmap(str(APP_ICON)).scaled(
                    22, 22,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            else:
                base = QPixmap(22, 22)
                base.fill(Qt.GlobalColor.transparent)
            p = QPainter(base)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            # Draw status dot in bottom-right corner
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#0d0f14")))
            p.drawEllipse(13, 13, 8, 8)
            p.setBrush(QBrush(QColor(dot_color)))
            p.drawEllipse(14, 14, 6, 6)
            p.end()
            return QIcon(base)

        self.tray_icon_disconnected = _make_tray_icon(COLORS["disconnected"])
        self.tray_icon_connected    = _make_tray_icon(COLORS["connected"])

        self.tray.setIcon(self.tray_icon_disconnected)

        menu = QMenu()
        action_show = QAction("Show Window", self)
        action_show.triggered.connect(self.show_and_raise)
        action_connect = QAction("Connect", self)
        action_connect.triggered.connect(self._connect)
        action_disconnect = QAction("Disconnect", self)
        action_disconnect.triggered.connect(self._disconnect)
        action_quit = QAction("Quit", self)
        action_quit.triggered.connect(self._quit)

        menu.addAction(action_show)
        menu.addSeparator()
        menu.addAction(action_connect)
        menu.addAction(action_disconnect)
        menu.addSeparator()
        menu.addAction(action_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_and_raise()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def show_and_raise(self):
        self.show()
        self.raise_()
        self.activateWindow()

    # ── Profile management ──

    def _refresh_profile_list(self):
        self.profile_list.clear()
        for p in self.profiles:
            item = QListWidgetItem(f"  {p.get('name', 'Unnamed')}")
            item.setSizeHint(QSize(0, 42))
            self.profile_list.addItem(item)

    def _on_profile_selected(self, idx):
        self.current_profile_idx = idx
        if 0 <= idx < len(self.profiles):
            p = self.profiles[idx]
            self.profile_name_label.setText(p.get("name", "Unnamed"))
            host = p.get("host", "")
            port = p.get("port", "443")
            saml = "· SAML" if p.get("saml") else ""
            self.host_label.setText(f"{host}:{port}  {saml}")
        self._update_buttons()

    def _add_profile(self):
        dlg = ProfileDialog(self)
        if dlg.exec():
            self.profiles.append(dlg.get_profile())
            save_profiles(self.profiles)
            self._refresh_profile_list()
            self.profile_list.setCurrentRow(len(self.profiles) - 1)

    def _edit_profile(self):
        idx = self.current_profile_idx
        if idx is None or idx >= len(self.profiles):
            return
        dlg = ProfileDialog(self, self.profiles[idx])
        if dlg.exec():
            self.profiles[idx] = dlg.get_profile()
            save_profiles(self.profiles)
            self._refresh_profile_list()
            self.profile_list.setCurrentRow(idx)
            self._on_profile_selected(idx)

    def _delete_profile(self):
        idx = self.current_profile_idx
        if idx is None or idx >= len(self.profiles):
            return
        name = self.profiles[idx].get("name", "this profile")
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Profile")
        msg.setText(f"Delete <b>{name}</b>?")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.profiles.pop(idx)
            save_profiles(self.profiles)
            self._refresh_profile_list()
            if self.profiles:
                self.profile_list.setCurrentRow(max(0, idx - 1))
            else:
                self.profile_name_label.setText("Select a Profile")
                self.host_label.setText("")

    # ── VPN control ──

    def _connect(self):
        idx = self.current_profile_idx
        if idx is None or idx >= len(self.profiles):
            self._log("⚠  No profile selected.")
            return
        if self.vpn_worker and self.vpn_worker.isRunning():
            return

        profile = self.profiles[idx]
        self._set_status("connecting")
        self._log(f"── Connecting to {profile.get('name')} ──")

        self.vpn_worker = VpnWorker(profile)
        self.vpn_worker.log_signal.connect(self._log)
        self.vpn_worker.status_signal.connect(self._set_status)
        self.vpn_worker.finished_signal.connect(self._on_vpn_finished)
        self.vpn_worker.start()

    def _disconnect(self):
        if self.vpn_worker and self.vpn_worker.isRunning():
            self._log("── Disconnecting... ──")
            self.vpn_worker.stop()

    def _on_vpn_finished(self):
        self._set_status("disconnected")

    def _set_status(self, status):
        self.vpn_status = status
        self.status_dot.set_status(status)

        labels = {
            "connected":    ("CONNECTED",    COLORS["connected"]),
            "disconnected": ("DISCONNECTED", COLORS["disconnected"]),
            "connecting":   ("CONNECTING…",  COLORS["connecting"]),
            "error":        ("ERROR",        COLORS["red"]),
        }
        text, color = labels.get(status, ("UNKNOWN", COLORS["text_dim"]))
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"color: {color}; font-size: 11px; letter-spacing: 2px; font-weight: bold;"
        )

        # Tray icon
        if hasattr(self, "tray"):
            icon = self.tray_icon_connected if status == "connected" else self.tray_icon_disconnected
            self.tray.setIcon(icon)
            self.tray.setToolTip(f"FortiVPN · {text}")

        self._update_buttons()

    def _update_buttons(self):
        has_profile = self.current_profile_idx is not None and len(self.profiles) > 0
        is_running = self.vpn_worker is not None and self.vpn_worker.isRunning()

        self.btn_connect.setVisible(not is_running)
        self.btn_disconnect.setVisible(is_running)
        self.btn_connect.setEnabled(has_profile and not is_running)
        self.btn_edit.setEnabled(has_profile and not is_running)
        self.btn_delete.setEnabled(has_profile and not is_running)

    def _log(self, text):
        cursor = self.log_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_view.setTextCursor(cursor)

        # Color coding
        if any(k in text for k in ["ERROR", "✗", "⚠", "error", "failed"]):
            color = COLORS["red"]
        elif any(k in text for k in ["✓", "CONNECTED", "connected"]):
            color = COLORS["accent"]
        elif any(k in text for k in ["──", "▶", "ℹ"]):
            color = COLORS["yellow"]
        else:
            color = "#7fba84"

        self.log_view.insertHtml(
            f'<span style="color:{color}; font-family: monospace; white-space:pre;">{text}</span><br>'
        )
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    # ── Window events ──

    def closeEvent(self, event):
        if hasattr(self, "tray") and self.tray.isVisible():
            self.hide()
            event.ignore()
            self.tray.showMessage(
                "FortiVPN",
                "Running in system tray. Right-click to quit.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        else:
            self._quit()

    def _quit(self):
        if self.vpn_worker and self.vpn_worker.isRunning():
            self.vpn_worker.stop()
            self.vpn_worker.wait(3000)
        QApplication.quit()


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLESHEET)
    if APP_ICON:
        app.setWindowIcon(QIcon(str(APP_ICON)))

    # Try to set a nice app font
    for font_name in ["JetBrains Mono", "Fira Code", "Cascadia Code", "Hack", "Monospace"]:
        f = QFont(font_name, 12)
        if f.exactMatch() or font_name == "Monospace":
            app.setFont(f)
            break

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
