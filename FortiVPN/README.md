# FortiVPN Client

<p align="center">
  <img src="data/com.github.fortivpn_client.svg" width="128" height="128" alt="FortiVPN Client Icon"/>
</p>

<p align="center">
  <strong>A native GNOME client for openfortivpn with SAML/SSO authentication.</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#installation">Installation</a> •
  <a href="#usage">Usage</a> •
  <a href="#troubleshooting">Troubleshooting</a> •
  <a href="#contributing">Contributing</a>
</p>

---

## Features

- **SAML/SSO Authentication** — Embedded WebKit browser handles your identity provider login (Azure AD, Okta, Google, etc.)
- **Multiple Profiles** — Save and manage multiple VPN gateway configurations
- **System Tray Icon** — See connection status at a glance via AppIndicator
- **Native GNOME UI** — Built with GTK4 + libadwaita for a seamless desktop experience
- **Real-time Logs** — Monitor the openfortivpn connection log in the app
- **Polkit Integration** — Secure privilege escalation without running the GUI as root
- **Universal Installer** — One script for Ubuntu, Fedora, Arch, openSUSE, and derivatives

## Screenshots

| Disconnected | SAML Login | Connected |
|---|---|---|
| Profile list with connection controls | WebKit browser for SSO | Active VPN with log output |

## Installation

There are three supported install paths. Pick the one that matches your distro
and how isolated you want the app to be:

1. **Distro packages via `install.sh`** — native install, lightest footprint,
   works on the major package managers.
2. **Flatpak** — recommended cross-distro option; identical build everywhere,
   sandboxed UI that delegates the privileged `openfortivpn` call to the host.
3. **Manual** — install the components yourself; for unusual distros,
   air-gapped systems, or when you want full control.

### 1. Distro packages (install.sh)

```bash
git clone https://github.com/fortivpn-client/fortivpn-client.git
cd fortivpn-client
chmod +x FortiVPN/install.sh
./FortiVPN/install.sh install
```

The installer automatically detects your distribution and installs all
dependencies.

| Distribution | Package Manager | Status |
|---|---|---|
| Ubuntu 23.04+ / Debian 13+ | apt | ✅ Tested |
| Fedora 39+ | dnf | ✅ Tested |
| Arch Linux / Manjaro | pacman | ✅ Tested |
| openSUSE Tumbleweed | zypper | ✅ Tested |
| Linux Mint / Pop!_OS | apt | ✅ Compatible |
| RHEL 9+ / Rocky / Alma | dnf | ⚠️ May need EPEL |
| Alpine Linux | apk | ✅ Supported |
| Void Linux | xbps | ✅ Supported |
| Gentoo | emerge | ℹ️ Prints ebuild hints — no auto-emerge |
| NixOS | — | ❌ Aborts; use the Flatpak or write a flake |
| Anything else | — | ⚠️ Prints required components and recommends Flatpak |

### 2. Flatpak (recommended for cross-distro)

The Flatpak build works identically on every Linux distribution. The UI is
sandboxed; the privileged `openfortivpn` invocation is forwarded to the host
via `flatpak-spawn --host`, so the host system needs `openfortivpn` installed
(any package manager, or built from source).

```bash
flatpak install --user flathub org.gnome.Platform//46 org.gnome.Sdk//46
flatpak-builder --user --install --force-clean build \
    FortiVPN/flatpak/com.github.fortivpn_client.yml
flatpak run com.github.fortivpn_client
```

See [`FortiVPN/flatpak/README.md`](flatpak/README.md) for build details and
the flatpak-spawn host-bridge design.

### 3. Manual install

If the installer doesn't cover your distro, install these manually:

- `openfortivpn` (≥ 1.17.0 recommended)
- `python3` (≥ 3.10)
- `python3-gi` (PyGObject)
- `gtk4` + `libadwaita` (≥ 1.4)
- `webkit2gtk 6.0` (WebKitGTK for GTK4)
- `polkit` / `pkexec`

**Optional (for tray icon):**
- `gir1.2-ayatanaappindicator3-0.1` (Debian/Ubuntu)
- `libayatana-appindicator-gtk3` (Fedora/Arch)
- GNOME: Install [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/) extension

### Uninstall

```bash
./install.sh uninstall
```

## Usage

### Launch

From your application grid, search **"FortiVPN"**, or from terminal:

```bash
fortivpn-client
```

### Connecting

