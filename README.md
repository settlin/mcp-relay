# mcp-sync

Single source of truth for MCP server configurations across AI editors.

One canonical `~/.config/mcp/servers.json` propagates automatically to:

| Editor | Config location | Schema key |
|---|---|---|
| **Zed** | `~/.config/zed/settings.json` | `context_servers` |
| **Kilo** | `~/.config/kilo/kilo.jsonc` | `mcp` |
| **opencode** | `~/.config/opencode/opencode.jsonc` | `mcp` |
| **VS Code** | `~/Library/Application Support/Code/User/mcp.json` | `servers` |
| **Claude Desktop** | `~/Library/Application Support/Claude/claude_desktop_config.json` | `mcpServers` |
| **Cursor** | `~/.cursor/mcp.json` | `mcpServers` |
| **custom** | any path you register | any key |

A launchd agent (macOS) or systemd path unit (Linux) fires `mcp-sync sync` the moment `servers.json` is saved — zero manual steps after the first `mcp-sync install`.

---

## Installation

### Quick (copy the script)

```sh
curl -fsSL https://raw.githubusercontent.com/s7dhansh/mcp-sync/main/mcp-sync \
  -o ~/.local/bin/mcp-sync && chmod +x ~/.local/bin/mcp-sync
mcp-sync install
```

### From source

```sh
git clone https://github.com/s7dhansh/mcp-sync
cd mcp-sync
cp mcp-sync ~/.local/bin/mcp-sync
chmod +x ~/.local/bin/mcp-sync
mcp-sync install
```

### With pip / uv

```sh
pip install mcp-sync          # installs `mcp-sync` entry point
# or
uv tool install mcp-sync
```

Ensure `~/.local/bin` is in your `PATH`:

```sh
# fish
fish_add_path ~/.local/bin

# bash / zsh
export PATH="$HOME/.local/bin:$PATH"
```

---

## Quick start

```sh
# 1. Create the canonical config (editable template)
mcp-sync init

# 2. Check what was created
mcp-sync list

# 3. Preview what sync would write to each editor
mcp-sync diff

# 4. Apply to all editors
mcp-sync sync

# 5. Install the auto-watch daemon (fire-and-forget from now on)
mcp-sync install
```

---

## Canonical config

`~/.config/mcp/servers.json`

```json
{
  "version": 1,
  "servers": {
    "betterstack": {
      "transport": "remote",
      "url": "https://mcp.betterstack.com"
    },
    "clickup": {
      "transport": "remote",
      "url": "https://mcp.clickup.com/mcp"
    },
    "mongodb": {
      "transport": "local",
      "command": ["pnpm", "dlx", "@mongodb-js/mongodb-mcp-server", "--readonly"],
      "env": {
        "MDB_MCP_CONNECTION_STRING": "mongodb+srv://user:pass@host/db"
      }
    }
  }
}
```

Two transport types:

| Field | Description |
|---|---|
| `transport: "remote"` | HTTP/SSE MCP server; only `url` needed |
| `transport: "local"` | Subprocess MCP server; `command` array + optional `env` map |

---

## Commands

### `mcp-sync init`

Create `~/.config/mcp/servers.json` from a built-in template.

```sh
mcp-sync init           # safe — won't overwrite existing
mcp-sync init --force   # overwrite
```

---

### `mcp-sync sync`

Propagate canonical config to all active editor targets.

```sh
mcp-sync sync                   # all editors
mcp-sync sync --editor zed      # only Zed
mcp-sync sync --dry-run         # preview without writing
mcp-sync sync -n                # shorthand for --dry-run
```

The sync is **surgical**: only the canonical server entries are rewritten inside each editor's existing config. Other keys (model settings, keymaps, permissions, etc.) are left untouched. Comments outside the managed block are preserved.

---

### `mcp-sync status`

Show which servers are synced (present) and which are missing in each editor.

```sh
mcp-sync status
```

```
Canonical : /Users/you/.config/mcp/servers.json
Servers   : betterstack, clickup, mongodb

  Editor          Status      Present                           Missing
  --------------------------------------------------------------------------
  zed             ok          betterstack, clickup, mongodb
  kilo            ok          betterstack, clickup, mongodb
  opencode        ok          betterstack, clickup, mongodb
  vscode          missing     betterstack                       clickup
  claude-desktop  not found
```

---

### `mcp-sync diff`

Show a unified diff of exactly what `sync` would change in each editor.

```sh
mcp-sync diff
```

---

### `mcp-sync list`

List all servers in the canonical config.

```sh
mcp-sync list
```

```
  betterstack         remote  https://mcp.betterstack.com
  clickup             remote  https://mcp.clickup.com/mcp
  mongodb             local   pnpm dlx @mongodb-js/mongodb-mcp-server --readonly
                              MDB_MCP_CONNECTION_STRING=mongodb+srv://...
```

---

### `mcp-sync add`

Add or update a server in canonical config, then sync all editors.

