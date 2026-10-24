import errno
import json
import logging
import stat
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from spotipy.exceptions import SpotifyOauthError, SpotifyStateError

from utils.common import (
    AtomicCacheFileHandler,
    ManagedSpotifyOAuth,
    PrintAndLogHandler,
    _is_interactive_session,
    _resolve_cache_path,
    format_elapsed_time,
    get_artist_aliases,
    get_spotify_client,
    get_track_aliases,
    load_artist_aliases,
    load_track_aliases,
    setup_logger,
)


def test_print_and_log_handler_normal():
    handler = PrintAndLogHandler()
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)
    record = logging.LogRecord("test", logging.INFO, "", 0, "Test message", (), None)

    with patch("builtins.print") as mock_print:
        handler.emit(record)
        mock_print.assert_called_once_with("Test message")


def test_print_and_log_handler_unicode_encode_error():
    handler = PrintAndLogHandler()
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)
    record = logging.LogRecord("test", logging.INFO, "", 0, "Test \u266a music", (), None)

    with patch("builtins.print") as mock_print:
        # First print raises UnicodeEncodeError, second print succeeds with ascii fallback
        mock_print.side_effect = [
            UnicodeEncodeError("ascii", "Test \u266a music", 5, 6, "ordinal not in range"),
            None,
        ]
        handler.emit(record)
        assert mock_print.call_count == 2


def test_setup_logger(tmp_path):
    log_dir = str(tmp_path / "test_logs")
    logger = setup_logger("test_custom_logger", "test_prefix", logs_dir=log_dir)
    assert logger.name == "test_custom_logger"
    assert len(logger.handlers) == 2


def test_resolve_cache_path_and_interactivity(tmp_path):
    explicit = tmp_path / "custom.cache"
    assert _resolve_cache_path(explicit) == explicit

    with patch.dict("os.environ", {"SPOTIPY_CACHE_PATH": str(tmp_path / "env1.cache")}):
        assert _resolve_cache_path() == tmp_path / "env1.cache"

    with patch.dict(
        "os.environ", {"SPOTIPY_CACHE_PATH": "", "CACHE_PATH": str(tmp_path / "env2.cache")}
    ):
        assert _resolve_cache_path() == tmp_path / "env2.cache"

    with patch.dict("os.environ", {"SPOTIPY_CACHE_PATH": "", "CACHE_PATH": ""}):
        default_path = _resolve_cache_path()
        assert default_path.name == ".cache"

    mock_tty = MagicMock()
    mock_tty.isatty.return_value = True
    with patch("utils.common.sys.stdin", mock_tty):
        assert _is_interactive_session() is True

    mock_tty.isatty.return_value = False
    with patch("utils.common.sys.stdin", mock_tty):
        assert _is_interactive_session() is False

    with patch("utils.common.sys.stdin", None):
        assert _is_interactive_session() is False


