"""Exabase M-1 memory plugin.

Self-organizing long-term memory provider using Exabase's M-1 memory API.

Config via environment variables:
  EXABASE_API_KEY    - API key for Exabase (required)
  EXABASE_BASE_ID    - Exabase Base ID (optional)
  EXABASE_BASE_URL   - API base URL (default: https://api.exabase.io)

Or via $HERMES_HOME/exabase.json.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider
from tools.registry import tool_error

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.exabase.io"
_TIMEOUT_SECONDS = 20
_MIN_QUERY_LEN = 3
_MAX_SYNC_CHARS = 8000


def _load_config() -> Dict[str, Any]:
    """Load Exabase config from env vars with profile-scoped JSON overrides."""
    from hermes_constants import get_hermes_home

    config = {
        "api_key": os.environ.get("EXABASE_API_KEY", ""),
        "base_id": os.environ.get("EXABASE_BASE_ID") or os.environ.get("BASE_ID", ""),
        "base_url": os.environ.get("EXABASE_BASE_URL", _DEFAULT_BASE_URL),
        "precision": os.environ.get("EXABASE_PRECISION"),
        "expand_queries": os.environ.get("EXABASE_EXPAND_QUERIES"),
        "rerank_candidates": os.environ.get("EXABASE_RERANK_CANDIDATES"),
    }

    config_path = get_hermes_home() / "exabase.json"
    if config_path.exists():
        try:
            file_config = json.loads(config_path.read_text(encoding="utf-8"))
            config.update({
                key: value for key, value in file_config.items()
                if value is not None and value != ""
            })
        except Exception as exc:
            logger.debug("Failed to load Exabase config: %s", exc)

    return config


def _bounded_limit(value: Any, *, default: int = 10, maximum: int = 50) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), maximum)


def _bounded_precision(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
        return min(max(parsed, 0.0), 1.0)
    except (TypeError, ValueError):
        return None


def _bounded_integer(value: Any, minimum: int, maximum: int) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = int(value)
        return min(max(parsed, minimum), maximum)
    except (TypeError, ValueError):
        return None


class _ExabaseClient:
    """Minimal REST client for the Exabase Memory API."""

    def __init__(self, api_key: str, *, base_id: str = "", base_url: str = ""):
        if not api_key:
            raise RuntimeError("EXABASE_API_KEY is required")
        self.api_key = api_key
        self.base_id = base_id
        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")

    def _requests(self):
        try:
            import requests
            return requests
        except ImportError as exc:
            raise RuntimeError("requests is required for Exabase. Run: pip install requests") from exc

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key,
        }
        if self.base_id:
            headers["X-Exabase-Base-Id"] = self.base_id
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _parse_response(response) -> Dict[str, Any]:
        try:
            data = response.json()
        except Exception:
            data = None

        if response.status_code >= 400:
            if isinstance(data, dict):
                message = data.get("message") or data.get("error") or data
            else:
                message = response.text
            raise RuntimeError(f"Exabase HTTP {response.status_code}: {message}")

        return data if isinstance(data, dict) else {}

    def create_memory(self, content: str, *, infer: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "source": "text",
            "content": content,
        }
        if not infer:
            payload["infer"] = False

        response = self._requests().post(
            self._url("/v2/memories"),
            headers=self._headers(),
            json=payload,
            timeout=_TIMEOUT_SECONDS,
        )
        return self._parse_response(response)

    def search_memories(
        self,
        query: str,
        *,
        limit: int = 10,
        precision: Optional[float] = None,
        expand_queries: Optional[int] = None,
        rerank_candidates: Optional[int] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"query": query, "limit": limit}
        if precision is not None:
            params["precision"] = precision
        if expand_queries is not None:
            params["expandQueries"] = expand_queries
        if rerank_candidates is not None:
            params["rerankCandidates"] = rerank_candidates

        response = self._requests().get(
            self._url("/v2/memories/search"),
            headers=self._headers(),
            params=params,
            timeout=_TIMEOUT_SECONDS,
        )
        return self._parse_response(response)


SEARCH_SCHEMA = {
    "name": "exabase_search",
    "description": (
        "Search Exabase M-1 long-term memory for relevant facts and context. "
        "Use when prior preferences, decisions, or cross-session context may help."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "limit": {
                "type": "integer",
                "description": "Maximum results (default: 10, max: 50).",
            },
            "precision": {
                "type": "number",
                "description": "Minimum precision (0.0 to 1.0). Controls strictness of results.",
            },
            "expandQueries": {
                "type": "integer",
                "description": "Number of query expansions (1 to 5). Increases recall.",
            },
            "rerankCandidates": {
                "type": "integer",
                "description": "Number of candidates for reranking (1 to 500). Improves relevance.",
            },
        },
        "required": ["query"],
    },
}

REMEMBER_SCHEMA = {
    "name": "exabase_remember",
    "description": (
        "Store a durable memory in Exabase M-1. Use for explicit preferences, "
        "corrections, decisions, or facts worth remembering across sessions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The memory content to store."},
        },
        "required": ["content"],
    },
}


class ExabaseMemoryProvider(MemoryProvider):
    """Exabase M-1 memory with basic add/search support."""

    def __init__(self):
        self._api_key = ""
        self._base_id = ""
        self._base_url = _DEFAULT_BASE_URL
        self._precision: Optional[float] = None
        self._expand_queries: Optional[int] = None
        self._rerank_candidates: Optional[int] = None
        self._client: Optional[_ExabaseClient] = None
        self._client_lock = threading.Lock()
        self._prefetch_result = ""
        self._prefetch_lock = threading.Lock()
        self._prefetch_thread: Optional[threading.Thread] = None
        self._sync_thread: Optional[threading.Thread] = None

    @property
    def name(self) -> str:
        return "exabase"

    def is_available(self) -> bool:
        return bool(_load_config().get("api_key"))

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "api_key",
                "description": "Exabase API key",
                "secret": True,
                "required": True,
                "env_var": "EXABASE_API_KEY",
                "url": "https://exabase.io",
            },
            {
                "key": "base_id",
                "description": "Exabase Base ID (optional)",
                "default": "",
            },
            {
                "key": "precision",
                "description": "Default search precision (0.0 to 1.0, optional)",
                "env_var": "EXABASE_PRECISION",
            },
            {
                "key": "expand_queries",
                "description": "Default query expansions (1 to 5, optional)",
                "env_var": "EXABASE_EXPAND_QUERIES",
            },
            {
                "key": "rerank_candidates",
                "description": "Default rerank candidates (1 to 500, optional)",
                "env_var": "EXABASE_RERANK_CANDIDATES",
            },
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        from pathlib import Path

        config_path = Path(hermes_home) / "exabase.json"
        existing: Dict[str, Any] = {}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing.update({
            key: value for key, value in values.items()
            if key != "api_key" and value is not None
        })
        config_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    def initialize(self, session_id: str, **kwargs) -> None:
        config = _load_config()
        self._api_key = config.get("api_key", "")
        self._base_id = config.get("base_id", "")
        self._base_url = config.get("base_url", _DEFAULT_BASE_URL)
        self._precision = _bounded_precision(config.get("precision"))
        self._expand_queries = _bounded_integer(config.get("expand_queries"), 1, 5)
        self._rerank_candidates = _bounded_integer(config.get("rerank_candidates"), 1, 500)

    def _get_client(self) -> _ExabaseClient:
        with self._client_lock:
            if self._client is None:
                self._client = _ExabaseClient(
                    self._api_key,
                    base_id=self._base_id,
                    base_url=self._base_url,
                )
            return self._client

    def system_prompt_block(self) -> str:
        return (
            "# Exabase Memory\n"
            "Active. Use exabase_search to recall long-term memories and "
            "exabase_remember to store durable facts."
        )

    @staticmethod
    def _hits(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        hits = response.get("hits", [])
        return hits if isinstance(hits, list) else []

    @staticmethod
    def _format_hits(hits: List[Dict[str, Any]]) -> str:
        lines = []
        for hit in hits:
            content = str(hit.get("content") or "").strip()
            if not content:
                continue
            score = hit.get("score")
            if isinstance(score, (int, float)):
                lines.append(f"- {content} (score: {score:.3g})")
            else:
                lines.append(f"- {content}")
        return "\n".join(lines)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            self._prefetch_thread.join(timeout=3.0)
        with self._prefetch_lock:
            result = self._prefetch_result
            self._prefetch_result = ""
        return f"## Exabase Memory\n{result}" if result else ""

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        query = (query or "").strip()
        if len(query) < _MIN_QUERY_LEN:
            return

        def _run() -> None:
            try:
                hits = self._hits(
                    self._get_client().search_memories(
                        query,
                        limit=5,
                        precision=self._precision,
                        expand_queries=self._expand_queries,
                        rerank_candidates=self._rerank_candidates,
                    )
                )
                formatted = self._format_hits(hits)
                if formatted:
                    with self._prefetch_lock:
                        self._prefetch_result = formatted
            except Exception as exc:
                logger.debug("Exabase prefetch failed: %s", exc)

        self._prefetch_thread = threading.Thread(
            target=_run,
            daemon=True,
            name="exabase-prefetch",
        )
        self._prefetch_thread.start()

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        user_content = (user_content or "").strip()[:_MAX_SYNC_CHARS]
        assistant_content = (assistant_content or "").strip()[:_MAX_SYNC_CHARS]
        if not user_content and not assistant_content:
            return

        content = f"User: {user_content}\nAssistant: {assistant_content}".strip()

        def _sync() -> None:
            try:
                self._get_client().create_memory(content, infer=False)
            except Exception as exc:
                logger.warning("Exabase sync failed: %s", exc)

        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)

        self._sync_thread = threading.Thread(
            target=_sync,
            daemon=True,
            name="exabase-sync",
        )
        self._sync_thread.start()

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [SEARCH_SCHEMA, REMEMBER_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if tool_name == "exabase_search":
            query = (args.get("query") or "").strip()
            if not query:
                return tool_error("Missing required parameter: query")
            limit = _bounded_limit(args.get("limit", 10))
            precision = _bounded_precision(args.get("precision"))
            expand_queries = _bounded_integer(args.get("expandQueries"), 1, 5)
            rerank_candidates = _bounded_integer(args.get("rerankCandidates"), 1, 500)

            try:
                hits = self._hits(
                    self._get_client().search_memories(
                        query,
                        limit=limit,
                        precision=precision,
                        expand_queries=expand_queries,
                        rerank_candidates=rerank_candidates,
                    )
                )
                if not hits:
                    return json.dumps({"result": "No relevant memories found.", "count": 0})
                results = [
                    {
                        "id": hit.get("id"),
                        "name": hit.get("name"),
                        "content": hit.get("content", ""),
                        "score": hit.get("score"),
                    }
                    for hit in hits
                ]
                return json.dumps({"results": results, "count": len(results)})
            except Exception as exc:
                return tool_error(f"Search failed: {exc}")

        if tool_name == "exabase_remember":
            content = (args.get("content") or "").strip()
            if not content:
                return tool_error("Missing required parameter: content")
            try:
                response = self._get_client().create_memory(content, infer=True)
                memories = response.get("memories", {})
                memory_ids = memories.get("created", []) if isinstance(memories, dict) else []
                return json.dumps({
                    "result": "Memory stored.",
                    "id": response.get("id"),
                    "memory_ids": memory_ids,
                })
            except Exception as exc:
                return tool_error(f"Failed to store memory: {exc}")

        return tool_error(f"Unknown tool: {tool_name}")

    def shutdown(self) -> None:
        for thread in (self._prefetch_thread, self._sync_thread):
            if thread and thread.is_alive():
                thread.join(timeout=5.0)
        with self._client_lock:
            self._client = None


def register(ctx) -> None:
    """Register Exabase as a memory provider plugin."""
    ctx.register_memory_provider(ExabaseMemoryProvider())
