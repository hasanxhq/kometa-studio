# Install Starr Studio without Docker

This guide walks through running Starr Studio directly on Linux using Python 3.12, systemd user services, and a dedicated Kometa installation.

## Prerequisites

- Linux system with `systemd`
- Python 3.12 (with `venv` and `pip`)
- Git
- A running Plex Media Server
- A free [TMDb API key](https://www.themoviedb.org/settings/api)

If building Studio from source instead of using a release wheel, Node.js 20 or newer is also required.

## 1. Install Kometa

Studio manages Kometa as a subprocess. Kometa runs in its own Python virtual environment so its dependencies remain separate from Studio.

The pinned Kometa release is **v2.5.4** (as defined in `Dockerfile`).

Clone Kometa and check out the pinned tag:

```bash
git clone --branch v2.5.4 https://github.com/Kometa-Team/Kometa.git ~/kometa
```

Create Kometa's virtual environment and install its dependencies:

```bash
python3.12 -m venv ~/kometa/.venv
~/kometa/.venv/bin/pip install --upgrade pip
~/kometa/.venv/bin/pip install -r ~/kometa/requirements.txt
```

Create the Kometa configuration directory:

```bash
mkdir -p ~/kometa/config
```

If you have an existing Kometa configuration, place `config.yml` inside `~/kometa/config/`. If this is a new installation, Studio will generate it during first-run setup.

## 2. Install Starr Studio

Create a dedicated directory and virtual environment for Studio:

```bash
mkdir -p ~/starr-studio
python3.12 -m venv ~/starr-studio/.venv
~/starr-studio/.venv/bin/pip install --upgrade pip
```

### Option A: Install from a release wheel (recommended)

Each GitHub release provides a pre-built wheel containing the compiled frontend. Download the wheel from the releases page and install it into Studio's virtual environment:

```bash
~/starr-studio/.venv/bin/pip install starr_studio-<version>-py3-none-any.whl
```

### Option B: Install from source (fallback)

To build from source, clone the repository, build the frontend with Node.js, and install the Python package:

```bash
git clone https://github.com/hasanxhq/starr-studio.git ~/starr-studio/repo
cd ~/starr-studio/repo/frontend
npm ci
npm run build
cd ~/starr-studio
~/starr-studio/.venv/bin/pip install ~/starr-studio/repo
```

Verify that the CLI command works:

```bash
~/starr-studio/.venv/bin/starr-studio --version
```

## 3. Configure the environment file

Create the configuration directory and copy the example environment file:

```bash
mkdir -p ~/.config/starr-studio
cp deploy/studio.env.example ~/.config/starr-studio/studio.env
```

Edit `~/.config/starr-studio/studio.env`. Systemd does not expand `~` or `$HOME` inside environment files, so use full absolute paths:

```bash
STUDIO_HOST=127.0.0.1
STUDIO_PORT=8484
STUDIO_DATA_DIR=/home/<username>/.config/starr-studio/data
STUDIO_KOMETA_PYTHON=/home/<username>/kometa/.venv/bin/python3
STUDIO_KOMETA_ENTRY=/home/<username>/kometa/kometa.py
STUDIO_KOMETA_CONFIG=/home/<username>/kometa/config/config.yml
STUDIO_KOMETA_SCHEMAS=/home/<username>/kometa/json-schema
STUDIO_TIMEZONE=UTC
```

Replace `<username>` with your actual Linux username.

## 4. Set up the systemd user service

Copy the service unit file into your user systemd directory:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/starr-studio.service ~/.config/systemd/user/
```

Reload the systemd user manager, enable the unit, and start it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now starr-studio
```

Check the service status:

```bash
systemctl --user status starr-studio
```

View live logs with `journalctl`:

```bash
journalctl --user -u starr-studio -f
```

To allow the service to start at boot and keep running without an active SSH session, enable lingering:

```bash
loginctl enable-linger $USER
```

## 5. First start

Open `http://127.0.0.1:8484` in your browser (or through an SSH tunnel if remote: `ssh -L 8484:localhost:8484 user@host`).

First-run setup opens automatically. It will ask for:
- Connection to your Plex Media Server (sign-in or token)
- Your TMDb API key
- At least one Plex library to manage

## Security on shared servers

By default, Starr Studio treats requests from loopback and private local network ranges as trusted and does not require authentication.

On a shared machine or seedbox where multiple users have local shell access:
1. Configure a username and password in **Settings → General**.
2. Add `STUDIO_ALLOW_LOCAL=false` to `~/.config/starr-studio/studio.env`.
3. Restart the service:
   ```bash
   systemctl --user restart starr-studio
   ```

When `STUDIO_ALLOW_LOCAL=false` is set, all visitors must log in, even when connecting from `127.0.0.1`.

## Updating

### Updating Kometa

To update Kometa to a newer tag:

```bash
cd ~/kometa
git fetch --tags
git checkout <tag>
~/kometa/.venv/bin/pip install --upgrade -r requirements.txt
systemctl --user restart starr-studio
```

### Updating Starr Studio

When updating from a release wheel:

```bash
~/starr-studio/.venv/bin/pip install --upgrade starr_studio-<new_version>-py3-none-any.whl
systemctl --user restart starr-studio
```

When updating from source:

```bash
cd ~/starr-studio/repo
git pull
cd frontend
npm ci
npm run build
cd ~/starr-studio
~/starr-studio/.venv/bin/pip install --upgrade ~/starr-studio/repo
systemctl --user restart starr-studio
```