1. **Add a Profile** — Click the `+` button, enter your VPN gateway hostname, port, and optional realm
2. **Connect** — Click the play button on your profile
3. **Authenticate** — A browser window opens for SAML/SSO login with your identity provider
4. **Done** — The app captures the authentication cookie and starts the VPN tunnel

### Profile Options

| Field | Description | Example |
|---|---|---|
| Host | VPN gateway hostname | `vpn.company.com` |
| Port | Gateway port | `443` |
| Realm | SAML realm (if required) | `mycompany` |
| Trusted Cert | SHA-256 hash of gateway cert | `a1b2c3d4...` |
| Extra Args | Additional openfortivpn flags | `--pppd-use-peerdns=1` |

### Getting the Trusted Certificate Hash

On first connection, openfortivpn may show a certificate error with the hash. Copy it into the profile's "Trusted Cert" field, or run:

```bash
echo | openssl s_client -connect vpn.company.com:443 2>/dev/null | \
  openssl x509 -fingerprint -sha256 -noout | tr -d ':'
```

## How It Works

```
┌─────────────────┐     SAML      ┌──────────────┐
│  FortiVPN       │ ───────────── │   Identity    │
│  Client (GTK4)  │   WebKit      │   Provider    │
│                 │ ◄──────────── │  (Azure AD,   │
│  ┌───────────┐  │   Cookie      │   Okta, etc.) │
│  │ WebKit    │  │               └──────────────┘
│  │ Browser   │  │
│  └───────────┘  │
│        │        │
│    SVPNCOOKIE   │
│        │        │
│  ┌───────────┐  │    pkexec     ┌──────────────┐
│  │ VPN       │──│──────────────▶│ openfortivpn │
│  │ Controller│  │               │  (as root)   │
│  └───────────┘  │               └──────────────┘
│        │        │
│  ┌───────────┐  │
│  │ Tray Icon │  │
│  │ (status)  │  │
│  └───────────┘  │
└─────────────────┘
```

1. The app opens a WebKit window pointing to the FortiGate SAML login endpoint
2. The user authenticates with their identity provider
3. The app intercepts the `SVPNCOOKIE` from the authentication callback
4. The cookie is passed to `openfortivpn` via `pkexec` for the actual tunnel
5. The tray icon and UI update to reflect connection status

## Configuration

Profiles are stored in:
```
~/.config/fortivpn-client/profiles.json
```

Logs are stored in:
```
~/.local/share/fortivpn-client/logs/
```

## Troubleshooting

### "openfortivpn not found"

Install it for your distribution:
```bash
# Ubuntu/Debian
sudo apt install openfortivpn

# Fedora
sudo dnf install openfortivpn

# Arch
sudo pacman -S openfortivpn
```

### SAML window is blank or doesn't load

- Ensure `webkit2gtk 6.0` is installed (not the older 4.x)
- Some corporate proxies may interfere — try connecting from a different network first

### Tray icon not showing (GNOME)

GNOME doesn't support tray icons natively. Install the [AppIndicator Support](https://extensions.gnome.org/extension/615/appindicator-support/) extension:

```bash
# Via Extension Manager (Flatpak)
flatpak install flathub com.mattjakeman.ExtensionManager

# Or manually
gnome-extensions install appindicatorsupport@rgcjonas.gmail.com
```

### Polkit keeps asking for password

The included polkit rule caches auth for the `wheel` group. Make sure your user is in `wheel` (Fedora/Arch) or `sudo` (Ubuntu):

```bash
groups $USER
```

### Certificate errors

Get the gateway certificate hash and add it to your profile's "Trusted Cert" field. See [Getting the Trusted Certificate Hash](#getting-the-trusted-certificate-hash).

## Development

```bash
# Clone
git clone https://github.com/fortivpn-client/fortivpn-client.git
cd fortivpn-client

# Install deps only
./install.sh deps-only

# Run directly
python3 src/fortivpn_client.py
```

### Project Structure

```
fortivpn-client/
├── src/
│   └── fortivpn_client.py      # Main application
├── data/
│   ├── com.github.fortivpn_client.svg          # App icon
│   └── com.github.fortivpn_client.metainfo.xml # AppStream metadata
├── install.sh                   # Universal installer
├── LICENSE
└── README.md
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the **GNU General Public License v3.0** — see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [openfortivpn](https://github.com/adrienverge/openfortivpn) — The VPN client this GUI wraps
- [GNOME](https://www.gnome.org/) — For GTK4 and libadwaita
- [WebKitGTK](https://webkitgtk.org/) — For the embedded SAML browser

---

<p align="center">
  Made with ❤️ for the Linux VPN community
</p>
