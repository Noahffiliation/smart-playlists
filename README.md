<h1 align="center">Smart Playlists</h1>

## Table of Contents
- [About](#about)
- [Getting Started](#getting_started)
- [Usage](#usage)
- [Built Using](#built_using)
- [Authors](#authors)
- [Acknowledgments](#acknowledgement)

## About <a name = "about"></a>
As a heavy Spotify user, I wanted to replicate iTunes' Smart Playlists feature in Spotify, specifically Recently Added since I add music to my Spotify library/playlists all the time. Because my playlists are rather large at this point (1,000+ tracks), recent tracks don't get played very often and get lost in the sauce. This script running periodically keeps an automatically updated playlist of recently added tracks to my library.

### Note <a name = "note"></a>
This was more-or-less completely [vibe-coded](https://en.wikipedia.org/wiki/Vibe_coding) with [DeepSeek](https://chat.deepseek.com/), when it first became publically available. I wanted to try out the newest AI chatbot and also try out actual vibe coding and see how it goes for an inconsequential project. Generally, I'm pleasantly surprised with how well this turned out, functions just as intended.

## Getting Started <a name = "getting_started"></a>
### Prerequisites
- [Spotify Developer account](https://developer.spotify.com/)
- An app created in the Spotify Developer Dashboard
    - Enable `Web API` in the settings

### Installing
Create a Python Virtual Environment
```
python -m venv venv
source venv/bin/activate
```

Install Python packages:
```
pip install spotipy python-dotenv
```

Create `.env`
```
touch .env
```
Add info for `CLIENT_ID` and `CLIENT_SECRET` from the Spotify Developer App Settings
A good default for `REDIRECT_URI` is `http://localhost:8888/callback`, make sure it matches in the Spotify Developer App settings
`SOURCE_PLAYLIST_ID` is from your public Spotify playlist share link
`TARGET_PLAYLIST_NAME` is the name of your new playlist

## Usage <a name="usage"></a>
Once you fill out your `.env`, you can run the Python file to test it out
Use either a cronjob or Windows Task Scheduler to run the script periodically

## Built Using <a name = "built_using"></a>
- [Python](https://www.python.org/)
- [DeepSeek](https://chat.deepseek.com/)

## Authors <a name = "authors"></a>
- [@Noahffiliation](https://github.com/Noahffiliation) - Idea & Initial work

## Acknowledgements <a name = "acknowledgement"></a>
- iTunes
