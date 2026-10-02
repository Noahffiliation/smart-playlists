from unittest.mock import patch

import pytest

from utils import unplayed_tracks


@pytest.fixture(autouse=True)
def mock_sleep():
    with patch("time.sleep", return_value=None):
        yield


def test_generate_unplayed_playlist():
    # Tracks to test progress logging, duration filtering, and playcount verification
    spotify_library = {
        f"uri_{i}": {
            "name": f"Track {i}",
            "artist": f"Artist {i}",
            "uri": f"uri_{i}",
            "duration_ms": 120_000 if i == 14 else 180_000,
        }
        for i in range(16)
    }

    # Track 0-9: 0 plays, 180s duration (> 30s) -> unplayed
    # Track 10: 5 plays in bulk -> skipped
    # Track 11: 0 plays in bulk, verify returns 2 plays (false positive) -> skipped
    # Track 12: 0 plays in bulk, 25s duration (<= 30s) -> skipped (too short)
    # Track 13: 0 plays in bulk, 30s duration (<= 30s) -> skipped (exactly 30s)
    # Track 14: 0 plays in bulk, duration_ms None in matched, retrieved from library (120s) -> unplayed
    # Track 15: 0 plays in bulk, invalid duration_ms -> skipped (fails conversion)
    matched_tracks = [
        {
            "uri": f"uri_{i}",
            "name": f"Track {i}",
            "artist": f"Artist {i}",
            "duration_ms": (
                25_000
                if i == 12
                else 30_000
                if i == 13
                else None
                if i == 14
                else "invalid"
                if i == 15
                else 180_000
            ),
            "playcount": 0 if i != 10 else 5,
        }
        for i in range(16)
    ]

    with (
        patch("utils.unplayed_tracks.match_spotify_with_lastfm", return_value=matched_tracks),
        patch("utils.unplayed_tracks.get_lastfm_track_playcount") as mock_pc,
        patch("utils.unplayed_tracks.create_or_update_playlist") as mock_create_update,
    ):

        def fake_get_pc(artist, name):
            if name == "Track 11":
                return 2
            return 0

        mock_pc.side_effect = fake_get_pc

        result = unplayed_tracks.generate_unplayed_playlist(spotify_library, "Unplayed Playlist")

        expected_uris = [f"uri_{i}" for i in range(10)] + ["uri_14"]
        assert len(result) == 11
        mock_create_update.assert_called_once_with("Unplayed Playlist", expected_uris)

        # Verify that short tracks (Track 12, 13, 15) were not passed to get_lastfm_track_playcount
        verified_track_names = {call.args[1] for call in mock_pc.call_args_list}
        assert "Track 12" not in verified_track_names
        assert "Track 13" not in verified_track_names
        assert "Track 15" not in verified_track_names


def test_main():
    with (
        patch(
            "utils.unplayed_tracks.get_all_spotify_library_tracks", return_value={}
        ) as mock_get_lib,
        patch("utils.unplayed_tracks.generate_unplayed_playlist") as mock_gen,
        patch.dict(
            "os.environ",
            {
                "SOURCE_PLAYLIST_IDS": "p1,p2",
                "UNPLAYED_PLAYLIST_NAME": "My Unplayed",
            },
        ),
    ):
        # Default run with env
        unplayed_tracks.main()
        mock_get_lib.assert_called_with(["p1", "p2"])
        mock_gen.assert_called_with({}, "My Unplayed", min_duration_ms=30000)

        # Custom arguments
        unplayed_tracks.main(
            source_playlist_ids=["p3"],
            unplayed_playlist_name="Custom Unplayed",
            min_duration_ms=45000,
        )
        mock_get_lib.assert_called_with(["p3"])
        mock_gen.assert_called_with({}, "Custom Unplayed", min_duration_ms=45000)

    # Test env var configuration for MIN_TRACK_DURATION_MS
    with (
        patch("utils.unplayed_tracks.get_all_spotify_library_tracks", return_value={}),
        patch("utils.unplayed_tracks.generate_unplayed_playlist") as mock_gen,
        patch.dict("os.environ", {"MIN_TRACK_DURATION_MS": "40000"}),
    ):
        unplayed_tracks.main()
        mock_gen.assert_called_with({}, "Unplayed Tracks", min_duration_ms=40000)

    # Test invalid env var fallback to MIN_TRACK_DURATION_MS default
    with (
        patch("utils.unplayed_tracks.get_all_spotify_library_tracks", return_value={}),
        patch("utils.unplayed_tracks.generate_unplayed_playlist") as mock_gen,
        patch.dict("os.environ", {"MIN_TRACK_DURATION_MS": "not_a_number"}),
    ):
        unplayed_tracks.main()
        mock_gen.assert_called_with({}, "Unplayed Tracks", min_duration_ms=30000)
