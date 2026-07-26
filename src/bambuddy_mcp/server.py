"""MCP Server setup and main entry point."""

import asyncio
import json
import sys

import httpx
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import ImageContent, TextContent, Tool, ToolAnnotations

from bambuddy_mcp.camera import StreamTokenCache, get_camera_snapshot
from bambuddy_mcp.config import Config
from bambuddy_mcp.http import build_url, execute_api_call, fetch_openapi_spec
from bambuddy_mcp.openapi import parse_openapi_to_tools
from bambuddy_mcp.search import search_tools

PRINTER_FIELDS = ("id", "name", "model", "ip_address", "is_active")


def _tool_access(tool_def: dict) -> str:
    return tool_def.get(
        "access",
        "read" if tool_def.get("method") == "get" else "write",
    )


def _tool_annotations(tool_def: dict) -> ToolAnnotations:
    is_read = _tool_access(tool_def) == "read"
    return ToolAnnotations(
        readOnlyHint=is_read,
        destructiveHint=not is_read,
        idempotentHint=is_read,
        openWorldHint=True,
    )


def _validate_tool_access(expected_access: str, tool_def: dict) -> None:
    actual_access = _tool_access(tool_def)
    if actual_access == expected_access:
        return

    executor = "execute_read_tool" if actual_access == "read" else "execute_write_tool"
    raise ValueError(
        f"{tool_def['name']} is a {actual_access} operation; use {executor}"
    )


def _execution_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The tool name from search_tools results",
            },
            "arguments": {
                "type": "object",
                "description": "Arguments to pass to the tool",
                "default": {},
            },
            "embed_image": {
                "type": "boolean",
                "description": (
                    "Embed image data in the response instead of saving it to a file"
                ),
                "default": False,
            },
        },
        "required": ["name"],
    }


def _build_proxy_tools(censor_note: str) -> list[Tool]:
    read_annotations = _tool_annotations({"method": "get"})
    write_annotations = _tool_annotations({"method": "post"})
    return [
        Tool(
            name="list_categories",
            description=(
                "List all available tool categories and the total tool count. "
                "Use this first to understand what's available."
            ),
            inputSchema={"type": "object", "properties": {}},
            annotations=read_annotations,
        ),
        Tool(
            name="search_tools",
            description=(
                "Search for tools by keyword. Returns matching tool names, "
                "access classifications, descriptions, and input schemas."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search keyword to match against tool names "
                            "and descriptions"
                        ),
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "Optional category to filter by (from list_categories)"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 10)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
            annotations=read_annotations,
        ),
        Tool(
            name="execute_read_tool",
            description=(
                "Execute a read-only Bambuddy GET operation by name. "
                "Use search_tools first and select an operation with "
                f"access=read.{censor_note}"
            ),
            inputSchema=_execution_input_schema(),
            annotations=read_annotations,
        ),
        Tool(
            name="execute_write_tool",
            description=(
                "Execute a state-changing Bambuddy operation by name. "
                "This may control the printer or delete data. Use search_tools "
                f"first and select an operation with access=write.{censor_note}"
            ),
            inputSchema=_execution_input_schema(),
            annotations=write_annotations,
        ),
        Tool(
            name="find_printer",
            description=(
                "Find a printer by name. Returns printer details including "
                "the printer_id needed by other tools."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Printer name or partial name to search for "
                            "(case-insensitive)"
                        ),
                    },
                },
                "required": ["name"],
            },
            annotations=read_annotations,
        ),
        Tool(
            name="get_camera_snapshot",
            description="Get a current camera snapshot for a printer.",
            inputSchema={
                "type": "object",
                "properties": {
                    "printer_id": {
                        "type": "integer",
                        "description": "Bambuddy printer ID",
                    },
                    "embed_image": {
                        "type": "boolean",
                        "description": (
                            "Embed image data in the response instead of saving "
                            "it to a temporary file"
                        ),
                        "default": True,
                    },
                },
                "required": ["printer_id"],
            },
            annotations=read_annotations,
        ),
    ]


async def _execute_discovered_tool(
    expected_access: str,
    arguments: dict,
    config: Config,
    tool_map: dict,
) -> list[TextContent | ImageContent]:
    tool_name = arguments.get("name", "")
    if tool_name not in tool_map:
        return [
            TextContent(
                type="text",
                text=(
                    f"Unknown tool: {tool_name}. "
                    "Use search_tools to find available tools."
                ),
            )
        ]

    tool_def = tool_map[tool_name]
    try:
        _validate_tool_access(expected_access, tool_def)
    except ValueError as error:
        return [TextContent(type="text", text=str(error))]

    async with httpx.AsyncClient(timeout=30) as client:
        return await execute_api_call(
            config,
            tool_def,
            arguments.get("arguments", {}),
            client,
            embed_image=arguments.get("embed_image", False),
        )


