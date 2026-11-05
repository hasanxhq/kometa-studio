# Install Starr Studio on Ultra.cc

This guide explains how to install Starr Studio and Kometa on an [Ultra.cc](https://ultra.cc) seedbox.

Ultra.cc provides a shared Linux environment without root access or Docker. Applications run under your user account using `systemd --user` units, and the web interface is exposed through Ultra's Nginx reverse proxy.

## Security on shared servers (read this first)

Ultra.cc slots share their operating system and localhost (`127.0.0.1`) with other users on the same server. By default, Starr Studio permits unauthenticated access from local network connections.

To prevent other users on the server from accessing your Studio instance:
1. Keep `STUDIO_HOST=127.0.0.1` in your environment file.
2. Set `STUDIO_ALLOW_LOCAL=false` in `~/.config/starr-studio/studio.env`.
3. Set a username and password in **Settings → General** immediately upon first start.

With `STUDIO_ALLOW_LOCAL=false`, Studio requires password sign-in for all connections, including those originating from localhost.

---

## 1. Reserve a port

Ultra.cc assigns a range of ports to each slot. Run the following command via SSH to view your available free ports:

```bash
app-ports free
```

Choose one free port from the list (for example, `34567`). Replace `<port>` with your chosen port throughout the rest of this guide.

## 2. Install Kometa

Kometa must be installed in its own Python virtual environment.

Clone Kometa at the pinned release tag **v2.5.4**:

```bash
git clone --branch v2.5.4 https://github.com/Kometa-Team/Kometa.git ~/kometa
```

Create a virtual environment and install dependencies:

```bash
python3 -m venv ~/kometa/.venv
~/kometa/.venv/bin/pip install --upgrade pip
~/kometa/.venv/bin/pip install -r ~/kometa/requirements.txt
```

Create Kometa's configuration folder:

```bash
mkdir -p ~/kometa/config
```

If you have an existing Kometa configuration, place `config.yml` in `~/kometa/config/config.yml`. Otherwise, Studio will create one during first-run setup.

## 3. Install Starr Studio

Create a dedicated directory and virtual environment for Studio:

```bash
mkdir -p ~/starr-studio
python3 -m venv ~/starr-studio/.venv
~/starr-studio/.venv/bin/pip install --upgrade pip
```

Install Studio from the release wheel:

```bash
~/starr-studio/.venv/bin/pip install starr_studio-<version>-py3-none-any.whl
```

*(Alternatively, to build from source, clone the repository, build the frontend with `npm ci && npm run build` inside `frontend/`, and install with `pip install ~/starr-studio/repo`).*

Verify the installation:

```bash
~/starr-studio/.venv/bin/starr-studio --version
```

## 4. Configure the environment file

Create the Studio configuration directory:

```bash
mkdir -p ~/.config/starr-studio
```

Create `~/.config/starr-studio/studio.env` with your editor of choice (e.g. `nano ~/.config/starr-studio/studio.env`):

```bash
STUDIO_HOST=127.0.0.1
STUDIO_PORT=<port>
STUDIO_DATA_DIR=/home/<username>/.config/starr-studio/data
STUDIO_KOMETA_PYTHON=/home/<username>/kometa/.venv/bin/python3
STUDIO_KOMETA_ENTRY=/home/<username>/kometa/kometa.py
STUDIO_KOMETA_CONFIG=/home/<username>/kometa/config/config.yml
STUDIO_KOMETA_SCHEMAS=/home/<username>/kometa/json-schema
STUDIO_ALLOW_LOCAL=false
STUDIO_TIMEZONE=UTC
```

Replace:
- `<port>` with the port you selected from `app-ports free`.
- `<username>` with your Ultra.cc username (`whoami`). Systemd environment files do not expand `~` or `$HOME`.

## 5. Set up the systemd user unit

Create the user unit directory:

```bash
mkdir -p ~/.config/systemd/user
```

Create `~/.config/systemd/user/starr-studio.service`:

```ini
[Unit]
Description=Starr Studio
After=network.target

[Service]
Type=simple
EnvironmentFile=%h/.config/starr-studio/studio.env
ExecStart=%h/starr-studio/.venv/bin/starr-studio serve
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

Reload systemd, enable the service, and start it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now starr-studio
```

User process lingering is enabled by default on Ultra.cc, so user services continue running after you disconnect from SSH.

Verify that Studio is running:

```bash
systemctl --user status starr-studio
```

Check the logs if needed:

```bash
journalctl --user -u starr-studio -f
```

## 6. Configure the Nginx reverse proxy

Ultra.cc manages your web server using Nginx location snippets in `~/.apps/nginx/proxy.d/`.

Create the file `~/.apps/nginx/proxy.d/starr-studio.conf`:

```nginx
location /kometa/ {
    proxy_pass http://127.0.0.1:<port>;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;

    # Disable buffering for live Server-Sent Events (SSE) logs
    proxy_buffering off;
    proxy_http_version 1.1;
    proxy_read_timeout 1h;

    # Poster uploads up to 10 MB
    client_max_body_size 12m;
}
```

Replace `<port>` with your chosen port from step 1.

Test and reload the Nginx configuration:

```bash
app-nginx restart
```

## 7. Access and first-run setup

Open your browser to:

```text
https://<username>.<server>.usbx.me/kometa/
```

Complete the first-run setup wizard (Plex server, TMDb API key, libraries).

Next, secure your instance:
1. Open **Settings → General**.
2. Set a **Username** and **Password**.
3. Under **URL base**, confirm `/kometa` is configured.
4. Under **Trusted proxies**, add `127.0.0.1` so Ultra's local Nginx proxy passes your real IP through.
5. Save changes.

## Maintenance and updates

To restart Studio:

```bash
systemctl --user restart starr-studio
```

To update Kometa:

```bash
cd ~/kometa
git fetch --tags
git checkout <tag>
~/kometa/.venv/bin/pip install --upgrade -r requirements.txt
systemctl --user restart starr-studio
```

To update Studio from a newer release wheel:

```bash
~/starr-studio/.venv/bin/pip install --upgrade starr_studio-<new_version>-py3-none-any.whl
systemctl --user restart starr-studio
```
