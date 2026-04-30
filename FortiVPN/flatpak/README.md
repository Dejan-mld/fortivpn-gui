# FortiVPN Client — Flatpak

The Flatpak build is the recommended installation path for distros not
covered by `install.sh` (anything outside Debian/Ubuntu, Fedora/RHEL, Arch,
openSUSE, Alpine, Void). It produces an identical, self-contained build on
every distro.

## Build & install

```bash
# From the repo root
flatpak install --user flathub org.gnome.Platform//46 org.gnome.Sdk//46
flatpak-builder --user --install --force-clean build \
    FortiVPN/flatpak/com.github.fortivpn_client.yml
```

## Run

```bash
flatpak run com.github.fortivpn_client
```

The GNOME window opens, profiles are stored under
`~/.var/app/com.github.fortivpn_client/config/fortivpn-client/profiles.json`.

## How privileged work happens from inside the sandbox

`openfortivpn` cannot run inside the Flatpak — it needs root and
`/dev/net/tun`, neither of which the sandbox provides. Instead, the app
detects it is sandboxed (`/.flatpak-info` exists or `$FLATPAK_ID` is set)
and prefixes every privileged invocation with `flatpak-spawn --host`. That
talks to the `org.freedesktop.Flatpak` portal (granted via the
`--talk-name=org.freedesktop.Flatpak` finish-arg) and runs the command on
the host.

Concretely, instead of:

```
sudo --non-interactive openfortivpn vpn.example.com:443 --saml-login
```

the sandboxed app runs:

```
flatpak-spawn --host sudo --non-interactive openfortivpn vpn.example.com:443 --saml-login
```

This means **`openfortivpn` must be installed on the host**, not in the
Flatpak. On a host that has `install.sh deps-only` already applied — or
where `openfortivpn` was installed by hand — the Flatpak picks it up
automatically. Likewise, the polkit / sudoers rule from
`./install.sh fix-sudo` (run on the host) lets the sandboxed app start the
tunnel without a password prompt.

## Flathub submission notes

The manifest, desktop file, and AppStream metainfo XML are laid out for
direct submission to Flathub. To pre-validate locally:

```bash
flatpak run --command=appstreamcli org.flatpak.Builder validate \
    FortiVPN/flatpak/com.github.fortivpn_client.metainfo.xml
flatpak run --command=desktop-file-validate org.flatpak.Builder \
    FortiVPN/flatpak/com.github.fortivpn_client.desktop
```