async def _find_printers(
    name_query: str,
    config: Config,
    tool_map: dict,
) -> list[TextContent]:
    """Look up printers by name using the list_printers endpoint."""
    list_tool = tool_map.get("list_printers")
    if list_tool is None:
        return [
            TextContent(
                type="text",
                text=(
                    "The find_printer tool requires a 'list_printers' endpoint "
                    "in the Bambuddy API, but none was found. "
                    "Use search_tools to look for printer-related tools manually."
                ),
            )
        ]

    url, _ = build_url(config.base_url, list_tool["path"], {})
    headers: dict[str, str] = {}
    if config.api_key:
        headers["X-API-Key"] = config.api_key

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers)

    if response.status_code >= 400:
        return [
            TextContent(
                type="text",
                text=f"HTTP {response.status_code} Error fetching printers: {response.text}",
            )
        ]

    printers = response.json()

    # Handle paginated responses wrapped in an envelope
    if isinstance(printers, dict):
        for key in ("data", "items", "results", "printers"):
            if key in printers and isinstance(printers[key], list):
                printers = printers[key]
                break

    if not isinstance(printers, list):
        printers = [printers]

    # Filter by name (case-insensitive substring match)
    query_lower = name_query.lower()
    matches = [
        p
        for p in printers
        if isinstance(p, dict) and query_lower in p.get("name", "").lower()
    ]

    # Project to essential fields only
    results = [
        {field: p[field] for field in PRINTER_FIELDS if field in p} for p in matches
    ]

    output = {
        "query": name_query,
        "total_matches": len(results),
        "printers": results,
    }
    return [TextContent(type="text", text=json.dumps(output, indent=2))]


async def main():
    """Main entry point for the Bambuddy MCP server."""
    config = Config.from_env()
    server = Server("bambuddy")

    async with httpx.AsyncClient() as client:
        try:
            spec = await fetch_openapi_spec(config.base_url, client)
        except Exception as e:
            print(
                f"Error: Could not fetch OpenAPI spec from {config.base_url}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)

    tool_defs = parse_openapi_to_tools(spec)
    tool_map = {t["name"]: t for t in tool_defs}
    stream_token_cache = StreamTokenCache()
    mode = "direct" if config.direct_mode else "proxy"
    print(
        f"Loaded {len(tool_defs)} tools from OpenAPI spec (mode: {mode})",
        file=sys.stderr,
    )

    if config.direct_mode:
        # Direct mode: expose all 430+ tools individually

        @server.list_tools()
        async def list_tools_direct() -> list[Tool]:
            return [
                Tool(
                    name=t["name"],
                    description=t["description"],
                    inputSchema=t["input_schema"],
                    annotations=_tool_annotations(t),
                )
                for t in tool_defs
            ]

        @server.call_tool()
        async def call_tool_direct(
            name: str, arguments: dict
        ) -> list[TextContent | ImageContent]:
            if name not in tool_map:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            args = dict(arguments or {})
            embed_image = args.pop("embed_image", False)
            async with httpx.AsyncClient(timeout=30) as client:
                return await execute_api_call(
                    config,
                    tool_map[name],
                    args,
                    client,
                    embed_image=embed_image,
                )

    else:
        # Proxy mode (default): expose meta-tools for discovery + execution
        censored = []
        if config.censor_access_code:
            censored.append("access_code")
        if config.censor_serial:
            censored.append("serial_number")
        if config.censor_model_filename:
            censored.append("model filenames (.3mf/.gcode)")
        if censored:
            censor_note = (
                f" The Bambuddy MCP server is censoring: {', '.join(censored)}. "
                "Users can disable this in their MCP server config via BAMBUDDY_CENSOR_* env vars."
            )
        else:
            censor_note = ""

        @server.list_tools()
        async def list_tools_proxy() -> list[Tool]:
            return _build_proxy_tools(censor_note)

        @server.call_tool()
        async def call_tool_proxy(
            name: str, arguments: dict
        ) -> list[TextContent | ImageContent]:
            if name == "list_categories":
                tags = sorted({t["tag"] for t in tool_defs if t["tag"]})
                result = {
                    "total_tools": len(tool_defs),
                    "categories": tags,
                }
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            if name == "search_tools":
                query = arguments.get("query", "")
                category = arguments.get("category")
                limit = arguments.get("limit", 10)
                matches = search_tools(tool_defs, query, category, limit)
                results = [
                    {
                        "name": t["name"],
                        "access": _tool_access(t),
                        "description": t["description"],
                        "input_schema": t["input_schema"],
                    }
                    for t in matches
                ]
                return [TextContent(type="text", text=json.dumps(results, indent=2))]

            if name in ("execute_read_tool", "execute_write_tool"):
                expected_access = "read" if name == "execute_read_tool" else "write"
                return await _execute_discovered_tool(
                    expected_access,
                    arguments,
                    config,
                    tool_map,
                )

            if name == "find_printer":
                printer_name = arguments.get("name", "")
                if not printer_name:
                    return [
                        TextContent(
                            type="text",
                            text="The 'name' parameter is required for find_printer.",
                        )
                    ]
                return await _find_printers(printer_name, config, tool_map)

            if name == "get_camera_snapshot":
                printer_id = arguments.get("printer_id")
                if printer_id is None:
                    return [
                        TextContent(
                            type="text",
                            text=(
                                "The 'printer_id' parameter is required for "
                                "get_camera_snapshot."
                            ),
                        )
                    ]
                return await get_camera_snapshot(
                    printer_id,
                    arguments.get("embed_image", True),
                    config,
                    tool_map,
                    stream_token_cache,
                )

            return [TextContent(type="text", text=f"Unknown meta-tool: {name}")]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def run():
    """Sync entry point for console_scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
