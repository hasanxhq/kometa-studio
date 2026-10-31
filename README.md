# Kometa Studio

An arr-style web GUI for [Kometa](https://github.com/Kometa-Team/Kometa): it schedules Kometa runs, edits Kometa's config and YAML files with validation, and shows what each run changed in Plex.

> **Unofficial.** Kometa Studio is an independent project. It is not made by, endorsed by, or affiliated with the Kometa team. It runs an unmodified Kometa install and never changes Kometa's code.

**Status: alpha.** It's new and has only been tested on one setup, so expect rough edges. It edits your Kometa config, and Kometa changes your Plex library. Studio backs up every file it changes, and you can restore from System → Backup.

## What it does

- **First-run setup** walks you through what Kometa needs: Plex, a TMDb key and at least one library.
- **Libraries** shows your Plex collections, managed by Kometa or not, next to what Kometa's config does. Collections, overlays, playlists and Kometa's settings have forms, and every YAML file can be edited directly. Kometa checks each save.
- **Activity** runs Kometa with a live log, and shows what each run changed in Plex.
- **System** schedules runs, reports health, and makes full backups.
- **Settings** connects Radarr, Sonarr, Tautulli, MDBList and Maintainerr, and sets up notifications.

## What you need

- Docker, on Linux or WSL2
- A Plex server, and a Plex account or token for it
- A free [TMDb API key](https://www.themoviedb.org/settings/api). Kometa won't run without one.

## Run it with Docker (WSL2 or Linux)

There's no published image yet, so you build it from this repository:

```bash
git clone https://github.com/hasanxhq/kometa-studio.git
cd kometa-studio
mkdir -p config
docker compose up -d --build
```

Then open http://localhost:8484, and first-run setup takes it from there. `config/` becomes Kometa's config folder inside the container. Keep the repo and `config/` on WSL's own disk rather than under `/mnt/c`.

Settings in `compose.yaml` can be overridden with environment variables or a `.env` file: `PUID`, `PGID`, `TZ`, `STUDIO_PORT`, `KOMETA_CONFIG_DIR`, `KOMETA_TAG`. Set `TZ` to your timezone, such as `Europe/Paris`: it's UTC otherwise. Schedules use `TZ` unless `STUDIO_TIMEZONE` is set.

### Before you open it up

Until you set up a sign-in, Studio answers anyone on your local network without asking who they are. Internet addresses are refused. Set a username and password in first-run setup or Settings → General, and always before you put Studio behind a reverse proxy.

### If it can't reach TMDb or another service

Some networks block TMDb. Settings → Network has a proxy and DNS over HTTPS, and they apply to Kometa as well as Studio.

### Known limitations

- Calls per service on System → Status aren't available: Kometa 2.5.3 crashes with `--timings`, so Studio doesn't use it.
- MyAnimeList, AniDB, WeTrakr, FlickList, Floppy and Serializd can't be connected from Studio yet. Their settings go in `config.yml`, which you can edit from the Libraries page.
- Simkl, YamTrack, Tracearr and text file sources are under Show Advanced, not in the source list.

### Behind a reverse proxy

Set a **URL base** (such as `/kometa`) in Settings → General. Studio answers with and without it, so the proxy can pass the path on or strip it. For nginx:

```nginx
location /kometa/ {
    proxy_pass http://kometa-studio:8484;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;  # live run logs
}
```

Requests that come through a proxy never count as local for sign-in, unless the proxy is listed under **Trusted proxies** in the same card. List the proxy's own address rather than a whole network where you can.

## Develop

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
kometa-studio serve          # API on http://127.0.0.1:8484
cd frontend && npm install && npm run dev   # UI on http://localhost:5173, proxying /api
```

Tests: `pytest` and `cd frontend && npm test`.

## License

[MIT](LICENSE)
