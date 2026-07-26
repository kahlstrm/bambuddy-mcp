"""Configuration management via environment variables."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path


def _load_api_key() -> str:
    environment_key = os.environ.get("BAMBUDDY_API_KEY")
    if environment_key:
        return environment_key

    configured_path = os.environ.get("BAMBUDDY_API_KEY_FILE")
    if configured_path:
        key_path = Path(configured_path).expanduser()
    else:
        config_home = os.environ.get("XDG_CONFIG_HOME")
        config_root = (
            Path(config_home).expanduser() if config_home else Path.home() / ".config"
        )
        key_path = config_root / "bambuddy" / "api-key"

    if not key_path.exists():
        if configured_path:
            raise ValueError(f"API key file does not exist: {key_path}")
        return ""
    if not key_path.is_file():
        raise ValueError(f"API key path is not a file: {key_path}")

    permissions = stat.S_IMODE(key_path.stat().st_mode)
    if permissions & 0o077:
        raise ValueError(
            f"API key file has insecure permissions {permissions:o}: {key_path}"
        )

    try:
        api_key = key_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ValueError(f"Could not read API key file: {key_path}") from error
    if not api_key:
        raise ValueError(f"API key file is empty: {key_path}")
    return api_key


@dataclass
class Config:
    """Configuration for the Bambuddy MCP server."""

    base_url: str
    api_key: str
    direct_mode: bool
    censor_access_code: bool
    censor_serial: bool
    censor_model_filename: bool
    upload_root: str | None = None

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""

        def _bool_env(name: str, default: str) -> bool:
            return os.environ.get(name, default).lower() not in ("0", "false", "no")

        return cls(
            base_url=os.environ.get("BAMBUDDY_URL", "http://localhost:8000"),
            api_key=_load_api_key(),
            direct_mode=os.environ.get("BAMBUDDY_DIRECT_MODE", "").lower()
            in ("1", "true", "yes"),
            censor_access_code=_bool_env("BAMBUDDY_CENSOR_ACCESS_CODE", "true"),
            censor_serial=_bool_env("BAMBUDDY_CENSOR_SERIAL", "true"),
            censor_model_filename=_bool_env("BAMBUDDY_CENSOR_MODEL_FILENAME", "false"),
            upload_root=os.environ.get("BAMBUDDY_UPLOAD_ROOT")
            or str(Path.cwd().resolve()),
        )
