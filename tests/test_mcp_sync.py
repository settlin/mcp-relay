"""
Tests for mcp-sync.

Run with:
    pytest tests/
    pytest tests/ -v
    pytest tests/ -k test_sync
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ── Make the repo root importable as a module ─────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# We import the script directly (it lives without a .py extension; load via importlib)
import importlib.util

import importlib.machinery

_loader = importlib.machinery.SourceFileLoader("mcp_sync", str(ROOT / "mcp-sync"))
_spec = importlib.util.spec_from_loader("mcp_sync", _loader)
assert _spec is not None, "Could not load mcp-sync script"
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

find_key_block = _mod.find_key_block
_splice_server = _mod._splice_server
_adapt_zed = _mod._adapt_zed
_adapt_kilo_opencode = _mod._adapt_kilo_opencode
_adapt_vscode = _mod._adapt_vscode
_adapt_claude = _mod._adapt_claude


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

REMOTE_SERVER = {"transport": "remote", "url": "https://mcp.example.com"}
LOCAL_SERVER = {
    "transport": "local",
    "command": ["pnpm", "dlx", "my-mcp-server", "--readonly"],
    "env": {"API_KEY": "secret", "DB": "prod"},
}
LOCAL_SERVER_NO_ENV = {
    "transport": "local",
    "command": ["npx", "-y", "@scope/server"],
}

CANONICAL_SERVERS = {
    "betterstack": {"transport": "remote", "url": "https://mcp.betterstack.com"},
    "clickup": {"transport": "remote", "url": "https://mcp.clickup.com/mcp"},
    "mongodb": {
        "transport": "local",
        "command": ["pnpm", "dlx", "@mongodb-js/mongodb-mcp-server", "--readonly"],
        "env": {"MDB_MCP_CONNECTION_STRING": "mongodb+srv://user:pass@host/db"},
    },
}


@pytest.fixture
def canonical_dir(tmp_path: Path) -> Path:
    cfg = tmp_path / ".config" / "mcp"
    cfg.mkdir(parents=True)
    data = {"version": 1, "servers": CANONICAL_SERVERS}
    (cfg / "servers.json").write_text(json.dumps(data, indent=2))
    return cfg


@pytest.fixture(autouse=True)
def patch_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all module-level path constants to tmp_path so tests never touch real configs."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(_mod, "HOME", home)
    cfg_dir = home / ".config" / "mcp"
    cfg_dir.mkdir(parents=True)
    monkeypatch.setattr(_mod, "CONFIG_DIR", cfg_dir)
    canonical = cfg_dir / "servers.json"
    monkeypatch.setattr(_mod, "CANONICAL", canonical)
    monkeypatch.setattr(_mod, "CUSTOM_TARGETS_FILE", cfg_dir / "targets.json")
    log_dir = home / ".local" / "state"
    log_dir.mkdir(parents=True)
    monkeypatch.setattr(_mod, "LOG_FILE", log_dir / "mcp-sync.log")
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    monkeypatch.setattr(_mod, "BIN_PATH", bin_dir / "mcp-sync")


def _write_canonical(tmp_path: Path, servers: dict | None = None) -> Path:
    """Write a canonical servers.json into the patched location and return the path."""
    canonical: Path = _mod.CANONICAL
    data = {"version": 1, "servers": servers if servers is not None else CANONICAL_SERVERS}
    canonical.write_text(json.dumps(data, indent=2))
    return canonical


def _make_editor_config(content: str, tmp_path: Path, name: str = "settings.json") -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


# ══════════════════════════════════════════════════════════════════════════════
# find_key_block
# ══════════════════════════════════════════════════════════════════════════════


class TestFindKeyBlock:
    def test_simple_json(self) -> None:
        text = '{"foo": {"a": 1, "b": 2}, "bar": 3}'
        span = find_key_block(text, "foo")
        assert span is not None
        assert text[span[0] : span[1]] == '"foo": {"a": 1, "b": 2}'

    def test_nested_braces(self) -> None:
        text = '{"outer": {"inner": {"deep": 1}}}'
        span = find_key_block(text, "outer")
        assert span is not None
        assert text[span[0] : span[1]] == '"outer": {"inner": {"deep": 1}}'

    def test_missing_key(self) -> None:
        text = '{"foo": {"a": 1}}'
        assert find_key_block(text, "missing") is None

    def test_brace_in_string_ignored(self) -> None:
        text = '{"context_servers": {"name": "a { b }"}}'
        span = find_key_block(text, "context_servers")
        assert span is not None
        assert text[span[0] : span[1]] == '"context_servers": {"name": "a { b }"}'

    def test_line_comment_brace_ignored(self) -> None:
        text = '{\n  "mcp": {\n    // { fake\n    "k": 1\n  }\n}'
        span = find_key_block(text, "mcp")
        assert span is not None
        block = text[span[0] : span[1]]
        assert block.endswith("}")
        assert "fake" in block  # comment is inside the span but depth is correct

    def test_block_comment_brace_ignored(self) -> None:
        text = '{"k": {/* { */ "v": 1}}'
        span = find_key_block(text, "k")
        assert span is not None

    def test_escaped_quote_in_string(self) -> None:
        text = '{"key": {"val": "he said \\"hello\\""} }'
        span = find_key_block(text, "key")
        assert span is not None


# ══════════════════════════════════════════════════════════════════════════════
# _splice_server
# ══════════════════════════════════════════════════════════════════════════════


class TestSpliceServer:
    def test_replaces_existing(self) -> None:
        block = '{"servers": {"old": {"url": "http://old"}}}'
        result = _splice_server(block, "old", '{"url": "http://new"}')
        assert '"http://new"' in result
        assert '"http://old"' not in result

    def test_inserts_new(self) -> None:
        block = '{"servers": {"existing": {"url": "http://a"}}}'
        result = _splice_server(block, "newserver", '{"url": "http://b"}')
        assert '"newserver"' in result
        assert '"existing"' in result

    def test_empty_block(self) -> None:
        block = '{"servers": {}}'
        result = _splice_server(block, "first", '{"url": "http://x"}')
        assert '"first"' in result

    def test_idempotent(self) -> None:
        block = '{"servers": {"s": {"url": "http://x"}}}'
        r1 = _splice_server(block, "s", '{"url": "http://x"}')
        r2 = _splice_server(r1, "s", '{"url": "http://x"}')
        assert r1 == r2


# ══════════════════════════════════════════════════════════════════════════════
# Adapters
# ══════════════════════════════════════════════════════════════════════════════


class TestAdaptZed:
    def test_remote(self) -> None:
        out = json.loads(_adapt_zed(REMOTE_SERVER))
        assert out["enabled"] is True
        assert out["url"] == REMOTE_SERVER["url"]
        assert "command" not in out

    def test_local_with_env(self) -> None:
        out = json.loads(_adapt_zed(LOCAL_SERVER))
        assert out["enabled"] is True
        assert out["command"] == "pnpm"
        assert out["args"] == ["dlx", "my-mcp-server", "--readonly"]
        assert out["env"] == {"API_KEY": "secret", "DB": "prod"}

    def test_local_no_env(self) -> None:
        out = json.loads(_adapt_zed(LOCAL_SERVER_NO_ENV))
        assert "env" not in out


class TestAdaptKiloOpencode:
    def test_remote(self) -> None:
        out = json.loads(_adapt_kilo_opencode(REMOTE_SERVER))
        assert out["type"] == "remote"
        assert out["url"] == REMOTE_SERVER["url"]

    def test_local_with_env(self) -> None:
        out = json.loads(_adapt_kilo_opencode(LOCAL_SERVER))
        assert out["type"] == "local"
        assert out["command"] == LOCAL_SERVER["command"]
        assert out["environment"] == LOCAL_SERVER["env"]

    def test_local_no_env(self) -> None:
        out = json.loads(_adapt_kilo_opencode(LOCAL_SERVER_NO_ENV))
        assert "environment" not in out


class TestAdaptVSCode:
    def test_remote(self) -> None:
        out = json.loads(_adapt_vscode(REMOTE_SERVER))
        assert out["transport"] == "streamable-http"
        assert out["url"] == REMOTE_SERVER["url"]

    def test_local_with_env(self) -> None:
        out = json.loads(_adapt_vscode(LOCAL_SERVER))
        assert "transport" not in out
        assert out["command"] == "pnpm"
        assert out["args"] == ["dlx", "my-mcp-server", "--readonly"]
        assert out["env"] == LOCAL_SERVER["env"]


class TestAdaptClaude:
    def test_remote(self) -> None:
        out = json.loads(_adapt_claude(REMOTE_SERVER))
        assert out["url"] == REMOTE_SERVER["url"]
        assert "transport" not in out

    def test_local(self) -> None:
        out = json.loads(_adapt_claude(LOCAL_SERVER))
        assert out["command"] == "pnpm"
        assert out["args"] == ["dlx", "my-mcp-server", "--readonly"]


# ══════════════════════════════════════════════════════════════════════════════
# cmd_init
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdInit:
    def _run(self, force: bool = False) -> None:
        class A:
            pass
        a = A()
        a.force = force
        _mod.cmd_init(a)

    def test_creates_file(self) -> None:
        assert not _mod.CANONICAL.exists()
        self._run()
        assert _mod.CANONICAL.exists()
        data = json.loads(_mod.CANONICAL.read_text())
        assert "servers" in data
        assert data["version"] == 1

    def test_does_not_overwrite_without_force(self) -> None:
        _mod.CANONICAL.write_text(json.dumps({"servers": {"custom": {}}}))
        self._run(force=False)
        data = json.loads(_mod.CANONICAL.read_text())
        assert "custom" in data["servers"]

    def test_overwrites_with_force(self) -> None:
        _mod.CANONICAL.write_text(json.dumps({"servers": {"custom": {}}}))
        self._run(force=True)
        data = json.loads(_mod.CANONICAL.read_text())
        assert "betterstack" in data["servers"]


# ══════════════════════════════════════════════════════════════════════════════
# cmd_add / cmd_remove / cmd_list
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdAddRemove:
    def setup_method(self) -> None:
        _write_canonical(_mod.CANONICAL.parent)

    def _add(self, name: str, **kwargs) -> None:
        class A:
            force = False
            no_sync = True
            remote = None
            command = None
            arg = None
            env = None
        a = A()
        a.name = name
        for k, v in kwargs.items():
            setattr(a, k, v)
        _mod.cmd_add(a)

    def test_add_remote(self) -> None:
        self._add("newremote", remote="https://mcp.new.com")
        data = json.loads(_mod.CANONICAL.read_text())
        assert data["servers"]["newremote"]["transport"] == "remote"
        assert data["servers"]["newremote"]["url"] == "https://mcp.new.com"

    def test_add_local(self) -> None:
        self._add("newlocal", command="node server.js", env=["FOO=bar"])
        data = json.loads(_mod.CANONICAL.read_text())
        srv = data["servers"]["newlocal"]
        assert srv["transport"] == "local"
        assert srv["command"] == ["node", "server.js"]
        assert srv["env"]["FOO"] == "bar"

    def test_add_local_extra_args(self) -> None:
        self._add("localargs", command="pnpm", arg=["dlx", "server", "--flag"])
        data = json.loads(_mod.CANONICAL.read_text())
        assert data["servers"]["localargs"]["command"] == ["pnpm", "dlx", "server", "--flag"]

    def test_add_duplicate_raises(self) -> None:
        with pytest.raises(SystemExit):
            self._add("betterstack", remote="https://other.com")

    def test_add_duplicate_with_force(self) -> None:
        self._add("betterstack", remote="https://replaced.com", force=True)
        data = json.loads(_mod.CANONICAL.read_text())
        assert data["servers"]["betterstack"]["url"] == "https://replaced.com"

    def test_remove_existing(self) -> None:
        class A:
            name = "clickup"
        _mod.cmd_remove(A())
        data = json.loads(_mod.CANONICAL.read_text())
        assert "clickup" not in data["servers"]

    def test_remove_missing_raises(self) -> None:
        class A:
            name = "doesnotexist"
        with pytest.raises(SystemExit):
            _mod.cmd_remove(A())

    def test_add_local_requires_command(self) -> None:
        with pytest.raises(SystemExit):
            self._add("bad", command=None)


# ══════════════════════════════════════════════════════════════════════════════
# cmd_sync / _sync_one
# ══════════════════════════════════════════════════════════════════════════════


class TestSyncOne:
    """Lower-level _sync_one tests using in-memory editor configs."""

    def _target(self, path: Path, adapter: str = "kilo_opencode", key: str = "mcp") -> dict:
        return {
            "name": "test-editor",
            "path": str(path),
            "parent_key": key,
            "adapter": adapter,
            "enabled": True,
        }

    def test_remote_server_injected(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.json"
        cfg.write_text('{"mcp": {"other": {"type": "remote", "url": "http://other"}}}')
        servers = {"betterstack": {"transport": "remote", "url": "https://mcp.betterstack.com"}}
        changed, _ = _mod._sync_one(self._target(cfg), servers)
        assert changed
        data = json.loads(cfg.read_text())
        # raw text – adapter output may not be JSON-parseable without knowing structure,
        # but we can assert the key is present in the file
        assert "betterstack" in cfg.read_text()

    def test_local_server_injected(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.json"
        cfg.write_text('{"mcp": {}}')
        servers = {
            "mongodb": {
                "transport": "local",
                "command": ["pnpm", "dlx", "mongodb-mcp-server"],
                "env": {"KEY": "val"},
            }
        }
        changed, _ = _mod._sync_one(self._target(cfg), servers)
        assert changed
        assert "mongodb" in cfg.read_text()
        assert "KEY" in cfg.read_text()

    def test_already_up_to_date_no_change(self, tmp_path: Path) -> None:
        """Running sync twice should mark the second run as no-change."""
        cfg = tmp_path / "settings.json"
        cfg.write_text('{"mcp": {}}')
        servers = {"bs": {"transport": "remote", "url": "https://a.com"}}
        _mod._sync_one(self._target(cfg), servers)
        _, msg2 = _mod._sync_one(self._target(cfg), servers)
        assert "up-to-date" in msg2

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.json"
        original = '{"mcp": {}}'
        cfg.write_text(original)
        servers = {"new": {"transport": "remote", "url": "https://x.com"}}
        _mod._sync_one(self._target(cfg), servers, dry_run=True)
        assert cfg.read_text() == original

    def test_missing_editor_config_skipped(self, tmp_path: Path) -> None:
        cfg = tmp_path / "nonexistent.json"
        servers = {"x": {"transport": "remote", "url": "https://x.com"}}
        changed, msg = _mod._sync_one(self._target(cfg), servers)
        assert not changed
        assert "not found" in msg

    def test_only_servers_filter(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.json"
        cfg.write_text('{"mcp": {}}')
        servers = {
            "a": {"transport": "remote", "url": "https://a.com"},
            "b": {"transport": "remote", "url": "https://b.com"},
        }
        target = self._target(cfg)
        target["only_servers"] = ["a"]
        _mod._sync_one(target, servers)
        text = cfg.read_text()
        assert "a.com" in text
        assert "b.com" not in text

    def test_zed_adapter_format(self, tmp_path: Path) -> None:
        cfg = tmp_path / "zed.json"
        cfg.write_text('{"context_servers": {}}')
        servers = {"bs": {"transport": "remote", "url": "https://mcp.betterstack.com"}}
        target = {
            "name": "zed",
            "path": str(cfg),
            "parent_key": "context_servers",
            "adapter": "zed",
            "enabled": True,
        }
        _mod._sync_one(target, servers)
        text = cfg.read_text()
        assert '"enabled"' in text
        assert "betterstack.com" in text

    def test_vscode_adapter_format(self, tmp_path: Path) -> None:
        cfg = tmp_path / "mcp.json"
        cfg.write_text('{"servers": {}}')
        servers = {"cu": {"transport": "remote", "url": "https://mcp.clickup.com/mcp"}}
        target = {
            "name": "vscode",
            "path": str(cfg),
            "parent_key": "servers",
            "adapter": "vscode",
            "enabled": True,
        }
        _mod._sync_one(target, servers)
        text = cfg.read_text()
        assert "streamable-http" in text

    def test_parent_key_missing_creates_it(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.json"
        cfg.write_text('{"other_key": 1}')
        servers = {"s": {"transport": "remote", "url": "https://s.com"}}
        changed, _ = _mod._sync_one(self._target(cfg), servers)
        assert changed
        assert '"mcp"' in cfg.read_text()

    def test_preserves_comments_outside_block(self, tmp_path: Path) -> None:
        cfg = tmp_path / "settings.jsonc"
        original = '// top comment\n{"mcp": {}\n// bottom comment\n}'
        cfg.write_text(original)
        servers = {"s": {"transport": "remote", "url": "https://s.com"}}
        _mod._sync_one(self._target(cfg), servers)
        result = cfg.read_text()
        assert "// top comment" in result
        assert "// bottom comment" in result

    def test_follows_symlink(self, tmp_path: Path) -> None:
        real = tmp_path / "real.json"
        real.write_text('{"mcp": {}}')
        link = tmp_path / "link.json"
        link.symlink_to(real)
        servers = {"s": {"transport": "remote", "url": "https://s.com"}}
        changed, _ = _mod._sync_one(self._target(link), servers)
        assert changed
        assert "s.com" in real.read_text()  # real file updated, not just the link


# ══════════════════════════════════════════════════════════════════════════════
# cmd_sync (full integration via argparse namespace)
# ══════════════════════════════════════════════════════════════════════════════


class TestCmdSync:
    def setup_method(self) -> None:
        _write_canonical(None)  # uses patched CANONICAL

    class _Args:
        dry_run = False
        editor = "all"

    def test_no_active_targets_does_not_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_mod, "BUILTIN_TARGETS", [])
        monkeypatch.setattr(_mod, "CUSTOM_TARGETS_FILE", _mod.CANONICAL.parent / "notexist.json")
        _mod.cmd_sync(self._Args())

    def test_bad_editor_name_exits(self) -> None:
        class A:
            dry_run = False
            editor = "nonexistent-editor-xyz"
        with pytest.raises(SystemExit):
            _mod.cmd_sync(A())


# ══════════════════════════════════════════════════════════════════════════════
# load_canonical — error paths
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadCanonical:
    def test_missing_file_exits(self) -> None:
        assert not _mod.CANONICAL.exists()
        with pytest.raises(SystemExit):
            _mod.load_canonical()

    def test_valid_file_returns_dict(self) -> None:
        _write_canonical(None)
        data = _mod.load_canonical()
        assert "servers" in data


# ══════════════════════════════════════════════════════════════════════════════
# load_targets — custom targets file
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadTargets:
    def test_builtin_targets_loaded(self) -> None:
        targets = _mod.load_targets()
        names = [t["name"] for t in targets]
        assert "zed" in names
        assert "kilo" in names

    def test_custom_targets_merged(self, tmp_path: Path) -> None:
        custom = [
            {
                "name": "myeditor",
                "path": str(tmp_path / "myeditor.json"),
                "parent_key": "mcpServers",
                "adapter": "claude",
            }
        ]
        _mod.CUSTOM_TARGETS_FILE.write_text(json.dumps({"targets": custom}))
        targets = _mod.load_targets()
        names = [t["name"] for t in targets]
        assert "myeditor" in names

    def test_disabled_target_auto_enabled_when_file_exists(self, tmp_path: Path) -> None:
        cfg = tmp_path / "claude.json"
        cfg.write_text('{"mcpServers": {}}')
        custom = [
            {
                "name": "claude-test",
                "path": str(cfg),
                "parent_key": "mcpServers",
                "adapter": "claude",
                "enabled": False,
            }
        ]
        _mod.CUSTOM_TARGETS_FILE.write_text(json.dumps({"targets": custom}))
        targets = _mod.load_targets()
        match = next(t for t in targets if t["name"] == "claude-test")
        assert match["enabled"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Launchd / systemd template rendering
# ══════════════════════════════════════════════════════════════════════════════


class TestDaemonTemplates:
    def test_launchd_plist_contains_label(self) -> None:
        rendered = _mod._LAUNCHD_PLIST.format(
            label="com.testuser.mcp-sync",
            python="/usr/bin/python3",
            script="/home/user/.local/bin/mcp-sync",
            canonical="/home/user/.config/mcp/servers.json",
            log="/home/user/.local/state/mcp-sync.log",
        )
        assert "com.testuser.mcp-sync" in rendered
        assert "WatchPaths" in rendered
        assert "RunAtLoad" in rendered
        assert "ThrottleInterval" in rendered

    def test_systemd_service_contains_execstart(self) -> None:
        rendered = _mod._SYSTEMD_SERVICE.format(
            python="/usr/bin/python3",
            script="/home/user/.local/bin/mcp-sync",
            log="/home/user/.local/state/mcp-sync.log",
        )
        assert "ExecStart" in rendered
        assert "s7dhansh" in rendered

    def test_systemd_path_contains_canonical(self) -> None:
        rendered = _mod._SYSTEMD_PATH.format(
            canonical="/home/user/.config/mcp/servers.json"
        )
        assert "servers.json" in rendered
        assert "mcp-sync.service" in rendered


# ══════════════════════════════════════════════════════════════════════════════
# Version
# ══════════════════════════════════════════════════════════════════════════════


class TestVersion:
    def test_version_string(self) -> None:
        assert isinstance(_mod.__version__, str)
        parts = _mod.__version__.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_author_fields(self) -> None:
        assert _mod.__author__ == "Sudhanshu Raheja"
        assert "s7dhansh" in _mod.__url__
