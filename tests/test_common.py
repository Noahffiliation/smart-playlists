import json
import logging
from unittest.mock import MagicMock, patch

from utils.common import (
    PrintAndLogHandler,
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


def test_get_spotify_client():
    with (
        patch("utils.common.spotipy.Spotify") as mock_sp_cls,
        patch("utils.common.SpotifyOAuth") as mock_oauth_cls,
    ):
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
            open_browser=True,
        )

        # Custom requests_session and open_browser=False
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
        )

        # Fallback to SPOTIPY_* env vars
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
            get_spotify_client()
            mock_oauth_cls.assert_called_with(
                client_id="spotipy_id",
                client_secret="spotipy_sec",
                redirect_uri="http://localhost:8888/spotipy",
                scope=(
                    "user-follow-read user-library-read playlist-read-private "
                    "playlist-modify-public playlist-modify-private"
                ),
                open_browser=True,
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
