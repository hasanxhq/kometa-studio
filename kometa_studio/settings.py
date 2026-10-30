"""Process-level settings, read from STUDIO_* environment variables.

These are the few things Studio needs before its database exists. Everything a
user changes in the UI lives in SQLite instead.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STUDIO_")

    host: str = "127.0.0.1"
    port: int = 8484
    data_dir: Path = Path("data")

    # Where the Kometa install lives. The Docker image sets all three.
    kometa_python: Path | None = None
    kometa_entry: Path | None = None
    kometa_config: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "studio.db"
