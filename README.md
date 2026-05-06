# Spotify Analysis Tool

Yay now you can visualize your Spotify listening history!!

# Setup

## Python Environment

1. Create and activate a virtual environment:

	```bash
	python3 -m venv .venv
	source .venv/bin/activate
	```

2. Install the project dependencies:

	```bash
	pip install -r requirements.txt
	```

## Spotify API Setup

This is necessary for the "refresh" feature, which allows you to fetch newer Spotify plays.

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and create an app.
2. Add `http://127.0.0.1:8765/callback` as the Redirect URI, and click the checkox for `Web API` under "APIs used".

3. Copy the app’s Client ID, and paste this into your local `.env` file.

```bash
SPOTIFY_CLIENT_ID=your_client_id_here
```

## Run the app

Start the local server:

```bash
python serve.py
```

Then open the dashboard in your browser:

```text
http://127.0.0.1:8765/
```

From the dashboard, click **Refresh Spotify data** to authorize Spotify and fetch newer plays.