"""Tests for MCP tool exposure and access boundaries."""

import pytest
import respx
from httpx import Response

from bambuddy_mcp import server


@pytest.fixture
def read_tool():
    return {"name": "get_status", "method": "get", "access": "read"}


@pytest.fixture
def write_tool():
    return {"name": "start_print", "method": "post", "access": "write"}


def test_proxy_tools_separate_read_and_write_execution():
    tools = {tool.name: tool for tool in server._build_proxy_tools("")}

    assert "execute_tool" not in tools
    assert "execute_read_tool" in tools
    assert "execute_write_tool" in tools


def test_read_executor_annotations_are_read_only():
    tools = {tool.name: tool for tool in server._build_proxy_tools("")}
    annotations = tools["execute_read_tool"].annotations

    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is True


def test_write_executor_annotations_are_conservative():
    tools = {tool.name: tool for tool in server._build_proxy_tools("")}
    annotations = tools["execute_write_tool"].annotations

    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is True
    assert annotations.idempotentHint is False


def test_discovery_tools_are_read_only():
    tools = {tool.name: tool for tool in server._build_proxy_tools("")}

    for name in ("list_categories", "search_tools", "find_printer"):
        assert tools[name].annotations.readOnlyHint is True
        assert tools[name].annotations.destructiveHint is False


def test_direct_tool_annotations_follow_access(read_tool, write_tool):
    assert server._tool_annotations(read_tool).readOnlyHint is True
    assert server._tool_annotations(read_tool).destructiveHint is False
    assert server._tool_annotations(write_tool).readOnlyHint is False
    assert server._tool_annotations(write_tool).destructiveHint is True


def test_read_executor_rejects_write_operation(write_tool):
    with pytest.raises(
        ValueError,
        match="write operation.*execute_write_tool",
    ):
        server._validate_tool_access("read", write_tool)


def test_write_executor_rejects_read_operation(read_tool):
    with pytest.raises(
        ValueError,
        match="read operation.*execute_read_tool",
    ):
        server._validate_tool_access("write", read_tool)


def test_matching_executor_accepts_operation(read_tool, write_tool):
    server._validate_tool_access("read", read_tool)
    server._validate_tool_access("write", write_tool)


@pytest.mark.asyncio
@respx.mock
async def test_mismatched_executor_does_not_call_bambuddy(config):
    write_tool = {
        "name": "start_print",
        "path": "/start",
        "method": "post",
        "access": "write",
        "query_params": set(),
        "has_file_upload": False,
    }
    route = respx.post("http://test.local:8000/start").mock(
        return_value=Response(200, json={"ok": True})
    )

    result = await server._execute_discovered_tool(
        "read",
        {"name": "start_print", "arguments": {}},
        config,
        {"start_print": write_tool},
    )

    assert "write operation" in result[0].text
    assert "execute_write_tool" in result[0].text
    assert not route.called
