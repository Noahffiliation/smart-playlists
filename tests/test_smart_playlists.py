import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import smart_playlists

@pytest.fixture(autouse=True)
def mock_sleep():
    with patch('time.sleep', return_value=None):
        yield

@pytest.fixture
def mock_spotify():
    with patch('smart_playlists.sp') as mock_sp:
        yield mock_sp

@pytest.fixture
def mock_lastfm():
    with patch('smart_playlists.network') as mock_network:
        yield mock_network

def test_format_elapsed_time():
    assert smart_playlists.format_elapsed_time(5) == "5s"
    assert smart_playlists.format_elapsed_time(65) == "1m 5s"
    assert smart_playlists.format_elapsed_time(3665) == "1h 1m 5s"

def test_extract_track_data():
    cutoff_date = datetime(2026, 1, 1)

    # Valid track
    item = {
        'added_at': '2026-01-28T13:00:00Z',
        'track': {
            'uri': 'spotify:track:123',
            'name': 'Test Track',
            'artists': [{'name': 'Test Artist'}]
        }
    }
    result = smart_playlists._extract_track_data(item, cutoff_date)
    assert result['uri'] == 'spotify:track:123'
    assert result['name'] == 'Test Track'
    assert result['artist'] == 'Test Artist'

    # Old track
    item['added_at'] = '2025-12-31T13:00:00Z'
    assert smart_playlists._extract_track_data(item, cutoff_date) is None

    # Invalid track
    assert smart_playlists._extract_track_data(None, cutoff_date) is None
    assert smart_playlists._extract_track_data({}, cutoff_date) is None

def test_process_and_sort_tracks():
    tracks = [
        {'uri': 'track1', 'added_at': datetime(2026, 1, 10)},
        {'uri': 'track2', 'added_at': datetime(2026, 1, 20)},
        {'uri': 'track1', 'added_at': datetime(2026, 1, 15)}, # Newer version of track1
    ]
    result = smart_playlists._process_and_sort_tracks(tracks)
    assert result == ['track2', 'track1']

def test_get_all_playlist_tracks(mock_spotify):
    mock_spotify.playlist_tracks.side_effect = [
        {'items': [{'track': {'uri': '1'}}], 'next': 'url'},
        {'items': [{'track': {'uri': '2'}}], 'next': None}
    ]
    tracks = smart_playlists.get_all_playlist_tracks('playlist_id')
    assert len(tracks) == 2
    assert tracks[0]['track']['uri'] == '1'
    assert tracks[1]['track']['uri'] == '2'

def test_get_liked_songs(mock_spotify):
    mock_spotify.current_user_saved_tracks.side_effect = [
        {'items': [{'track': {'uri': '1'}, 'added_at': '2026-01-28T13:00:00Z'}], 'next': None},
        {'items': [], 'next': None}
    ]
    tracks = smart_playlists.get_liked_songs()
    assert len(tracks) == 1
    assert tracks[0]['track']['uri'] == '1'

def test_get_lastfm_track_playcount(mock_lastfm):
    mock_track = MagicMock()
    mock_track.get_userplaycount.return_value = 10
    mock_lastfm.get_track.return_value = mock_track

    count = smart_playlists.get_lastfm_track_playcount('Artist', 'Track')
    assert count == 10

    mock_track.get_userplaycount.return_value = None
    assert smart_playlists.get_lastfm_track_playcount('Artist', 'Track') == 0

    mock_lastfm.get_track.side_effect = Exception("Error")
    assert smart_playlists.get_lastfm_track_playcount('Artist', 'Track') == 0

def test_create_track_dict():
    track = {
        'uri': 'spotify:track:123',
        'name': 'Test Track',
        'artists': [{'name': 'Test Artist'}]
    }
    result = smart_playlists._create_track_dict(track)
    assert result['uri'] == 'spotify:track:123'
    assert result['key'] == 'test artist|||test track'

    assert smart_playlists._create_track_dict(None) is None
    assert smart_playlists._create_track_dict({}) is None

def test_add_liked_songs_to_library(mock_spotify):
    mock_spotify.current_user_saved_tracks.side_effect = [
        {'items': [{'track': {'uri': '1', 'name': 'N1', 'artists': [{'name': 'A1'}]}, 'added_at': '2026-01-28T13:00:00Z'}], 'next': None},
        {'items': [], 'next': None}
    ]
    all_tracks = {}
    smart_playlists._add_liked_songs_to_library(all_tracks)
    assert '1' in all_tracks
    assert all_tracks['1']['name'] == 'N1'

def test_update_recent_tracks_playlist(mock_spotify):
    # Mock get_recent_tracks_from_playlists
    with patch('smart_playlists.get_recent_tracks_from_playlists') as mock_get_recent:
        mock_get_recent.return_value = ['track1', 'track2']

        # Mocking playlist discovery
        mock_spotify.current_user_playlists.return_value = {'items': [{'name': 'Target', 'id': 'target_id'}]}

        smart_playlists.update_recent_tracks_playlist(['source'], 'Target')

        mock_spotify.playlist_replace_items.assert_called_with('target_id', [])
        mock_spotify.playlist_add_items.assert_called_with('target_id', ['track1', 'track2'])

