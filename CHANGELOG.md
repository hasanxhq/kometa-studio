# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Repository setup: MIT license, CI, branch workflow rules in AGENTS.md, and a single `VERSION` file.
- App skeleton: `kometa-studio serve`, `/api/v1/status`, SQLite with numbered migrations, and the arr-style navigation shell with a Show Advanced toggle.
- Docker image built on the official Kometa image, plus `compose.yaml`.
- Settings → Plex: sign in with Plex to find your servers. Studio tests every address and preselects the best one (relays last, with a warning). You can also enter a URL and token by hand. Saving writes `plex.url` and `plex.token` into Kometa's `config.yml`, keeping its comments, and backs up the old file to `.studio/backups/`.
