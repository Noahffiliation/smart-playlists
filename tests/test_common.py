import logging
import pytest
from unittest.mock import MagicMock, patch
from utils.common import PrintAndLogHandler, setup_logger, get_spotify_client, format_elapsed_time


def test_print_and_log_handler_normal():
    handler = PrintAndLogHandler()
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    record = logging.LogRecord('test', logging.INFO, '', 0, 'Test message', (), None)

    with patch('builtins.print') as mock_print:
        handler.emit(record)
        mock_print.assert_called_once_with('Test message')


def test_print_and_log_handler_unicode_encode_error():
    handler = PrintAndLogHandler()
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    record = logging.LogRecord('test', logging.INFO, '', 0, 'Test \u266a music', (), None)

    with patch('builtins.print') as mock_print:
        # First print raises UnicodeEncodeError, second print succeeds with ascii fallback
        mock_print.side_effect = [
            UnicodeEncodeError('ascii', 'Test \u266a music', 5, 6, 'ordinal not in range'),
            None
        ]
        handler.emit(record)
        assert mock_print.call_count == 2


def test_setup_logger(tmp_path):
    log_dir = str(tmp_path / "test_logs")
    logger = setup_logger("test_custom_logger", "test_prefix", logs_dir=log_dir)
    assert logger.name == "test_custom_logger"
    assert len(logger.handlers) == 2


def test_get_spotify_client():
    with patch('utils.common.spotipy.Spotify') as mock_sp_cls:
        client = get_spotify_client(
            client_id='id1',
            client_secret='sec1',
            redirect_uri='http://localhost:8888',
            scope='user-read',
            requests_timeout=20
        )
        assert client == mock_sp_cls.return_value

        # Custom requests_session
        custom_session = MagicMock()
        client_custom = get_spotify_client(requests_session=custom_session)
        assert client_custom == mock_sp_cls.return_value


def test_format_elapsed_time():
    assert format_elapsed_time(5) == "5s"
    assert format_elapsed_time(65) == "1m 5s"
    assert format_elapsed_time(3665) == "1h 1m 5s"
    assert format_elapsed_time(3600) == "1h 0s"
