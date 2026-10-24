from __future__ import annotations

import errno
import json
import logging
import os
import sys
import tempfile
import threading
import time
from datetime import datetime
from os import getenv, makedirs
from os.path import join
from pathlib import Path
from typing import Any, cast

import requests
import spotipy
from requests.adapters import HTTPAdapter
from spotipy.cache_handler import CacheFileHandler
from spotipy.exceptions import SpotifyOauthError, SpotifyStateError
from spotipy.oauth2 import SpotifyOAuth, start_local_http_server
from urllib3.util import Retry

__all__ = [
    "DEFAULT_SCOPE",
    "LOCAL_AUTH_SERVER_TIMEOUT_SECONDS",
    "TOKEN_EXPIRY_BUFFER_SECONDS",
    "AtomicCacheFileHandler",
    "ManagedSpotifyOAuth",
    "PrintAndLogHandler",
    "create_robust_session",
    "format_elapsed_time",
    "get_artist_aliases",
    "get_spotify_client",
    "get_track_aliases",
    "load_artist_aliases",
    "load_track_aliases",
    "setup_logger",
]


class PrintAndLogHandler(logging.Handler):
    """Custom logging handler that prints to console with fallback encoding."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            print(msg)
        except UnicodeEncodeError:
            # Fallback to ascii if terminal doesn't support Unicode
            msg = self.format(record).encode("ascii", "replace").decode()
            print(msg)


def setup_logger(name: str, log_prefix: str, logs_dir: str = "logs") -> logging.Logger:
    """Configure and return a standardized logger with file and console handlers."""
    makedirs(logs_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = join(logs_dir, f"{log_prefix}_{timestamp}.log")
    formatter = logging.Formatter("%(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    print_handler = PrintAndLogHandler()
    print_handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(print_handler)
    return logger


def create_robust_session() -> requests.Session:
    """Create a requests session configured with exponential backoff and connection retries."""
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session


DEFAULT_SCOPE = (
    "user-follow-read user-library-read playlist-read-private "
    "playlist-modify-public playlist-modify-private"
)
TOKEN_EXPIRY_BUFFER_SECONDS = 300
LOCAL_AUTH_SERVER_TIMEOUT_SECONDS = 120


def _resolve_cache_path(cache_path: str | Path | None = None) -> Path:
    """Resolve the path to the Spotify OAuth token cache file."""
    if cache_path is not None:
        return Path(cache_path)
    env_path = getenv("SPOTIPY_CACHE_PATH") or getenv("CACHE_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent.parent / ".cache"


def _is_interactive_session() -> bool:
    """Return True when standard input is attached to an interactive terminal."""
    return bool(sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty())


class AtomicCacheFileHandler(CacheFileHandler):
    """Thread-safe Spotify cache file handler using atomic file replacement."""

    def __init__(self, cache_path: str | Path | None = None) -> None:
        resolved_path = _resolve_cache_path(cache_path)
        super().__init__(cache_path=str(resolved_path))
        self._lock = threading.RLock()

    def get_cached_token(self) -> dict[str, Any] | None:
        """Read cached token JSON under a reentrant thread lock."""
        with self._lock:
            return cast(dict[str, Any] | None, super().get_cached_token())

    def save_token_to_cache(self, token_info: dict[str, Any]) -> None:
        """Atomically write token JSON via a restricted temporary file and os.replace."""
        with self._lock:
            cache_file = Path(self.cache_path)
            tmp_path: Path | None = None
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=cache_file.parent,
                    prefix=f"{cache_file.name}.tmp.",
                    delete=False,
                ) as tmp_file:
                    tmp_path = Path(tmp_file.name)
                    tmp_file.write(json.dumps(token_info, cls=self.encoder_cls))
                os.chmod(tmp_path, 0o600)
                os.replace(tmp_path, cache_file)
            except OSError:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)
                logging.getLogger(__name__).warning(
                    f"Couldn't write token to cache at: {self.cache_path}"
                )


class ManagedSpotifyOAuth(SpotifyOAuth):
    """Thread-safe SpotifyOAuth that fails fast in non-interactive runs instead of hanging."""

    def __init__(
        self,
        *args: Any,
        interactive: bool = False,
        auth_server_timeout: int = LOCAL_AUTH_SERVER_TIMEOUT_SECONDS,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.interactive = interactive
        self.auth_server_timeout = auth_server_timeout
        self._token_lock = threading.RLock()

    @staticmethod
    def is_token_expired(token_info: dict[str, Any]) -> bool:
        """Check token expiry with a 5-minute buffer to prevent mid-run expiration."""
        return int(token_info["expires_at"]) - int(time.time()) < TOKEN_EXPIRY_BUFFER_SECONDS

    def get_access_token(
        self, code: str | None = None, as_dict: bool = True, check_cache: bool = True
    ) -> Any:
        """Synchronize token retrieval and refresh across worker threads."""
        with self._token_lock:
            return super().get_access_token(code=code, as_dict=as_dict, check_cache=check_cache)

    def get_auth_response(self, open_browser: bool | None = None) -> str:
        """Block interactive browser/local-server fallback unless interactive auth is enabled."""
        if not self.interactive:
            cache_loc = getattr(self.cache_handler, "cache_path", ".cache")
            raise SpotifyOauthError(
                f"No valid cached Spotify token found at '{cache_loc}'. "
                "Run 'uv run utils/generate_auth.py' to authenticate."
            )
        return cast(str, super().get_auth_response(open_browser=open_browser))

    def _get_auth_response_local_server(self, redirect_port: int) -> str:
        """Run local OAuth callback server with socket timeout, cleanup, and port-busy fallback."""
        try:
            server = start_local_http_server(redirect_port)
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE and _is_interactive_session():
                logging.getLogger(__name__).warning(
                    f"Local redirect port {redirect_port} is already in use; "
                    "falling back to manual URL copy-paste authentication."
                )
                return cast(
                    str, self._get_auth_response_interactive(open_browser=self.open_browser)
                )
            raise

        server.timeout = self.auth_server_timeout
        try:
            self._open_auth_url()
            server.handle_request()
        finally:
            server.server_close()

        return self._extract_server_auth_code(server)

    def _extract_server_auth_code(self, server: Any) -> str:
        """Validate and return authorization code captured by local callback server."""
        if server.error is not None:
            raise server.error
        if self.state is not None and server.state != self.state:
            raise SpotifyStateError(self.state, server.state)
        if server.auth_code is not None:
            return str(server.auth_code)
        raise SpotifyOauthError(
            "Local authentication server timed out without receiving an authorization callback."
        )


def get_spotify_client(
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
    scope: str = DEFAULT_SCOPE,
    requests_timeout: int = 15,
    requests_session: requests.Session | None = None,
    open_browser: bool | None = None,
) -> spotipy.Spotify:
    """Initialize and return Spotify client with thread-safe OAuth and resilient retries."""
    c_id = client_id or getenv("CLIENT_ID") or getenv("SPOTIPY_CLIENT_ID")
    c_secret = client_secret or getenv("CLIENT_SECRET") or getenv("SPOTIPY_CLIENT_SECRET")
    r_uri = redirect_uri or getenv("REDIRECT_URI") or getenv("SPOTIPY_REDIRECT_URI")
    session = requests_session or create_robust_session()
    interactive = open_browser is not None
    effective_open_browser = bool(open_browser)
    cache_handler = AtomicCacheFileHandler()

    return spotipy.Spotify(
        auth_manager=ManagedSpotifyOAuth(
            client_id=c_id,
            client_secret=c_secret,
            redirect_uri=r_uri,
            scope=scope,
            open_browser=effective_open_browser,
            requests_timeout=requests_timeout,
            requests_session=session,
            cache_handler=cache_handler,
            interactive=interactive,
        ),
        requests_timeout=requests_timeout,
        requests_session=cast(Any, session),
        retries=5,
    )


def format_elapsed_time(seconds: float) -> str:
    """Format elapsed seconds into a human readable string."""
    minutes, seconds_rem = divmod(seconds, 60)
    hours, minutes_rem = divmod(minutes, 60)
    parts: list[str] = []
    if hours > 0:
        parts.append(f"{int(hours)}h")
    if minutes_rem > 0:
        parts.append(f"{int(minutes_rem)}m")
    parts.append(f"{int(seconds_rem)}s")
    return " ".join(parts)


def _resolve_alias_path(file_path: str | Path | None, env_var: str, default_filename: str) -> Path:
    """Resolve the path to an alias JSON file."""
    if file_path is not None:
        return Path(file_path)
    env_path = getenv(env_var)
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent.parent / default_filename


def _parse_alias_entry(key: Any, val: Any) -> set[str] | None:
    """Parse a single key-value entry into an alias group."""
    k_str = str(key).strip()
    if not k_str:
        return None
    group = {k_str}
    if isinstance(val, (list, tuple, set)):
        group.update(str(item).strip() for item in val if str(item).strip())
    elif isinstance(val, str) and val.strip():
        group.add(val.strip())
    return group


def _load_raw_alias_groups(file_path: Path) -> list[set[str]]:
    """Read alias groups from a JSON file, returning empty list if missing or invalid."""
    if not file_path.is_file():
        return []
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return []
        groups: list[set[str]] = []
        for key, val in data.items():
            entry = _parse_alias_entry(key, val)
            if entry:
                groups.append(entry)
        return groups
    except Exception as e:
        logger = logging.getLogger("smart_playlists")
        logger.warning(f"Failed to load aliases from {file_path}: {e}")
        return []


def _merge_single_group(merged_groups: list[set[str]], new_group: set[str]) -> None:
    """Merge an alias group into existing groups if overlapping, or append it."""
    matching_indices = [
        i for i, existing in enumerate(merged_groups) if not existing.isdisjoint(new_group)
    ]
    if not matching_indices:
        merged_groups.append(new_group)
        return

    first_idx = matching_indices[0]
    target = merged_groups[first_idx]
    target.update(new_group)
    for idx in reversed(matching_indices[1:]):
        target.update(merged_groups.pop(idx))


def _merge_alias_groups(alias_groups: list[set[str]]) -> list[set[str]]:
    """Merge overlapping alias groups and convert names to lowercase."""
    merged_groups: list[set[str]] = []
    for group in alias_groups:
        lower_group = {item.lower() for item in group}
        _merge_single_group(merged_groups, lower_group)
    return merged_groups


def _build_alias_map(merged_groups: list[set[str]]) -> dict[str, set[str]]:
    """Map every item name in a group to its full alias group."""
    alias_map: dict[str, set[str]] = {}
    for group in merged_groups:
        for name in group:
            alias_map[name] = group
    return alias_map


def load_artist_aliases(file_path: str | Path | None = None) -> dict[str, set[str]]:
    """Load artist aliases from a JSON file and build a bidirectional lowercase alias mapping."""
    target_path = _resolve_alias_path(file_path, "ARTIST_ALIASES_FILE", "artist_aliases.json")
    raw_groups = _load_raw_alias_groups(target_path)
    merged_groups = _merge_alias_groups(raw_groups)
    return _build_alias_map(merged_groups)


def load_track_aliases(file_path: str | Path | None = None) -> dict[str, set[str]]:
    """Load track aliases from a JSON file and build a bidirectional lowercase alias mapping."""
    target_path = _resolve_alias_path(file_path, "TRACK_ALIASES_FILE", "track_aliases.json")
    raw_groups = _load_raw_alias_groups(target_path)
    merged_groups = _merge_alias_groups(raw_groups)
    return _build_alias_map(merged_groups)


def get_artist_aliases(artist: str, alias_map: dict[str, set[str]] | None = None) -> set[str]:
    """Return all known lowercase aliases for an artist (including the artist itself)."""
    artist_lower = (artist or "").strip().lower()
    if not artist_lower:
        return set()
    if alias_map and artist_lower in alias_map:
        return set(alias_map[artist_lower])
    return {artist_lower}


def get_track_aliases(track: str, alias_map: dict[str, set[str]] | None = None) -> set[str]:
    """Return all known lowercase aliases for a track (including the track itself)."""
    track_lower = (track or "").strip().lower()
    if not track_lower:
        return set()
    if alias_map and track_lower in alias_map:
        return set(alias_map[track_lower])
    return {track_lower}
