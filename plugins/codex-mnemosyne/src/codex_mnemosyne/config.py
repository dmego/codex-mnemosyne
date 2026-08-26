"""Environment-driven configuration for the Codex Mnemosyne plugin."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 hosts
    tomllib = None


PLUGIN_IDS = {
    "codex-mnemosyne",
    "codex-mnemosyne@codex-mnemosyne",
}
CONFIG_ENV_KEYS = (
    "CODEX_MNEMOSYNE_BANK",
    "CODEX_MNEMOSYNE_AUTHOR_ID",
    "CODEX_MNEMOSYNE_AUTHOR_TYPE",
    "CODEX_MNEMOSYNE_SCOPE",
    "CODEX_MNEMOSYNE_SOURCE",
    "CODEX_MNEMOSYNE_IMPORTANCE",
    "CODEX_MNEMOSYNE_RECALL_TOP_K",
    "CODEX_MNEMOSYNE_RECALL_MAX_CHARS",
    "CODEX_MNEMOSYNE_ITEM_MAX_CHARS",
    "CODEX_MNEMOSYNE_CAPTURE_MIN_CHARS",
    "CODEX_MNEMOSYNE_CAPTURE_MAX_CHARS",
    "CODEX_MNEMOSYNE_STATE_DIR",
    "CODEX_MNEMOSYNE_AUTO_RECALL",
    "CODEX_MNEMOSYNE_AUTO_CAPTURE",
    "CODEX_MNEMOSYNE_AUTO_TOOL_CAPTURE",
    "CODEX_MNEMOSYNE_EXTRACT",
    "CODEX_MNEMOSYNE_EXTRACT_ENTITIES",
    "CODEX_MNEMOSYNE_VERACITY",
    "CODEX_MNEMOSYNE_TRUST_TIER",
    "CODEX_MNEMOSYNE_DEBUG",
    "CODEX_MNEMOSYNE_DIAGNOSTICS",
)
NATIVE_CONFIG_KEYS = (
    "MNEMOSYNE_MCP_BANK",
    "MNEMOSYNE_AUTHOR_ID",
    "MNEMOSYNE_AUTHOR_TYPE",
    "MNEMOSYNE_DEFAULT_SCOPE",
    "MNEMOSYNE_DATA_DIR",
    "MNEMOSYNE_HOME",
    "MNEMOSYNE_SHARED_DB_PATH",
    "MNEMOSYNE_SYNC_REMOTE",
    "MNEMOSYNE_SYNC_KEY",
)


def _first_non_empty(env: Mapping[str, str], *names: str, default: str) -> str:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return default


def _bounded_int(env: Mapping[str, str], name: str, default: int, lower: int, upper: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(lower, min(upper, value))


def _bounded_float(env: Mapping[str, str], name: str, default: float, lower: float, upper: float) -> float:
    try:
        value = float(env.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(lower, min(upper, value))


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no", "disabled"}


def _safe_slug(value: str, default: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return value.strip("-.") or default


def _toml_scalar(value: object) -> str | None:
    """Convert a TOML scalar to an environment-style string safely."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _read_toml(path: Path) -> dict[str, object]:
    if tomllib is None:
        try:
            import tomli  # type: ignore
        except ImportError:
            return {}
        parser = tomli
    else:
        parser = tomllib
    try:
        with path.open("rb") as handle:
            value = parser.load(handle)
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _nested_env(table: object) -> dict[str, str]:
    if not isinstance(table, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, value in table.items():
        converted = _toml_scalar(value)
        if converted is not None and (str(key) in CONFIG_ENV_KEYS or str(key) in NATIVE_CONFIG_KEYS):
            result[str(key)] = converted
    return result


def _file_env(document: Mapping[str, object]) -> dict[str, str]:
    """Extract only Mnemosyne values from Codex's config shape.

    Codex keeps plugin MCP transport values under
    ``plugins.<plugin-id>.mcp_servers.mnemosyne.env``.  A top-level MCP table
    is accepted too, which makes the same plugin usable when a user chooses to
    configure the server directly.
    """
    result: dict[str, str] = {}
    mcp_servers = document.get("mcp_servers")
    if isinstance(mcp_servers, Mapping):
        server = mcp_servers.get("mnemosyne")
        if isinstance(server, Mapping):
            result.update(_nested_env(server.get("env")))

    plugins = document.get("plugins")
    if isinstance(plugins, Mapping):
        for plugin_id, plugin in plugins.items():
            normalized = str(plugin_id)
            if normalized not in PLUGIN_IDS and not normalized.startswith("codex-mnemosyne@"):
                continue
            if not isinstance(plugin, Mapping):
                continue
            scoped_servers = plugin.get("mcp_servers")
            if not isinstance(scoped_servers, Mapping):
                continue
            server = scoped_servers.get("mnemosyne")
            if isinstance(server, Mapping):
                result.update(_nested_env(server.get("env")))
    return result


def _candidate_config_paths(values: Mapping[str, str], payload: Mapping[str, object] | None) -> list[Path]:
    explicit = (values.get("CODEX_MNEMOSYNE_CONFIG") or "").strip()
    if explicit:
        return [Path(explicit).expanduser()]

    codex_home = (values.get("CODEX_HOME") or "").strip()
    if not codex_home:
        codex_home = str(Path.home() / ".codex")
    paths: list[Path] = [Path(codex_home).expanduser() / "config.toml"]

    project_cwd = ""
    if payload:
        project_cwd = str(payload.get("cwd") or payload.get("projectFolder") or "").strip()
    if not project_cwd:
        project_cwd = str(values.get("CODEX_PROJECT_ROOT") or values.get("PWD") or "").strip()
    if project_cwd:
        project_config = Path(project_cwd).expanduser() / ".codex" / "config.toml"
        if project_config not in paths:
            paths.append(project_config)
    return paths


def resolve_config_env(
    env: Mapping[str, str] | None = None,
    payload: Mapping[str, object] | None = None,
) -> tuple[dict[str, str], str]:
    """Merge Codex config-file values and process environment values.

    Process values always win over files.  For deterministic unit tests a
    caller passing a small mapping opts into file loading only when it gives an
    explicit ``CODEX_HOME``/config path or a payload; the real runner passes no
    mapping and therefore reads the host's normal ``~/.codex/config.toml``.
    """
    source_env = os.environ if env is None else env
    values = {str(key): str(value) for key, value in source_env.items()}
    should_read_files = (
        env is None
        or "CODEX_HOME" in values
        or "CODEX_MNEMOSYNE_CONFIG" in values
        or payload is not None
    )
    file_values: dict[str, str] = {}
    sources: list[str] = []
    if should_read_files:
        for path in _candidate_config_paths(values, payload):
            if not path.is_file():
                continue
            file_values.update(_file_env(_read_toml(path)))
            sources.append(str(path))
    merged = dict(file_values)
    merged.update(values)
    # A Codex plugin config commonly names the integration variable while the
    # upstream MCP server reads its native name.  Bridge that alias in both
    # directions only when one side is absent; explicit process values remain
    # untouched.
    aliases = (
        ("CODEX_MNEMOSYNE_BANK", "MNEMOSYNE_MCP_BANK"),
        ("CODEX_MNEMOSYNE_AUTHOR_ID", "MNEMOSYNE_AUTHOR_ID"),
        ("CODEX_MNEMOSYNE_AUTHOR_TYPE", "MNEMOSYNE_AUTHOR_TYPE"),
    )
    for plugin_key, native_key in aliases:
        if native_key not in merged and plugin_key in merged:
            merged[native_key] = merged[plugin_key]
        if plugin_key not in merged and native_key in merged:
            merged[plugin_key] = merged[native_key]
    return merged, ",".join(sources)


def apply_config_env(
    env: MutableMapping[str, str] | None = None,
    payload: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Apply config-file values into a mutable environment mapping.

    This is used by the bundled MCP launcher because Codex intentionally owns
    the plugin transport command and does not always materialize nested
    ``.mcp_servers.<name>.env`` values in the child process.
    """
    source = None if env is None or env is os.environ else env
    merged, _ = resolve_config_env(source, payload)
    if env is None:
        os.environ.update(merged)
        return dict(os.environ)
    env.update(merged)
    return dict(env)


@dataclass(frozen=True)
class Config:
    """Resolved plugin settings.

    Mnemosyne's own environment variables remain untouched. This object only
    controls the Codex integration and passes the selected bank through to the
    SDK.
    """

    bank: str
    author_id: str
    author_type: str
    scope: str
    source: str
    importance: float
    recall_top_k: int
    recall_max_chars: int
    item_max_chars: int
    capture_min_chars: int
    capture_max_chars: int
    state_dir: Path
    auto_recall: bool
    auto_capture: bool
    auto_tool_capture: bool
    extract: bool
    extract_entities: bool
    veracity: str
    trust_tier: str
    debug: bool
    diagnostics: bool
    config_source: str = ""

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> "Config":
        values, config_source = resolve_config_env(env, payload)
        scope = _first_non_empty(values, "CODEX_MNEMOSYNE_SCOPE", default="global").lower()
        if scope not in {"session", "global"}:
            scope = "global"

        state_dir = Path(
            _first_non_empty(
                values,
                "CODEX_MNEMOSYNE_STATE_DIR",
                "PLUGIN_DATA",
                default=str(Path.home() / ".codex" / "mnemosyne"),
            )
        ).expanduser()

        return cls(
            bank=_first_non_empty(values, "CODEX_MNEMOSYNE_BANK", "MNEMOSYNE_MCP_BANK", default="default"),
            author_id=_first_non_empty(
                values,
                "CODEX_MNEMOSYNE_AUTHOR_ID",
                "MNEMOSYNE_AUTHOR_ID",
                default="codex",
            ),
            author_type=_first_non_empty(
                values,
                "CODEX_MNEMOSYNE_AUTHOR_TYPE",
                "MNEMOSYNE_AUTHOR_TYPE",
                default="agent",
            ),
            scope=scope,
            source=_first_non_empty(values, "CODEX_MNEMOSYNE_SOURCE", default="codex-auto"),
            importance=_bounded_float(values, "CODEX_MNEMOSYNE_IMPORTANCE", 0.4, 0.0, 1.0),
            recall_top_k=_bounded_int(values, "CODEX_MNEMOSYNE_RECALL_TOP_K", 5, 1, 20),
            recall_max_chars=_bounded_int(values, "CODEX_MNEMOSYNE_RECALL_MAX_CHARS", 6000, 512, 24000),
            item_max_chars=_bounded_int(values, "CODEX_MNEMOSYNE_ITEM_MAX_CHARS", 1500, 128, 8000),
            capture_min_chars=_bounded_int(values, "CODEX_MNEMOSYNE_CAPTURE_MIN_CHARS", 80, 10, 2000),
            capture_max_chars=_bounded_int(values, "CODEX_MNEMOSYNE_CAPTURE_MAX_CHARS", 12000, 256, 40000),
            state_dir=state_dir,
            auto_recall=_flag(values, "CODEX_MNEMOSYNE_AUTO_RECALL", True),
            auto_capture=_flag(values, "CODEX_MNEMOSYNE_AUTO_CAPTURE", True),
            auto_tool_capture=_flag(values, "CODEX_MNEMOSYNE_AUTO_TOOL_CAPTURE", True),
            extract=_flag(values, "CODEX_MNEMOSYNE_EXTRACT", False),
            extract_entities=_flag(values, "CODEX_MNEMOSYNE_EXTRACT_ENTITIES", False),
            veracity=_first_non_empty(values, "CODEX_MNEMOSYNE_VERACITY", default="unknown"),
            trust_tier=_first_non_empty(values, "CODEX_MNEMOSYNE_TRUST_TIER", default="EXTERNAL_WRITE"),
            debug=_flag(values, "CODEX_MNEMOSYNE_DEBUG", False),
            diagnostics=_flag(values, "CODEX_MNEMOSYNE_DIAGNOSTICS", False),
            config_source=config_source,
        )

    def session_id(self, payload: Mapping[str, object]) -> str:
        """Return a stable, path-free session identifier."""
        raw_session = str(
            payload.get("session_id")
            or payload.get("sessionId")
            or payload.get("conversation_id")
            or payload.get("conversationId")
            or "unknown"
        )
        cwd = str(payload.get("cwd") or payload.get("projectFolder") or os.getcwd())
        project = _safe_slug(Path(cwd).name, "workspace")
        return f"{project}:{_safe_slug(raw_session, 'unknown')}"

    def project_name(self, payload: Mapping[str, object]) -> str:
        cwd = str(payload.get("cwd") or payload.get("projectFolder") or os.getcwd())
        return _safe_slug(Path(cwd).name, "workspace")

    def project_channel(self, payload: Mapping[str, object]) -> str:
        """Return a stable, non-path channel key for project-isolated recall."""
        cwd = str(payload.get("cwd") or payload.get("projectFolder") or os.getcwd())
        digest = hashlib.sha256(str(Path(cwd).expanduser().resolve()).encode("utf-8")).hexdigest()[:16]
        return f"codex-project:{digest}"