def test_update_recent_tracks_playlist_create_new(mock_spotify):
    with patch('smart_playlists.get_recent_tracks_from_playlists') as mock_get_recent:
        mock_get_recent.return_value = ['track1']
        mock_spotify.current_user_playlists.return_value = {'items': []}
        mock_spotify.current_user.return_value = {'id': 'user_id'}
        mock_spotify.user_playlist_create.return_value = {'id': 'new_id'}

        smart_playlists.update_recent_tracks_playlist(['source'], 'New')

        mock_spotify.user_playlist_create.assert_called()
        mock_spotify.playlist_add_items.assert_called_with('new_id', ['track1'])

def test_match_spotify_with_lastfm(mock_lastfm):
    spotify_tracks = {
        'uri1': {'name': 'Name1', 'artist': 'Artist1'},
        'uri2': {'name': 'Name2', 'artist': 'Artist2'}
    }

    with patch('smart_playlists.get_lastfm_track_playcount') as mock_pc:
        mock_pc.side_effect = [10, 0]

        result = smart_playlists.match_spotify_with_lastfm(spotify_tracks)
        assert len(result) == 2
        assert result[0]['playcount'] == 10
        assert result[1]['playcount'] == 0

def test_create_or_update_playlist_exists(mock_spotify):
    mock_spotify.current_user_playlists.return_value = {'items': [{'name': 'P1', 'id': 'p1'}]}
    smart_playlists.create_or_update_playlist('P1', ['t1'])
    mock_spotify.playlist_replace_items.assert_called_with('p1', [])
    mock_spotify.playlist_add_items.assert_called_with('p1', ['t1'])

def test_create_or_update_playlist_new(mock_spotify):
    mock_spotify.current_user_playlists.return_value = {'items': []}
    mock_spotify.current_user.return_value = {'id': 'user_id'}
    mock_spotify.user_playlist_create.return_value = {'id': 'p1'}
    smart_playlists.create_or_update_playlist('P1', ['t1'])
    mock_spotify.user_playlist_create.assert_called_with('user_id', 'P1', public=True)
    mock_spotify.playlist_add_items.assert_called_with('p1', ['t1'])

def test_update_playcount_playlists(mock_spotify):
    with patch('smart_playlists.get_all_spotify_library_tracks') as mock_library, \
         patch('smart_playlists.match_spotify_with_lastfm') as mock_match, \
         patch('smart_playlists.create_or_update_playlist') as mock_create_update:

        mock_library.return_value = {}
        mock_match.return_value = [
            {'uri': 't1', 'artist': 'A', 'name': 'N', 'playcount': 100},
            {'uri': 't2', 'artist': 'A2', 'name': 'N2', 'playcount': 10}
        ]

        smart_playlists.update_playcount_playlists(['s1'], 'Top', 'Bottom')
        assert mock_create_update.call_count == 2

def test_get_recent_playlist_tracks(mock_spotify):
    mock_spotify.playlist.return_value = {'name': 'P1'}
    with patch('smart_playlists.get_all_playlist_tracks') as mock_tracks, \
         patch('smart_playlists._process_playlist_tracks') as mock_process:
        mock_tracks.return_value = []
        mock_process.return_value = [{'uri': 't1'}]

        result = smart_playlists._get_recent_playlist_tracks(['id'], datetime.now())
        assert result == [{'uri': 't1'}]

def test_process_playlist_tracks(mock_spotify):
    with patch('smart_playlists._extract_track_data') as mock_extract:
        mock_extract.side_effect = [{'uri': 't1'}, None, {'uri': 't2'}]
        result = smart_playlists._process_playlist_tracks([1, 2, 3], datetime.now())
        assert len(result) == 2

def test_get_all_spotify_library_tracks(mock_spotify):
    with patch('smart_playlists._add_liked_songs_to_library') as mock_liked, \
         patch('smart_playlists._add_playlist_tracks_to_library') as mock_playlist:

        result = smart_playlists.get_all_spotify_library_tracks(['ids'])
        assert result == {}
        mock_liked.assert_called_once()
        mock_playlist.assert_called_once()

def test_add_playlist_tracks_to_library(mock_spotify):
    mock_spotify.playlist.return_value = {'name': 'P1'}
    with patch('smart_playlists.get_all_playlist_tracks') as mock_get:
        mock_get.return_value = [{'track': {'uri': 't1', 'name': 'N', 'artists': [{'name': 'A'}]}}]
        all_tracks = {}
        smart_playlists._add_playlist_tracks_to_library(all_tracks, ['id'])
        assert 't1' in all_tracks
