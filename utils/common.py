from __future__ import annotations

import json
import logging
from datetime import datetime
from os import getenv, makedirs
from os.path import join
from pathlib import Path
from typing import Any, cast

import requests
import spotipy
from requests.adapters import HTTPAdapter
from spotipy.oauth2 import SpotifyOAuth
from urllib3.util import Retry


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


def get_spotify_client(
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
    scope: str = DEFAULT_SCOPE,
    requests_timeout: int = 15,
    requests_session: requests.Session | None = None,
    open_browser: bool = True,
) -> spotipy.Spotify:
    """Initialize and return Spotify client with OAuth and resilient connection retries."""
    c_id = client_id or getenv("CLIENT_ID") or getenv("SPOTIPY_CLIENT_ID")
    c_secret = client_secret or getenv("CLIENT_SECRET") or getenv("SPOTIPY_CLIENT_SECRET")
    r_uri = redirect_uri or getenv("REDIRECT_URI") or getenv("SPOTIPY_REDIRECT_URI")
    session = requests_session or create_robust_session()

    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=c_id,
            client_secret=c_secret,
            redirect_uri=r_uri,
            scope=scope,
            open_browser=open_browser,
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
