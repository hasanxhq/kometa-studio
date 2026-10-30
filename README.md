# Kometa Studio

An arr-style web GUI for [Kometa](https://github.com/Kometa-Team/Kometa): it schedules Kometa runs, edits Kometa's config and YAML files with validation, and shows what each run changed in Plex.

> **Unofficial.** Kometa Studio is an independent project. It is not made by, endorsed by, or affiliated with the Kometa team. It runs an unmodified Kometa install and never changes Kometa's code.

**Status:** early development. The app shell runs, and Settings → Plex connects Kometa to your Plex server. Running Kometa comes next.

## Run it with Docker (WSL2 or Linux)

```bash
mkdir -p config
docker compose up -d --build
```

Then open http://localhost:8484. `config/` becomes Kometa's config folder inside the container. Keep the repo and `config/` on WSL's own disk rather than under `/mnt/c`.

Settings in `compose.yaml` can be overridden with environment variables: `PUID`, `PGID`, `TZ`, `STUDIO_PORT`, `KOMETA_CONFIG_DIR`, `KOMETA_TAG`.

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
