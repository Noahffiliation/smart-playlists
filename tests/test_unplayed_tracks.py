import pytest
from unittest.mock import patch, MagicMock
from unplayed_tracks import generate_unplayed_playlist, main

def test_generate_unplayed_playlist():
    with patch('unplayed_tracks.match_spotify_with_lastfm') as mock_match, \
         patch('unplayed_tracks.create_or_update_playlist') as mock_create_update, \
         patch('unplayed_tracks.get_lastfm_track_playcount') as mock_get_playcount:

        mock_match.return_value = [
            {'uri': 't1', 'playcount': 0, 'artist': 'Artist 1', 'name': 'Track 1'},
            {'uri': 't2', 'playcount': 10, 'artist': 'Artist 2', 'name': 'Track 2'},
            {'uri': 't3', 'playcount': 0, 'artist': 'Artist 3', 'name': 'Track 3'}
        ]
        mock_get_playcount.return_value = 0

        generate_unplayed_playlist({}, "Unplayed Playlist")

        mock_match.assert_called_once_with({})
        mock_create_update.assert_called_once_with("Unplayed Playlist", ['t1', 't3'])
        assert mock_get_playcount.call_count == 2

def test_generate_unplayed_playlist_empty():
    with patch('unplayed_tracks.match_spotify_with_lastfm') as mock_match, \
         patch('unplayed_tracks.create_or_update_playlist') as mock_create_update:

        mock_match.return_value = [
            {'uri': 't2', 'playcount': 10, 'artist': 'Artist 2', 'name': 'Track 2'}
        ]

        generate_unplayed_playlist({}, "Unplayed Playlist")

        mock_match.assert_called_once_with({})
        mock_create_update.assert_called_once_with("Unplayed Playlist", [])

def test_main():
    with patch('unplayed_tracks.getenv') as mock_getenv, \
         patch('unplayed_tracks.get_all_spotify_library_tracks') as mock_get_lib, \
         patch('unplayed_tracks.generate_unplayed_playlist') as mock_generate:

        def mock_env(key, default=''):
            if key == 'SOURCE_PLAYLIST_IDS':
                return 'id1, id2 '
            elif key == 'UNPLAYED_PLAYLIST_NAME':
                return 'My Unplayed Tracks'
            return default

        mock_getenv.side_effect = mock_env
        mock_get_lib.return_value = {'id1': {'uri': 't1'}}

        main()

        mock_get_lib.assert_called_once_with(['id1', 'id2'])
        mock_generate.assert_called_once_with({'id1': {'uri': 't1'}}, 'My Unplayed Tracks')

def test_main_empty_env():
    with patch('unplayed_tracks.getenv') as mock_getenv, \
         patch('unplayed_tracks.get_all_spotify_library_tracks') as mock_get_lib, \
         patch('unplayed_tracks.generate_unplayed_playlist') as mock_generate:

        def mock_env(key, default=''):
            if key == 'SOURCE_PLAYLIST_IDS':
                return ''
            elif key == 'UNPLAYED_PLAYLIST_NAME':
                return default
            return default

        mock_getenv.side_effect = mock_env
        mock_get_lib.return_value = {}

        main()

        mock_get_lib.assert_called_once_with([])
        mock_generate.assert_called_once_with({}, 'Unplayed Tracks')
