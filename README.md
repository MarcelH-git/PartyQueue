# PartyQueue

A self-hosted party jukebox. Guests suggest YouTube videos from their phones, the host controls the queue, the TV plays everything back — without embedding issues.

The key point: guests can suggest videos, but cannot skip, delete or reorder the queue. Only the host has control.

## Features

- Guests join by name (no account needed)
- YouTube search with live suggestions
- Host panel: skip, reorder, delete
- TV view (`/tv`) plays videos directly via yt-dlp — works on restricted browsers too (e.g. Fire TV Silk)
- QR code on the TV screen for easy joining
- Playback history

## Requirements

- Python 3.8+
- `pip install flask qrcode pillow yt-dlp`
- YouTube Data API v3 key (optional but recommended for search)

## Starting

```bash
cp .env.example .env
# edit .env (API key, password)
bash run.sh
```

Then in the browser:
- Guests: `http://<IP>:5000/`
- TV: `http://<IP>:5000/tv`
- Host: `http://<IP>:5000/host`

## Configuration (.env)

The host interface (`/host`) is password protected. The password is set freely in `.env`.

```
YOUTUBE_API_KEY=your_api_key
JUKEBOX_PASSWORD=
HOST_NAME=Host
PUBLIC_HOST=          # leave empty for automatic IP detection
```

## Notes

- Update yt-dlp occasionally: `pip install -U yt-dlp`
- Direct video URLs expire after ~6h — not an issue for party use
- `.env` is not checked into the repository