```sh
# Remote server (HTTP/SSE)
mcp-sync add betterstack --remote https://mcp.betterstack.com
mcp-sync add clickup     --remote https://mcp.clickup.com/mcp

# Local server (subprocess)
mcp-sync add mongodb \
  --command "pnpm dlx @mongodb-js/mongodb-mcp-server --readonly" \
  --env MDB_MCP_CONNECTION_STRING=mongodb+srv://user:pass@host/db

# Local server with separate --arg flags
mcp-sync add myserver \
  --command pnpm \
  --arg dlx \
  --arg my-mcp-package \
  --arg --flag

# Overwrite an existing entry
mcp-sync add betterstack --remote https://mcp.betterstack.com --force

# Add without syncing immediately
mcp-sync add newserver --remote https://new.example.com --no-sync
```

---

### `mcp-sync remove`

Remove a server from canonical config (editor configs are not modified until the next sync).

```sh
mcp-sync remove betterstack
```

---

### `mcp-sync edit`

Open the canonical config in `$EDITOR`.

```sh
mcp-sync edit          # uses $EDITOR (falls back to vi)
EDITOR=nano mcp-sync edit
```

After saving, run `mcp-sync sync` — or let the daemon do it if `mcp-sync install` has been run.

---

### `mcp-sync targets`

Show all known editor targets, whether they are active, and where their config lives.

```sh
mcp-sync targets
```

```
  Name            On    Path
  ----------------------------------------------------------------------
  zed             ✓     /Users/you/.config/zed/settings.json (exists)
  kilo            ✓     /Users/you/.config/kilo/kilo.jsonc (exists)
  opencode        ✓     /Users/you/.config/opencode/opencode.jsonc (exists)
  vscode          ✓     /Users/you/Library/Application Support/Code/User/mcp.json (exists)  [only: betterstack, clickup]
  claude-desktop  ✗     /Users/you/Library/Application Support/Claude/claude_desktop_config.json (not found)
  cursor          ✗     /Users/you/.cursor/mcp.json (not found)
```

Targets marked `✗` are auto-enabled the moment their config file appears on disk.

---

### `mcp-sync install`

Install `mcp-sync` to `~/.local/bin` and set up the auto-watch daemon.

```sh
mcp-sync install
```

What it does:

1. Copies the script to `~/.local/bin/mcp-sync` (skips if already there)
2. Creates `~/.config/mcp/servers.json` if it doesn't exist
3. **macOS** — writes and loads a launchd `WatchPaths` agent that fires on every save of `servers.json`
4. **Linux** — writes and enables a systemd user path unit + service
5. Prints a `PATH` hint if `~/.local/bin` is not in `$PATH`

After `install`, editing `servers.json` (or running `mcp-sync add/remove/edit`) automatically propagates changes — no cron, no polling.

Logs are written to `~/.local/state/mcp-sync.log`.

---

### `mcp-sync uninstall`

Remove the auto-watch daemon.

```sh
mcp-sync uninstall                  # removes daemon + binary
mcp-sync uninstall --keep-binary    # removes daemon only
```

---

### `mcp-sync logs`

Tail the sync log.

```sh
mcp-sync logs           # last 40 lines, then follow
mcp-sync logs -n 100    # last 100 lines
```

---

## Adding a custom editor

Create `~/.config/mcp/targets.json`:

```json
{
  "targets": [
    {
      "name": "my-editor",
      "path": "~/.config/my-editor/config.json",
      "parent_key": "mcpServers",
      "adapter": "claude"
    }
  ]
}
```

Available adapters:

| Adapter | Format | Used by |
|---|---|---|
| `zed` | `{enabled, command/url, args, env}` | Zed |
| `kilo_opencode` | `{type, command/url, environment}` | Kilo, opencode |
| `vscode` | `{transport, url}` / `{command, args, env}` | VS Code |
| `claude` | `{url}` / `{command, args, env}` | Claude Desktop, Cursor |

Custom targets take effect immediately without restarting the daemon.

---

## Limiting sync scope per target

If an editor manages some MCP servers itself (e.g. the VS Code MongoDB extension), you can restrict which canonical servers get written to that editor via `only_servers`:

```json
{
  "targets": [
    {
      "name": "vscode",
      "path": "~/Library/Application Support/Code/User/mcp.json",
      "parent_key": "servers",
      "adapter": "vscode",
      "only_servers": ["betterstack", "clickup"]
    }
  ]
}
```

---

## How it works

```
servers.json  ──saved──▶  launchd / systemd
                                │
                          mcp-sync sync
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
    Zed settings.json   kilo.jsonc         vscode/mcp.json
    (context_servers)    (mcp)              (servers)
              │
              ▼
    opencode.jsonc  claude_desktop_config.json  cursor/mcp.json
```

The sync is **purely additive and surgical**:
- Each editor's file is read as raw text (JSONC-aware)
- Only the entries for canonical servers are replaced or inserted
- All other keys, comments, and formatting are preserved

---

## Development

```sh
git clone https://github.com/s7dhansh/mcp-sync
cd mcp-sync
pip install -e ".[dev]"
# or with uv:
uv sync --group dev

pytest tests/ -v
pytest tests/ -v --cov=. --cov-report=term-missing
```

---

## License

MIT © [Sudhanshu Raheja](https://github.com/s7dhansh)
