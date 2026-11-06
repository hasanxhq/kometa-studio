<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/svg/lockup-on-dark.svg">
  <img src="brand/svg/lockup-on-light.svg" alt="Starr Studio" height="56">
</picture>

# Starr Studio

**A studio for organising your Plex library, with the \*arr suite.**

Group titles into collections, give them posters and overlays, and let Radarr, Sonarr or Seerr fetch what's missing, all without writing YAML. Powered by [Kometa](https://github.com/Kometa-Team/Kometa): Studio writes Kometa's config, runs it and shows what each run changed in Plex.

> **Unofficial.** Starr Studio is an independent project. It is not made by, endorsed by, or affiliated with the Kometa team. It runs an unmodified Kometa install and never changes Kometa's code.

**Status: alpha.** It's new and has only been tested on one setup, so expect rough edges. It edits your Kometa config, and Kometa changes your Plex library. Studio backs up every file it changes, and you can restore from System → Backup.

## What it does

**Organise what you have**
- **Collections:** build one from smart filters, lists (TMDb, IMDb, Letterboxd, MDBList and more), individual titles or a Plex search, or combine several. A preview shows what's already in your library and what's missing before you build.
- **Ready-made:** Kometa's ready-made collections (genres, studios, decades, awards, people and more) as galleries. Pick the ones you want and build them in one go.
- **Posters and overlays:** upload or link a poster for each collection, and place Kometa's overlays (resolution, audio, ratings and more) with the overlay designer.
- **Playlists** and every library's settings have forms too. Anything Studio can't describe stays in Kometa's own files, which you can still edit, and Kometa checks every save.

**Fill the gaps**
- **Download missing:** a collection can ask Radarr and Sonarr, or Seerr, for the titles it lacks, with a cap and a quality profile per collection. Requests are off until you turn them on.
- **Requests** lists what was asked for and where it is. When a title arrives in Plex, Studio rebuilds just the collection that asked for it.

**Move over from Kometa**
- Already run Kometa? **Move over** reads your setup and shows how each collection would land in Studio. **Switch over** takes a full backup first, and **Undo** puts everything back. You can also upload a single collection file.

**Keep it running**
- **Activity** runs Kometa with a live log and shows what each run changed in Plex.
- **System** schedules runs, reports health, and makes full backups.
- **Settings** connects Radarr, Sonarr, Seerr, Tautulli, MDBList and Maintainerr, and sets up notifications.

## What you need

- Docker, on Linux or WSL2
- A Plex server, and a Plex account or token for it
- A free [TMDb API key](https://www.themoviedb.org/settings/api). Kometa won't run without one.

## Run it with Docker (WSL2 or Linux)

There's no published image yet, so you build it from this repository:

```bash
git clone https://github.com/hasanxhq/starr-studio.git
cd starr-studio
mkdir -p config
docker compose up -d --build
```

Then open http://localhost:8484, and first-run setup takes it from there. `config/` becomes Kometa's config folder inside the container. Keep the repo and `config/` on WSL's own disk rather than under `/mnt/c`.

Settings in `compose.yaml` can be overridden with environment variables or a `.env` file: `PUID`, `PGID`, `TZ`, `STUDIO_PORT`, `STUDIO_ALLOW_LOCAL`, `KOMETA_CONFIG_DIR`, `KOMETA_TAG`. Set `TZ` to your timezone, such as `Europe/Paris`: it's UTC otherwise. Schedules use `TZ` unless `STUDIO_TIMEZONE` is set.

### Install from a wheel

Each [GitHub release](https://github.com/hasanxhq/starr-studio/releases) attaches a Python wheel with the frontend already built. Download the `.whl`, then:

```bash
pip install path/to/starr_studio-*.whl
starr-studio serve
```

You still need a Kometa install and its config folder: see [Install without Docker](docs/install-without-docker.md).

Other setups:
- [Install without Docker](docs/install-without-docker.md) (Python 3.12, systemd user service)
- [Reverse proxy setup](docs/reverse-proxy.md) (nginx, Caddy, Traefik, SWAG)
- [Ultra.cc seedbox](docs/seedboxes/ultra.md) (one script: `deploy/install-seedbox.sh`)

### Before you open it up

Until you set up a sign-in, Studio answers anyone on your local network without asking who they are. Internet addresses are refused. Set a username and password in first-run setup or Settings → General, and always before you put Studio behind a reverse proxy.

**On a shared server** (for example a seedbox such as Ultra.cc), loopback and the private network include other customers, so "local" isn't safe. Set a username and password, then set `STUDIO_ALLOW_LOCAL=false` so those addresses no longer skip sign-in.

### If it can't reach TMDb or another service

Some networks block TMDb. Settings → Network has a proxy and DNS over HTTPS, and they apply to Kometa as well as Studio.

### Known limitations

- Calls per service on System → Status need Kometa 2.5.4 or newer (the image's own). Studio leaves `--timings` off for an older Kometa you've pointed it at, because 2.5.3 crashes on that flag.
- MyAnimeList, AniDB, WeTrakr, FlickList, Floppy and Serializd can't be connected from Studio yet. Their settings go in `config.yml`, which you can edit from the Libraries page.
- Simkl, YamTrack, Tracearr and text file sources are under Show Advanced, not in the source list.

### Behind a reverse proxy

Set a **URL base** (such as `/starr-studio`) in Settings → General, and have the proxy pass the path on **as it is, prefix included**: a proxy that strips the prefix sends page loads round in a redirect loop. For nginx:

```nginx
location /starr-studio/ {
    proxy_pass http://starr-studio:8484;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;  # live run logs
}
```

Requests that come through a proxy never count as local for sign-in, unless the proxy is listed under **Trusted proxies** in the same card. List the proxy's own address rather than a whole network where you can. [Reverse proxy setup](docs/reverse-proxy.md) covers Caddy, Traefik and SWAG too.

## Develop

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
starr-studio serve          # API on http://127.0.0.1:8484
cd frontend && npm install && npm run dev   # UI on http://localhost:5173, proxying /api
```

Tests: `pytest` and `cd frontend && npm test`.

## License

[MIT](LICENSE)
