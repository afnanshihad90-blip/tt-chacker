import os
import uuid
import asyncio
import shutil
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import yt_dlp
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="YTDown Backend v2",
    description="Video downloader & info API for Telegram bots (TikTok, YouTube, Instagram, etc.)",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Temporary download directory
TEMP_DIR = Path("temp_downloads")
TEMP_DIR.mkdir(exist_ok=True)

# Auto cleanup after X minutes
CLEANUP_MINUTES = int(os.getenv("CLEANUP_MINUTES", "15"))


class VideoRequest(BaseModel):
    url: str
    format_id: Optional[str] = None  # specific format, or "best", "bestaudio"
    audio_only: bool = False


class InfoResponse(BaseModel):
    id: str
    title: str
    uploader: Optional[str] = None
    duration: Optional[float] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    thumbnail: Optional[str] = None
    description: Optional[str] = None
    webpage_url: str
    extractor: str
    formats: List[dict]


def get_ydl_opts(download: bool = False, format_id: str = "best", audio_only: bool = False, outtmpl: str = None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "extractor_args": {
            "tiktok": {"api_hostname": "api16-normal-c-useast1a.tiktokv.com"},
            "youtube": {"player_client": ["android", "web"]},
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.tiktok.com/",
        },
    }

    if download:
        if outtmpl:
            opts["outtmpl"] = outtmpl
        if audio_only:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        elif format_id and format_id not in ["best", "bestaudio"]:
            opts["format"] = format_id
        else:
            # Prefer mp4 high quality
            opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
            opts["merge_output_format"] = "mp4"

    return opts


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "YTDown Backend v2",
        "endpoints": {
            "GET /health": "Health check",
            "POST /info": "Get video metadata & available formats",
            "POST /download": "Download video/audio and get file",
            "GET /download/{file_id}": "Direct download by file id"
        }
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "ytdown-backend-v2"}


@app.post("/info")
async def get_info(req: VideoRequest):
    """Get video information and available formats without downloading."""
    try:
        ydl_opts = get_ydl_opts(download=False)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)

        if not info:
            raise HTTPException(status_code=400, detail="Could not extract video info")

        formats = []
        for f in info.get("formats", []):
            # Filter useful formats
            if f.get("vcodec") != "none" or f.get("acodec") != "none":
                formats.append({
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "resolution": f.get("resolution") or f.get("format_note"),
                    "fps": f.get("fps"),
                    "vcodec": f.get("vcodec"),
                    "acodec": f.get("acodec"),
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "format_note": f.get("format_note"),
                    "url": f.get("url") if f.get("protocol") in ["https", "http"] else None,
                })

        return {
            "id": info.get("id"),
            "title": info.get("title"),
            "uploader": info.get("uploader") or info.get("creator") or info.get("channel"),
            "duration": info.get("duration"),
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "comment_count": info.get("comment_count"),
            "repost_count": info.get("repost_count"),
            "thumbnail": info.get("thumbnail"),
            "description": (info.get("description") or "")[:500],
            "webpage_url": info.get("webpage_url") or req.url,
            "extractor": info.get("extractor"),
            "upload_date": info.get("upload_date"),
            "formats": formats[:30],  # limit
            "original_url": req.url
        }
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Download error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/download")
async def download_video(req: VideoRequest, background_tasks: BackgroundTasks):
    """Download video/audio and return a temporary download link."""
    file_id = str(uuid.uuid4())
    out_dir = TEMP_DIR / file_id
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        outtmpl = str(out_dir / "%(title).80s.%(ext)s")
        ydl_opts = get_ydl_opts(
            download=True,
            format_id=req.format_id or "best",
            audio_only=req.audio_only,
            outtmpl=outtmpl
        )

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)

        # Find the downloaded file
        files = list(out_dir.glob("*"))
        if not files:
            raise HTTPException(status_code=500, detail="Download failed - no file created")

        downloaded_file = files[0]
        # Rename to clean name
        ext = downloaded_file.suffix
        clean_name = f"{file_id}{ext}"
        final_path = TEMP_DIR / clean_name
        shutil.move(str(downloaded_file), str(final_path))
        shutil.rmtree(out_dir, ignore_errors=True)

        # Schedule cleanup
        background_tasks.add_task(cleanup_file, final_path, CLEANUP_MINUTES * 60)

        filesize = final_path.stat().st_size

        return {
            "success": True,
            "file_id": file_id,
            "filename": final_path.name,
            "ext": ext.lstrip("."),
            "filesize": filesize,
            "filesize_mb": round(filesize / (1024 * 1024), 2),
            "title": info.get("title"),
            "download_url": f"/download/{file_id}",
            "direct_url": f"/file/{file_id}"
        }
    except Exception as e:
        # Cleanup on error
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@app.get("/download/{file_id}")
@app.get("/file/{file_id}")
async def serve_file(file_id: str):
    """Serve the downloaded file."""
    # Find file by prefix
    matches = list(TEMP_DIR.glob(f"{file_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="File not found or expired")

    file_path = matches[0]
    media_type = "video/mp4"
    if file_path.suffix == ".mp3":
        media_type = "audio/mpeg"
    elif file_path.suffix == ".webm":
        media_type = "video/webm"
    elif file_path.suffix == ".m4a":
        media_type = "audio/mp4"

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=file_path.name,
        background=None
    )


async def cleanup_file(path: Path, delay_seconds: int):
    """Delete file after delay."""
    await asyncio.sleep(delay_seconds)
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


# Optional: simple TikTok-specific endpoint for quick info
@app.get("/tiktok")
async def tiktok_info(url: str = Query(..., description="TikTok video URL")):
    req = VideoRequest(url=url)
    return await get_info(req)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
