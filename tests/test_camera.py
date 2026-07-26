"""Tests for safe camera snapshot access."""

import pytest
import respx
from httpx import Response

from bambuddy_mcp.camera import StreamTokenCache, get_camera_snapshot


@pytest.fixture
def camera_tools():
    return {
        "create_stream_token": {
            "name": "create_stream_token",
            "path": "/api/v1/printers/camera/stream-token",
            "method": "post",
            "query_params": set(),
            "has_file_upload": False,
        },
        "raw_camera_snapshot": {
            "name": "raw_camera_snapshot",
            "path": "/api/v1/printers/{printer_id}/camera/snapshot",
            "method": "get",
            "query_params": {"token"},
            "has_file_upload": False,
        },
    }


def mock_token_route(*tokens):
    return respx.post(
        "http://test.local:8000/api/v1/printers/camera/stream-token"
    ).mock(side_effect=[Response(200, json={"token": token}) for token in tokens])


def mock_snapshot_route(*responses):
    return respx.get("http://test.local:8000/api/v1/printers/7/camera/snapshot").mock(
        side_effect=list(responses)
    )


def jpeg_response():
    return Response(
        200,
        content=b"jpeg",
        headers={"content-type": "image/jpeg"},
    )


@pytest.mark.asyncio
@respx.mock
async def test_snapshot_reuses_token_for_sixty_minutes(config, camera_tools):
    now = [1_000.0]
    token_route = mock_token_route("first", "second")
    snapshot_route = mock_snapshot_route(
        jpeg_response(),
        jpeg_response(),
        jpeg_response(),
    )
    cache = StreamTokenCache(clock=lambda: now[0])

    first = await get_camera_snapshot(7, True, config, camera_tools, cache)
    now[0] += 3_599
    second = await get_camera_snapshot(7, True, config, camera_tools, cache)
    now[0] += 1
    third = await get_camera_snapshot(7, True, config, camera_tools, cache)

    assert first[0].data == second[0].data == third[0].data
    assert token_route.call_count == 2
    assert snapshot_route.call_count == 3
    assert snapshot_route.calls[0].request.url.params["token"] == "first"
    assert snapshot_route.calls[1].request.url.params["token"] == "first"
    assert snapshot_route.calls[2].request.url.params["token"] == "second"
    assert "first" not in repr(first)


@pytest.mark.asyncio
@respx.mock
async def test_snapshot_refreshes_token_once_after_unauthorized(config, camera_tools):
    token_route = mock_token_route("stale", "fresh")
    snapshot_route = mock_snapshot_route(
        Response(401, json={"detail": "Unauthorized"}),
        jpeg_response(),
    )

    result = await get_camera_snapshot(
        7, True, config, camera_tools, StreamTokenCache()
    )

    assert result[0].type == "image"
    assert token_route.call_count == 2
    assert snapshot_route.call_count == 2
    assert snapshot_route.calls[1].request.url.params["token"] == "fresh"


@pytest.mark.asyncio
@respx.mock
async def test_snapshot_retries_only_once(config, camera_tools):
    token_route = mock_token_route("first", "second")
    snapshot_route = mock_snapshot_route(
        Response(401, json={"detail": "Unauthorized"}),
        Response(401, json={"detail": "Unauthorized"}),
    )

    result = await get_camera_snapshot(
        7, True, config, camera_tools, StreamTokenCache()
    )

    assert result[0].text.startswith("HTTP 401 Error:")
    assert token_route.call_count == 2
    assert snapshot_route.call_count == 2


@pytest.mark.asyncio
async def test_snapshot_reports_missing_api_operations(config):
    result = await get_camera_snapshot(7, True, config, {}, StreamTokenCache())

    assert "requires Bambuddy camera token and snapshot endpoints" in result[0].text