def test_atomic_cache_file_handler_read_write_and_concurrency(tmp_path):
    cache_file = tmp_path / ".cache"
    handler = AtomicCacheFileHandler(cache_path=cache_file)

    assert handler.get_cached_token() is None

    token_data = {"access_token": "tok_0", "refresh_token": "ref", "expires_at": 9999999999}
    handler.save_token_to_cache(token_data)

    assert cache_file.exists()
    mode = stat.S_IMODE(cache_file.stat().st_mode)
    assert mode == 0o600
    assert handler.get_cached_token() == token_data

    # Verify concurrent reads/writes never observe partial/empty JSON
    observed_tokens: list[dict[str, object] | None] = []
    results_lock = threading.Lock()

    def writer() -> None:
        for i in range(25):
            handler.save_token_to_cache(
                {"access_token": f"tok_{i}", "refresh_token": "ref", "expires_at": 9999999999}
            )

    def reader() -> None:
        for _ in range(25):
            tok = handler.get_cached_token()
            with results_lock:
                observed_tokens.append(tok)

    threads = [
        threading.Thread(target=writer),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(observed_tokens) == 50
    assert all(tok is not None and "access_token" in tok for tok in observed_tokens)


def test_atomic_cache_file_handler_oserror_cleanup(tmp_path):
    cache_file = tmp_path / ".cache"
    handler = AtomicCacheFileHandler(cache_path=cache_file)

    # OSError before tmp_path is created
    with patch("utils.common.tempfile.NamedTemporaryFile", side_effect=OSError("disk full")):
        handler.save_token_to_cache({"access_token": "x"})
    assert not cache_file.exists()

    # OSError during os.replace cleans up temporary file
    with patch("utils.common.os.replace", side_effect=OSError("replace failed")):
        handler.save_token_to_cache({"access_token": "x"})
    assert not cache_file.exists()
    assert list(tmp_path.glob(".cache.tmp.*")) == []


def test_managed_spotify_oauth_non_interactive_and_expiry(tmp_path):
    cache_handler = AtomicCacheFileHandler(cache_path=tmp_path / ".cache")
    oauth = ManagedSpotifyOAuth(
        client_id="cid",
        client_secret="csec",
        redirect_uri="http://127.0.0.1:8888/callback",
        scope="user-follow-read",
        open_browser=False,
        cache_handler=cache_handler,
        interactive=False,
    )

    now = int(time.time())
    assert oauth.is_token_expired({"expires_at": now + 60}) is True
    assert oauth.is_token_expired({"expires_at": now + 600}) is False

    # Missing cache in non-interactive mode fails fast without binding port 8888
    with pytest.raises(SpotifyOauthError, match=r"generate_auth\.py"):
        oauth.get_access_token(as_dict=False)

    # Interactive mode delegates get_auth_response to parent
    oauth_interactive = ManagedSpotifyOAuth(
        client_id="cid",
        client_secret="csec",
        redirect_uri="http://127.0.0.1:8888/callback",
        scope="user-follow-read",
        open_browser=False,
        cache_handler=cache_handler,
        interactive=True,
    )
    with patch.object(
        ManagedSpotifyOAuth.__bases__[0], "get_auth_response", return_value="auth_code_123"
    ) as mock_super_auth:
        assert oauth_interactive.get_auth_response(open_browser=False) == "auth_code_123"
        mock_super_auth.assert_called_once_with(open_browser=False)


def test_managed_spotify_oauth_local_server_branches(tmp_path):
    cache_handler = AtomicCacheFileHandler(cache_path=tmp_path / ".cache")
    oauth = ManagedSpotifyOAuth(
        client_id="cid",
        client_secret="csec",
        redirect_uri="http://127.0.0.1:8888/callback",
        state="expected_state",
        scope="user-follow-read",
        open_browser=True,
        cache_handler=cache_handler,
        interactive=True,
        auth_server_timeout=30,
    )

    # 1. Happy path: returns auth_code and always closes server
    mock_server = MagicMock()
    mock_server.error = None
    mock_server.state = "expected_state"
    mock_server.auth_code = "code_ok"
    with (
        patch("utils.common.start_local_http_server", return_value=mock_server),
        patch.object(oauth, "_open_auth_url") as mock_open,
    ):
        assert oauth._get_auth_response_local_server(8888) == "code_ok"
        assert mock_server.timeout == 30
        mock_open.assert_called_once()
        mock_server.handle_request.assert_called_once()
        mock_server.server_close.assert_called_once()

    # 2. Server error branch
    mock_server.reset_mock()
    mock_server.error = SpotifyOauthError("access_denied")
    with (
        patch("utils.common.start_local_http_server", return_value=mock_server),
        patch.object(oauth, "_open_auth_url"),
        pytest.raises(SpotifyOauthError, match="access_denied"),
    ):
        oauth._get_auth_response_local_server(8888)
    mock_server.server_close.assert_called_once()

    # 3. State mismatch branch
    mock_server.reset_mock()
    mock_server.error = None
    mock_server.state = "wrong_state"
    mock_server.auth_code = "code_ok"
    with (
        patch("utils.common.start_local_http_server", return_value=mock_server),
        patch.object(oauth, "_open_auth_url"),
        pytest.raises(SpotifyStateError),
    ):
        oauth._get_auth_response_local_server(8888)
    mock_server.server_close.assert_called_once()

    # 4. Timeout / no auth_code branch
    mock_server.reset_mock()
    mock_server.error = None
    mock_server.state = "expected_state"
    mock_server.auth_code = None
    with (
        patch("utils.common.start_local_http_server", return_value=mock_server),
        patch.object(oauth, "_open_auth_url"),
        pytest.raises(SpotifyOauthError, match="timed out"),
    ):
        oauth._get_auth_response_local_server(8888)
    mock_server.server_close.assert_called_once()

    # 5. Port already in use in interactive terminal falls back to manual URL paste
    addr_in_use = OSError(errno.EADDRINUSE, "Address already in use")
    with (
        patch("utils.common.start_local_http_server", side_effect=addr_in_use),
        patch("utils.common._is_interactive_session", return_value=True),
        patch.object(
            oauth, "_get_auth_response_interactive", return_value="manual_code"
        ) as mock_manual,
    ):
        assert oauth._get_auth_response_local_server(8888) == "manual_code"
        mock_manual.assert_called_once_with(open_browser=True)

    # 6. Port already in use in non-interactive session (or non-EADDRINUSE OSError) re-raises
    with (
        patch("utils.common.start_local_http_server", side_effect=addr_in_use),
        patch("utils.common._is_interactive_session", return_value=False),
        pytest.raises(OSError, match="Address already in use"),
    ):
        oauth._get_auth_response_local_server(8888)

    perm_err = OSError(errno.EACCES, "Permission denied")
    with (
        patch("utils.common.start_local_http_server", side_effect=perm_err),
        patch("utils.common._is_interactive_session", return_value=True),
        pytest.raises(OSError, match="Permission denied"),
    ):
        oauth._get_auth_response_local_server(8888)


def test_get_spotify_client():
    with (
        patch("utils.common.spotipy.Spotify") as mock_sp_cls,
        patch("utils.common.ManagedSpotifyOAuth") as mock_oauth_cls,
        patch("utils.common.AtomicCacheFileHandler") as mock_cache_cls,
        patch("utils.common.create_robust_session") as mock_session_fn,
    ):
        default_session = MagicMock()
        mock_session_fn.return_value = default_session

        # Default non-interactive mode (open_browser=None -> interactive=False, open_browser=False)
        client = get_spotify_client(
            client_id="id1",
            client_secret="sec1",
            redirect_uri="http://localhost:8888",
            scope="user-read",
            requests_timeout=20,
        )
        assert client == mock_sp_cls.return_value
        mock_oauth_cls.assert_called_with(
            client_id="id1",
            client_secret="sec1",
            redirect_uri="http://localhost:8888",
            scope="user-read",
            open_browser=False,
            requests_timeout=20,
            requests_session=default_session,
            cache_handler=mock_cache_cls.return_value,
            interactive=False,
        )

        # Custom requests_session and explicit open_browser=False -> interactive=True
        custom_session = MagicMock()
        client_custom = get_spotify_client(
            client_id="id2",
            client_secret="sec2",
            redirect_uri="http://localhost:8888",
            requests_session=custom_session,
            open_browser=False,
        )
        assert client_custom == mock_sp_cls.return_value
        mock_oauth_cls.assert_called_with(
            client_id="id2",
            client_secret="sec2",
            redirect_uri="http://localhost:8888",
            scope=(
                "user-follow-read user-library-read playlist-read-private "
                "playlist-modify-public playlist-modify-private"
            ),
            open_browser=False,
            requests_timeout=15,
            requests_session=custom_session,
            cache_handler=mock_cache_cls.return_value,
            interactive=True,
        )

        # Fallback to SPOTIPY_* env vars with explicit open_browser=True -> interactive=True
        with patch.dict(
            "os.environ",
            {
                "CLIENT_ID": "",
                "CLIENT_SECRET": "",
                "REDIRECT_URI": "",
                "SPOTIPY_CLIENT_ID": "spotipy_id",
                "SPOTIPY_CLIENT_SECRET": "spotipy_sec",
                "SPOTIPY_REDIRECT_URI": "http://localhost:8888/spotipy",
            },
        ):
            get_spotify_client(open_browser=True)
            mock_oauth_cls.assert_called_with(
                client_id="spotipy_id",
                client_secret="spotipy_sec",
                redirect_uri="http://localhost:8888/spotipy",
                scope=(
                    "user-follow-read user-library-read playlist-read-private "
                    "playlist-modify-public playlist-modify-private"
                ),
                open_browser=True,
                requests_timeout=15,
                requests_session=default_session,
                cache_handler=mock_cache_cls.return_value,
                interactive=True,
            )


def test_format_elapsed_time():
    assert format_elapsed_time(5) == "5s"
    assert format_elapsed_time(65) == "1m 5s"
    assert format_elapsed_time(3665) == "1h 1m 5s"
    assert format_elapsed_time(3600) == "1h 0s"


def test_load_artist_aliases_default():
    # Tests loading default artist_aliases.json from project root
    aliases = load_artist_aliases()
    assert "花冷え。" in aliases
    assert "hanabie." in aliases
    assert aliases["花冷え。"] == {"花冷え。", "hanabie."}


def test_load_artist_aliases_custom_file(tmp_path):
    custom_file = tmp_path / "custom_aliases.json"
    data = {
        "Band A": ["Alias 1"],
        "Band B": ["Alias 2"],
        "Bridge": ["Alias 1", "Alias 2"],
        "Band C": "Single Alias",
        "": ["Empty Key Ignored"],
        "Band D": [],
        "Band E": ["  "],
    }
    custom_file.write_text(json.dumps(data), encoding="utf-8")

    result = load_artist_aliases(custom_file)
    # Band A, Band B, Alias 1, Alias 2, Bridge should all be merged into one group
    expected_merged = {"band a", "band b", "alias 1", "alias 2", "bridge"}
    assert result["band a"] == expected_merged
    assert result["band b"] == expected_merged
    assert result["bridge"] == expected_merged
    assert result["band c"] == {"band c", "single alias"}
    assert result["band d"] == {"band d"}
    assert result["band e"] == {"band e"}


def test_load_artist_aliases_env_var(tmp_path):
    custom_file = tmp_path / "env_aliases.json"
    custom_file.write_text(json.dumps({"X": ["Y"]}), encoding="utf-8")

    with patch.dict("os.environ", {"ARTIST_ALIASES_FILE": str(custom_file)}):
        result = load_artist_aliases()
        assert result["x"] == {"x", "y"}


def test_load_artist_aliases_invalid_and_nonexistent(tmp_path):
    # Non-existent file
    assert load_artist_aliases(tmp_path / "missing.json") == {}

    # Invalid JSON
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text("{bad json}", encoding="utf-8")
    assert load_artist_aliases(invalid_file) == {}

    # Non-dict JSON
    list_file = tmp_path / "list.json"
    list_file.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert load_artist_aliases(list_file) == {}


def test_get_artist_aliases():
    alias_map = {
        "花冷え。": {"花冷え。", "hanabie."},
        "hanabie.": {"花冷え。", "hanabie."},
    }

    assert get_artist_aliases("花冷え。", alias_map) == {"花冷え。", "hanabie."}
    assert get_artist_aliases("HANABIE.", alias_map) == {"花冷え。", "hanabie."}
    assert get_artist_aliases("Unknown Artist", alias_map) == {"unknown artist"}
    assert get_artist_aliases("Coldplay", None) == {"coldplay"}
    assert get_artist_aliases("", alias_map) == set()
    assert get_artist_aliases("   ", alias_map) == set()


def test_load_track_aliases_default():
    aliases = load_track_aliases()
    assert "iwaly - izna version" in aliases
    assert "iwaly" in aliases
    assert "iwaly (izna version)" in aliases


def test_load_track_aliases_env_var(tmp_path):
    custom_file = tmp_path / "env_track_aliases.json"
    custom_file.write_text(json.dumps({"Song A": ["Song B"]}), encoding="utf-8")

    with patch.dict("os.environ", {"TRACK_ALIASES_FILE": str(custom_file)}):
        result = load_track_aliases()
        assert result["song a"] == {"song a", "song b"}


def test_get_track_aliases():
    alias_map = {
        "iwaly - izna version": {"iwaly - izna version", "iwaly"},
        "iwaly": {"iwaly - izna version", "iwaly"},
    }

    assert get_track_aliases("IWALY - izna Version", alias_map) == {
        "iwaly - izna version",
        "iwaly",
    }
    assert get_track_aliases("IWALY", alias_map) == {"iwaly - izna version", "iwaly"}
    assert get_track_aliases("Unknown Track", alias_map) == {"unknown track"}
    assert get_track_aliases("Song", None) == {"song"}
    assert get_track_aliases("", alias_map) == set()
    assert get_track_aliases("   ", alias_map) == set()
