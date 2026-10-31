# Kometa Studio

An arr-style web GUI for [Kometa](https://github.com/Kometa-Team/Kometa): it schedules Kometa runs, edits Kometa's config and YAML files with validation, and shows what each run changed in Plex.

> **Unofficial.** Kometa Studio is an independent project. It is not made by, endorsed by, or affiliated with the Kometa team. It runs an unmodified Kometa install and never changes Kometa's code.

**Status:** early development. Settings → Plex connects Kometa to your Plex server, Libraries shows your Plex collections (managed by Kometa or not) next to what Kometa's config does, Activity → Queue runs Kometa with a live log, History shows what each run changed, System → Tasks schedules runs, and Kometa's files can be edited, as YAML checked as you type or with forms for collections and overlays, with Kometa checking every save (with backups and restore). Health checks and polish come next.

## Run it with Docker (WSL2 or Linux)

```bash
mkdir -p config
docker compose up -d --build
```

Then open http://localhost:8484. `config/` becomes Kometa's config folder inside the container. Keep the repo and `config/` on WSL's own disk rather than under `/mnt/c`.

Settings in `compose.yaml` can be overridden with environment variables: `PUID`, `PGID`, `TZ`, `STUDIO_PORT`, `KOMETA_CONFIG_DIR`, `KOMETA_TAG`. Schedules use `TZ` unless `STUDIO_TIMEZONE` is set.

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
