# syntax=docker/dockerfile:1.7
# Kometa Studio on top of the official Kometa image (handoff v2 §3.1).
# Kometa stays untouched at / with its own venv at /.venv; Studio gets /studio and its own venv.
ARG KOMETA_TAG=v2.5.3

FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# vite.config.ts writes the build to ../kometa_studio/static
RUN npm run build

# Kometa's image leaves out its JSON schemas (its .dockerignore), so take them from the same release's source
# for --schema-path. Kometa itself is unchanged.
FROM node:22-slim AS schemas
ARG KOMETA_TAG
ADD https://github.com/Kometa-Team/Kometa/archive/refs/tags/${KOMETA_TAG}.tar.gz /tmp/kometa.tar.gz
RUN mkdir /json-schema \
 && tar -xzf /tmp/kometa.tar.gz -C /json-schema --strip-components=2 --wildcards "*/json-schema/*" \
 && test -f /json-schema/config-schema.json

FROM kometateam/kometa:${KOMETA_TAG}
WORKDIR /studio
COPY pyproject.toml VERSION README.md LICENSE ./
COPY kometa_studio/ ./kometa_studio/
COPY --from=frontend /src/kometa_studio/static/ ./kometa_studio/static/
COPY --from=schemas /json-schema/ /studio/json-schema/
# Use the image's system Python, not Kometa's venv, so the two dependency sets never mix.
RUN /usr/local/bin/python3 -m venv /studio/.venv \
 && /studio/.venv/bin/pip install --no-cache-dir --disable-pip-version-check /studio

ENV STUDIO_HOST=0.0.0.0 \
    STUDIO_PORT=8484 \
    STUDIO_DATA_DIR=/config/.studio \
    STUDIO_KOMETA_PYTHON=/.venv/bin/python3 \
    STUDIO_KOMETA_ENTRY=/kometa.py \
    STUDIO_KOMETA_CONFIG=/config/config.yml \
    STUDIO_KOMETA_SCHEMAS=/studio/json-schema

EXPOSE 8484
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD ["/studio/.venv/bin/python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['STUDIO_PORT']}/api/v1/ping\", timeout=4)"]
ENTRYPOINT ["/tini", "-s", "--", "/studio/.venv/bin/kometa-studio", "serve"]
