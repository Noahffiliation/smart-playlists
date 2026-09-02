import logging
from unittest.mock import MagicMock, patch

from utils.common import PrintAndLogHandler, format_elapsed_time, get_spotify_client, setup_logger


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
