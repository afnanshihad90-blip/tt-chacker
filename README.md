# YTDown Backend v2

Simple & fast video downloader API backend for Telegram bots.  
Supports **TikTok, YouTube, Instagram, Twitter/X, Facebook** and more via `yt-dlp`.

Perfect for deploying on **Render** (free tier works).

---

## Features

- `POST /info` → Get video title, stats, available formats (no download)
- `POST /download` → Download video/audio and get temporary file link
- Auto file cleanup after 15 minutes
- CORS enabled
- TikTok optimized headers

---

## Quick Deploy on Render

1. Create a new **Web Service** on [Render](https://render.com)
2. Connect your GitHub repo
3. Settings:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 120`
4. Deploy!

Your API will be available at: `https://your-service.onrender.com`

---

## API Endpoints

### Health Check
```
GET /health
```

### Get Video Info
```http
POST /info
Content-Type: application/json

{
  "url": "https://www.tiktok.com/@user/video/123456789"
}
```

### Download Video
```http
POST /download
Content-Type: application/json

{
  "url": "https://www.tiktok.com/@user/video/123456789",
  "format_id": "best",       // optional
  "audio_only": false        // true = MP3
}
```

Response example:
```json
{
  "success": true,
  "file_id": "uuid-here",
  "filename": "uuid.mp4",
  "filesize_mb": 12.5,
  "title": "Video Title",
  "download_url": "/download/uuid-here"
}
```

Then download the file from:
```
GET /download/{file_id}
```

---

## Local Testing

```bash
pip install -r requirements.txt
python main.py
```

API docs: http://localhost:8000/docs

---

## Environment Variables (optional)

| Variable          | Default | Description                    |
|-------------------|---------|--------------------------------|
| `PORT`            | 8000    | Server port                    |
| `CLEANUP_MINUTES` | 15      | Auto delete files after X min  |

---

## Notes for Telegram Bot

In your Telegram bot code, call this backend like:

```python
import httpx

async def get_video_info(url: str):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post("https://your-backend.onrender.com/info", json={"url": url})
        return r.json()

async def download_video(url: str, audio_only=False):
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://your-backend.onrender.com/download",
            json={"url": url, "audio_only": audio_only}
        )
        data = r.json()
        # Then download file from data["download_url"]
        return data
```

---

Made for easy Telegram bot integration.
