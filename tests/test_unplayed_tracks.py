import pytest
from unittest.mock import MagicMock, patch
from utils import unplayed_tracks


@pytest.fixture(autouse=True)
def mock_sleep():
    with patch('time.sleep', return_value=None):
        yield


def test_generate_unplayed_playlist():
    # 12 tracks to test progress logging at 10 items
    spotify_library = {
        f'uri_{i}': {'name': f'Track {i}', 'artist': f'Artist {i}', 'uri': f'uri_{i}'}
        for i in range(12)
    }

    mock_client = MagicMock()
    mock_network = MagicMock()

    # Track 0-9: 0 plays
    # Track 10: 5 plays in bulk
    # Track 11: 0 plays in bulk, verify returns 2 plays (false positive)
    matched_tracks = [
        {'uri': f'uri_{i}', 'name': f'Track {i}', 'artist': f'Artist {i}', 'playcount': 0 if i != 10 else 5}
        for i in range(12)
    ]

    with patch('utils.unplayed_tracks.match_spotify_with_lastfm', return_value=matched_tracks), \
         patch('utils.unplayed_tracks.get_lastfm_track_playcount') as mock_pc, \
         patch('utils.unplayed_tracks.create_or_update_playlist') as mock_create_update:

        def fake_get_pc(artist, name, lastfm_network=None):
            if name == 'Track 11':
                return 2
            return 0

        mock_pc.side_effect = fake_get_pc

        result = unplayed_tracks.generate_unplayed_playlist(
            spotify_library,
            'Unplayed Playlist',
            client=mock_client,
            lastfm_network=mock_network
        )

        assert len(result) == 10
        mock_create_update.assert_called_once()


def test_main():
    with patch('utils.unplayed_tracks.get_all_spotify_library_tracks', return_value={}) as mock_get_lib, \
         patch('utils.unplayed_tracks.generate_unplayed_playlist') as mock_gen, \
         patch.dict('os.environ', {'SOURCE_PLAYLIST_IDS': 'p1,p2', 'UNPLAYED_PLAYLIST_NAME': 'My Unplayed'}):

        # Default run with env
        unplayed_tracks.main()
        mock_get_lib.assert_called_with(['p1', 'p2'], client=None)
        mock_gen.assert_called_with({}, 'My Unplayed', client=None, lastfm_network=None)

        # Custom arguments
        unplayed_tracks.main(
            source_playlist_ids=['p3'],
            unplayed_playlist_name='Custom Unplayed'
        )
        mock_get_lib.assert_called_with(['p3'], client=None)
        mock_gen.assert_called_with({}, 'Custom Unplayed', client=None, lastfm_network=None)
