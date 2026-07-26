"""Safe camera snapshot access."""

import asyncio
import time
from collections.abc import Callable

import httpx
from mcp.types import ImageContent, TextContent

from bambuddy_mcp.config import Config
from bambuddy_mcp.http import build_url, execute_api_call

STREAM_TOKEN_PATH = "/api/v1/printers/camera/stream-token"
SNAPSHOT_PATH = "/api/v1/printers/{printer_id}/camera/snapshot"
STREAM_TOKEN_TTL_SECONDS = 60 * 60


class StreamTokenError(Exception):
    """Raised when Bambuddy cannot provide a camera stream token."""


class StreamTokenCache:
    """Keep one short-lived camera token in process memory."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get(
        self,
        config: Config,
        token_tool: dict,
        client: httpx.AsyncClient,
    ) -> str:
        if self._token is not None and self._clock() < self._expires_at:
            return self._token

        async with self._lock:
            if self._token is not None and self._clock() < self._expires_at:
                return self._token

            token = await _create_stream_token(config, token_tool, client)
            self._token = token
            self._expires_at = self._clock() + STREAM_TOKEN_TTL_SECONDS
            return token

    async def invalidate(self, token: str) -> None:
        async with self._lock:
            if self._token == token:
                self._token = None
                self._expires_at = 0.0


def _find_operation(tool_map: dict, method: str, path: str) -> dict | None:
    return next(
        (
            tool
            for tool in tool_map.values()
            if tool.get("method") == method and tool.get("path") == path
        ),
        None,
    )


async def _create_stream_token(
    config: Config,
    token_tool: dict,
    client: httpx.AsyncClient,
) -> str:
    url, _ = build_url(config.base_url, token_tool["path"], {})
    headers = {"X-API-Key": config.api_key} if config.api_key else {}
    response = await client.post(url, headers=headers)

    if response.status_code >= 400:
        raise StreamTokenError(f"HTTP {response.status_code}")

    try:
        token = response.json()["token"]
    except (KeyError, TypeError, ValueError) as error:
        raise StreamTokenError("response did not contain a token") from error
    if not isinstance(token, str) or not token:
        raise StreamTokenError("response did not contain a token")
    return token


def _is_unauthorized(result: list[TextContent | ImageContent]) -> bool:
    return (
        len(result) == 1
        and isinstance(result[0], TextContent)
        and result[0].text.startswith("HTTP 401 Error:")
    )


async def get_camera_snapshot(
    printer_id: int,
    embed_image: bool,
    config: Config,
    tool_map: dict,
    token_cache: StreamTokenCache,
) -> list[TextContent | ImageContent]:
    """Fetch a snapshot without exposing the camera stream token."""
    token_tool = _find_operation(tool_map, "post", STREAM_TOKEN_PATH)
    snapshot_tool = _find_operation(tool_map, "get", SNAPSHOT_PATH)
    if token_tool is None or snapshot_tool is None:
        return [
            TextContent(
                type="text",
                text=(
                    "The get_camera_snapshot helper requires Bambuddy camera "
                    "token and snapshot endpoints, but they were not found."
                ),
            )
        ]

    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(2):
            try:
                token = await token_cache.get(config, token_tool, client)
            except (httpx.HTTPError, StreamTokenError) as error:
                return [
                    TextContent(
                        type="text",
                        text=f"Could not create camera stream token: {error}",
                    )
                ]

            result = await execute_api_call(
                config,
                snapshot_tool,
                {"printer_id": printer_id, "token": token},
                client,
                embed_image=embed_image,
            )
            if not _is_unauthorized(result) or attempt == 1:
                return result
            await token_cache.invalidate(token)

    raise AssertionError("camera snapshot retry loop did not return")
