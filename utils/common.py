from __future__ import annotations

import logging
from datetime import datetime
from os import getenv, makedirs
from os.path import join

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


def get_spotify_client(
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
    scope: str = "user-follow-read user-library-read playlist-modify-public playlist-modify-private",
    requests_timeout: int = 15,
    requests_session: requests.Session | None = None,
) -> spotipy.Spotify:
    """Initialize and return Spotify client with OAuth and resilient connection retries."""
    c_id = client_id or getenv("CLIENT_ID")
    c_secret = client_secret or getenv("CLIENT_SECRET")
    r_uri = redirect_uri or getenv("REDIRECT_URI")
    session = requests_session or create_robust_session()

    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=c_id, client_secret=c_secret, redirect_uri=r_uri, scope=scope
        ),
        requests_timeout=requests_timeout,
        requests_session=session,
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
