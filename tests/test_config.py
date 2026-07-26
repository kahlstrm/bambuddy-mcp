"""Tests for configuration loading."""

import pytest

from bambuddy_mcp.config import Config


@pytest.fixture(autouse=True)
def isolate_api_key_config(monkeypatch, tmp_path):
    monkeypatch.delenv("BAMBUDDY_API_KEY_FILE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def test_config_from_env_defaults(monkeypatch, tmp_path):
    """Test default values when env vars not set."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BAMBUDDY_URL", raising=False)
    monkeypatch.delenv("BAMBUDDY_API_KEY", raising=False)
    monkeypatch.delenv("BAMBUDDY_DIRECT_MODE", raising=False)
    monkeypatch.delenv("BAMBUDDY_CENSOR_ACCESS_CODE", raising=False)
    monkeypatch.delenv("BAMBUDDY_CENSOR_SERIAL", raising=False)
    monkeypatch.delenv("BAMBUDDY_CENSOR_MODEL_FILENAME", raising=False)
    monkeypatch.delenv("BAMBUDDY_UPLOAD_ROOT", raising=False)

    config = Config.from_env()

    assert config.base_url == "http://localhost:8000"
    assert config.api_key == ""
    assert config.direct_mode is False
    assert config.censor_access_code is True
    assert config.censor_serial is True
    assert config.censor_model_filename is False
    assert config.upload_root == str(tmp_path.resolve())


def test_config_from_env_custom(monkeypatch):
    """Test custom values from env vars."""
    monkeypatch.setenv("BAMBUDDY_URL", "http://custom:9000")
    monkeypatch.setenv("BAMBUDDY_API_KEY", "secret")
    monkeypatch.setenv("BAMBUDDY_DIRECT_MODE", "true")
    monkeypatch.setenv("BAMBUDDY_CENSOR_ACCESS_CODE", "false")
    monkeypatch.setenv("BAMBUDDY_CENSOR_SERIAL", "false")
    monkeypatch.setenv("BAMBUDDY_CENSOR_MODEL_FILENAME", "true")
    monkeypatch.setenv("BAMBUDDY_UPLOAD_ROOT", "/workspace/models")

    config = Config.from_env()

    assert config.base_url == "http://custom:9000"
    assert config.api_key == "secret"
    assert config.direct_mode is True
    assert config.censor_access_code is False
    assert config.censor_serial is False
    assert config.censor_model_filename is True
    assert config.upload_root == "/workspace/models"


def test_reads_api_key_from_explicit_file(monkeypatch, tmp_path):
    key_file = tmp_path / "api-key"
    key_file.write_text("file-secret\n")
    key_file.chmod(0o600)
    monkeypatch.delenv("BAMBUDDY_API_KEY", raising=False)
    monkeypatch.setenv("BAMBUDDY_API_KEY_FILE", str(key_file))

    assert Config.from_env().api_key == "file-secret"


def test_reads_api_key_from_default_xdg_file(monkeypatch, tmp_path):
    key_file = tmp_path / "bambuddy" / "api-key"
    key_file.parent.mkdir()
    key_file.write_text("xdg-secret\n")
    key_file.chmod(0o600)
    monkeypatch.delenv("BAMBUDDY_API_KEY", raising=False)
    monkeypatch.delenv("BAMBUDDY_API_KEY_FILE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert Config.from_env().api_key == "xdg-secret"


def test_environment_api_key_takes_precedence(monkeypatch, tmp_path):
    key_file = tmp_path / "api-key"
    key_file.write_text("file-secret\n")
    key_file.chmod(0o600)
    monkeypatch.setenv("BAMBUDDY_API_KEY", "environment-secret")
    monkeypatch.setenv("BAMBUDDY_API_KEY_FILE", str(key_file))

    assert Config.from_env().api_key == "environment-secret"


def test_missing_explicit_api_key_file_is_rejected(monkeypatch, tmp_path):
    monkeypatch.delenv("BAMBUDDY_API_KEY", raising=False)
    monkeypatch.setenv("BAMBUDDY_API_KEY_FILE", str(tmp_path / "missing"))

    with pytest.raises(ValueError, match="API key file does not exist"):
        Config.from_env()


def test_insecure_api_key_file_permissions_are_rejected(monkeypatch, tmp_path):
    key_file = tmp_path / "api-key"
    key_file.write_text("file-secret\n")
    key_file.chmod(0o644)
    monkeypatch.delenv("BAMBUDDY_API_KEY", raising=False)
    monkeypatch.setenv("BAMBUDDY_API_KEY_FILE", str(key_file))

    with pytest.raises(ValueError, match="permissions"):
        Config.from_env()


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("no", False),
        ("", False),
    ],
)
def test_direct_mode_parsing(monkeypatch, value, expected):
    """Test various truthy/falsy values for direct mode."""
    monkeypatch.setenv("BAMBUDDY_DIRECT_MODE", value)
    assert Config.from_env().direct_mode is expected
