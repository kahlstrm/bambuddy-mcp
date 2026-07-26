# Bambuddy MCP Server

An [MCP](https://modelcontextprotocol.io) server that exposes the full [Bambuddy](https://github.com/maziggy/bambuddy) REST API as tools for AI assistants.

This MCP server dynamically generates tools from Bambuddy's OpenAPI spec at startup, giving your AI assistant access to **430+ API endpoints** — without flooding the context window on startup.


## How It Works

On startup, the server fetches the OpenAPI spec from your running Bambuddy instance (`/openapi.json`), parses all 430+ endpoints, and indexes them by category.

By default, only **5 meta-tools** are registered with the AI assistant:

| Meta-tool | Purpose |
|-----------|---------|
| `list_categories` | Browse available API categories |
| `search_tools` | Find tools by keyword and inspect their read/write access |
| `execute_read_tool` | Call a discovered `GET` operation |
| `execute_write_tool` | Call a discovered non-`GET` operation |
| `find_printer` | Find a printer ID by name |

This keeps the context window small while still providing full API coverage. The AI searches for what it needs, inspects the input schema, and executes — all on demand.

When a tool is called, the server makes the corresponding HTTP request to Bambuddy and returns the response. JSON responses are returned as text, while binary responses (e.g. camera snapshots) are returned as native MCP `ImageContent` with base64-encoded data so AI assistants can see, process, and display them directly.

## Example Usage

Once configured, you can ask your AI assistant things like:

- "What printers are connected?"
- "Show me the status of my A1 Mini"
- "List my recent print archives"
- "Add the benchy to the print queue"
- "What filament spools do I have?"
- "Check the print progress"
- "Turn on the chamber light"
- "Show me a camera snapshot from printer X"

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) or [Nix](https://nixos.org/)
- A running [Bambuddy](https://github.com/maziggy/bambuddy) instance

## Installation

```bash
uv pip install bambuddy-mcp
```

Or install from source:

```bash
git clone https://github.com/maziggy/bambuddy-mcp.git
cd bambuddy-mcp
uv sync
```

Or run the reproducible Nix package:

```bash
nix run github:kahlstrm/bambuddy-mcp
```

## Configuration

### Using uvx

```json
{
  "mcpServers": {
    "bambuddy": {
      "command": "uvx",
      "args": ["bambuddy-mcp"],
      "env": {
        "BAMBUDDY_URL": "http://localhost:8000",
        "BAMBUDDY_API_KEY": "your-api-key",
        "BAMBUDDY_CENSOR_ACCESS_CODE": "true",
        "BAMBUDDY_CENSOR_SERIAL": "true",
        "BAMBUDDY_CENSOR_MODEL_FILENAME": "false"
      }
    }
  }
}
```

### Local development

For development or running from source:

```json
{
  "mcpServers": {
    "bambuddy": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/bambuddy-mcp", "python", "-m", "bambuddy_mcp"],
      "env": {
        "BAMBUDDY_URL": "http://localhost:8000",
        "BAMBUDDY_API_KEY": "your-api-key",
        "BAMBUDDY_CENSOR_ACCESS_CODE": "true",
        "BAMBUDDY_CENSOR_SERIAL": "true",
        "BAMBUDDY_CENSOR_MODEL_FILENAME": "false"
      }
    }
  }
}
```

### Using Nix

The flake packages Bambuddy MCP with Python dependencies from its pinned
Nixpkgs input. It does not use `uv.lock`.

```json
{
  "mcpServers": {
    "bambuddy": {
      "command": "nix",
      "args": ["run", "github:kahlstrm/bambuddy-mcp"],
      "env": {
        "BAMBUDDY_URL": "http://localhost:8000",
        "BAMBUDDY_API_KEY": "your-api-key"
      }
    }
  }
}
```

For development, `nix develop` provides Python, the runtime and test
dependencies, pytest, and Ruff. Run `nix flake check` to build the package and
execute the complete test and formatting suite.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BAMBUDDY_URL` | `http://localhost:8000` | Base URL of your Bambuddy instance |
| `BAMBUDDY_API_KEY` | _(empty)_ | API key for authentication (create in Bambuddy Settings) |
| `BAMBUDDY_DIRECT_MODE` | `false` | Set to `true` to expose all 430+ tools directly instead of the meta-tools |
| `BAMBUDDY_CENSOR_ACCESS_CODE` | `true` | Mask `access_code` fields in API responses |
| `BAMBUDDY_CENSOR_SERIAL` | `true` | Mask `serial_number` fields (keeps first 2 + last 2 chars) |
| `BAMBUDDY_CENSOR_MODEL_FILENAME` | `false` | Mask model filenames (`.3mf`, `.gcode`) in API responses and prevent direct base64 image embedding |
| `BAMBUDDY_UPLOAD_ROOT` | Current working directory | Restrict local file uploads to this directory |

> **Note:** By default, the server separates discovered operations between `execute_read_tool` and `execute_write_tool`. The server rejects operations sent through the wrong executor. Set `BAMBUDDY_DIRECT_MODE=true` to expose all 430+ tools directly with per-operation safety annotations (uses significantly more context).

### Local file uploads

Run `bambuddy-mcp` from the project directory containing the files you want to
upload. The current working directory becomes the default upload root. Set
`BAMBUDDY_UPLOAD_ROOT` when an MCP client launches the server from a different
directory.

Only multipart fields declared as binary files in Bambuddy's OpenAPI document
are opened. Relative paths resolve from the upload root, and resolved paths
outside that root—including escaping symlinks—are rejected.
