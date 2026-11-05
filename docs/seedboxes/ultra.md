# Install Starr Studio on Ultra.cc

[Ultra.cc](https://ultra.cc) slots have no root and no Docker. Apps run as `systemd --user` services, and Ultra's nginx serves them at `https://<username>.<server>.usbx.me/<path>/`.

## Read this first: a shared server

Your slot shares `127.0.0.1` and the private network with other customers. Studio normally lets those "local" addresses in without a password until sign-in is set up, which on a seedbox means other customers could get in.

The install script closes that gap. It writes the username and password into Studio's database **before Studio first starts**, and sets `STUDIO_ALLOW_LOCAL=false`. From its first second, Studio asks everyone to sign in, `127.0.0.1` included.

## 1. Pick a port

```bash
app-ports free
```

Choose one from the list, for example `34567`.

## 2. Python 3.12

Kometa and Studio need Python 3.12 or newer. Check with `python3 --version`. If it's older, install 3.12 with pyenv as Ultra's Python guide describes, and pass its path to the script with `--python`.

## 3. Run the install script

Get the script and the latest release's wheel (both are on the [releases page](https://github.com/hasanxhq/starr-studio/releases)), then run:

```bash
curl -fsSLO https://raw.githubusercontent.com/hasanxhq/starr-studio/main/deploy/install-seedbox.sh
bash install-seedbox.sh --port 34567 --username <you>
```

It asks for the password twice (hidden). Without `--wheel`, it downloads the newest release's wheel. To use a file you downloaded, add `--wheel ./starr_studio-<version>-py3-none-any.whl`.

What it does, in order:

1. Installs Kometa at the version Studio is tested with (v2.5.4), in `~/kometa` with its own venv.
2. Installs Studio in `~/starr-studio/.venv`.
3. Writes `~/.config/starr-studio/studio.env` (only readable by you) with `STUDIO_ALLOW_LOCAL=false`.
4. Creates your user (`starr-studio create-user`), and sets the URL base to `/starr-studio` and Ultra's nginx (`127.0.0.1`) as a trusted proxy (`starr-studio set-proxy`).
5. Installs and starts the `starr-studio` user service.
6. Writes `~/.apps/nginx/proxy.d/starr-studio.conf` and runs `app-nginx restart`.

`--dry-run` prints all of this without changing anything. `--help` lists every option.

## 4. Open Studio

Open `https://<username>.<server>.usbx.me/starr-studio/` and sign in. First-run setup (Plex, TMDb, a library) takes it from there. If you already use Kometa, point `STUDIO_KOMETA_CONFIG` at your `config.yml` (or copy it to `~/kometa/config/`), restart, and use **Move over from Kometa**.

## Updating

Run the script again with the new wheel (or none, for the latest release):

```bash
bash install-seedbox.sh --port 34567
```

It moves Kometa to the pinned version, reinstalls Studio and restarts it. Your user, `studio.env` and Studio's data stay as they are.

## Day to day

```bash
systemctl --user status starr-studio      # is it running?
systemctl --user restart starr-studio     # after changing studio.env
journalctl --user -u starr-studio -f      # Studio's own log
```

To change the password later, use Settings → General, or from SSH:

```bash
set -a; . ~/.config/starr-studio/studio.env; set +a
~/starr-studio/.venv/bin/starr-studio create-user --username <you> --replace
```

## By hand

Each step the script takes is in [Install without Docker](../install-without-docker.md), and the nginx block is in [deploy/nginx-location.conf](../../deploy/nginx-location.conf) (use your port and URL base).
