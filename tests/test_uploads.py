"""Tests for local file upload boundaries."""

from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response

from bambuddy_mcp.config import Config
from bambuddy_mcp.http import execute_api_call


def upload_config(upload_root: Path | None) -> Config:
    config = Config(
        base_url="http://test.local",
        api_key="key123",
        direct_mode=False,
        censor_access_code=True,
        censor_serial=True,
        censor_model_filename=False,
    )
    config.upload_root = str(upload_root) if upload_root else None
    return config


@pytest.fixture
def upload_tool():
    return {
        "name": "upload_file",
        "path": "/upload",
        "method": "post",
        "query_params": set(),
        "has_file_upload": True,
        "file_params": {"file"},
    }


@pytest.mark.asyncio
@respx.mock
async def test_uploads_file_within_root(tmp_path, upload_tool):
    model = tmp_path / "model.stl"
    model.write_bytes(b"solid model")
    route = respx.post("http://test.local/upload").mock(
        return_value=Response(200, json={"ok": True})
    )

    async with httpx.AsyncClient() as client:
        await execute_api_call(
            upload_config(tmp_path), upload_tool, {"file": str(model)}, client
        )

    request = route.calls.last.request
    assert b'filename="model.stl"' in request.content
    assert b"solid model" in request.content


@pytest.mark.asyncio
@respx.mock
async def test_resolves_relative_path_from_upload_root(tmp_path, upload_tool):
    model = tmp_path / "model.stl"
    model.write_bytes(b"solid relative")
    route = respx.post("http://test.local/upload").mock(
        return_value=Response(200, json={"ok": True})
    )

    async with httpx.AsyncClient() as client:
        await execute_api_call(
            upload_config(tmp_path), upload_tool, {"file": "model.stl"}, client
        )

    assert b"solid relative" in route.calls.last.request.content


@pytest.mark.asyncio
@respx.mock
async def test_rejects_file_outside_upload_root(tmp_path, upload_tool):
    upload_root = tmp_path / "project"
    upload_root.mkdir()
    outside = tmp_path / "secret"
    outside.write_text("outside root")
    route = respx.post("http://test.local/upload").mock(
        return_value=Response(200, json={"ok": True})
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="outside upload root"):
            await execute_api_call(
                upload_config(upload_root),
                upload_tool,
                {"file": str(outside)},
                client,
            )

    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_rejects_symlink_escaping_upload_root(tmp_path, upload_tool):
    upload_root = tmp_path / "project"
    upload_root.mkdir()
    outside = tmp_path / "secret"
    outside.write_text("outside root")
    link = upload_root / "model.stl"
    link.symlink_to(outside)
    route = respx.post("http://test.local/upload").mock(
        return_value=Response(200, json={"ok": True})
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="outside upload root"):
            await execute_api_call(
                upload_config(upload_root),
                upload_tool,
                {"file": str(link)},
                client,
            )

    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_rejects_upload_when_root_is_not_configured(tmp_path, upload_tool):
    model = tmp_path / "model.stl"
    model.write_bytes(b"solid model")
    route = respx.post("http://test.local/upload").mock(
        return_value=Response(200, json={"ok": True})
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="BAMBUDDY_UPLOAD_ROOT"):
            await execute_api_call(
                upload_config(None), upload_tool, {"file": str(model)}, client
            )

    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_does_not_open_non_file_multipart_fields(tmp_path, upload_tool):
    model = tmp_path / "model.stl"
    model.write_bytes(b"solid model")
    note_path = tmp_path / "note.txt"
    note_path.write_text("must not be uploaded")
    route = respx.post("http://test.local/upload").mock(
        return_value=Response(200, json={"ok": True})
    )

    async with httpx.AsyncClient() as client:
        await execute_api_call(
            upload_config(tmp_path),
            upload_tool,
            {"file": str(model), "note": str(note_path)},
            client,
        )

    request = route.calls.last.request
    assert b"must not be uploaded" not in request.content
    assert str(note_path).encode() in request.content
