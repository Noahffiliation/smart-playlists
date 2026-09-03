from unittest.mock import MagicMock, patch

from utils import generate_auth


def test_generate_master_cache():
    mock_sp = MagicMock()
    mock_sp.current_user.return_value = {"id": "user_123"}
    mock_sp.auth_manager.get_authorize_url.return_value = (
        "https://accounts.spotify.com/authorize?..."
    )
    mock_sp.auth_manager.redirect_uri = "http://127.0.0.1:8888/callback"

    # open_browser=True
    user = generate_auth.generate_master_cache(client=mock_sp, open_browser=True)
    assert user["id"] == "user_123"
    mock_sp.current_user.assert_called_once()

    # open_browser=False
    user2 = generate_auth.generate_master_cache(client=mock_sp, open_browser=False)
    assert user2["id"] == "user_123"

    # None user branch
    mock_sp.current_user.return_value = None
    import pytest

    with pytest.raises(RuntimeError, match="Failed to retrieve current Spotify user"):
        generate_auth.generate_master_cache(client=mock_sp)


def test_main():
    with patch("utils.generate_auth.generate_master_cache", return_value={"id": "u1"}) as mock_gen:
        # Default
        generate_auth.main([])
        mock_gen.assert_called_with(open_browser=True)

        # --manual flag
        generate_auth.main(["--manual"])
        mock_gen.assert_called_with(open_browser=False)
