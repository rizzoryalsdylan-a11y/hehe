#!/usr/bin/env python3
import os
import json
import tempfile
import subprocess
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "yt_downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

class InfoRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    format_id: str

def run_yt_dlp(args: list, timeout: int = 300) -> dict:
    """Run yt-dlp command and return result"""
    try:
        result = subprocess.run(
            ["yt-dlp"] + args,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode != 0:
            raise Exception(result.stderr or "yt-dlp command failed")
        return {"success": True, "output": result.stdout, "error": None}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Download timeout - video too large")
    except Exception as e:
        logger.error(f"yt-dlp error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/info")
async def get_info(req: InfoRequest):
    """Get video info without cookies"""
    try:
        # Use yt-dlp to extract info in JSON format
        result = run_yt_dlp([
            "-j",
            "--no-warnings",
            "--socket-timeout", "30",
            req.url
        ], timeout=60)
        
        info = json.loads(result["output"])
        
        # Extract formats
        formats = []
        seen = set()
        
        # Video formats
        if "formats" in info:
            for fmt in info["formats"]:
                if fmt.get("vcodec") != "none" and fmt.get("acodec") != "none":
                    key = (fmt.get("height"), fmt.get("ext"))
                    if key not in seen:
                        seen.add(key)
                        height = fmt.get("height", "unknown")
                        ext = fmt.get("ext", "mp4")
                        filesize = fmt.get("filesize", 0)
                        formats.append({
                            "format_id": fmt["format_id"],
                            "label": f"{height}p",
                            "type": "video",
                            "filesize": filesize,
                            "ext": ext
                        })
        
        # Audio formats
        if "formats" in info:
            for fmt in info["formats"]:
                if fmt.get("vcodec") == "none" and fmt.get("acodec") != "none":
                    key = ("audio", fmt.get("ext"))
                    if key not in seen:
                        seen.add(key)
                        filesize = fmt.get("filesize", 0)
                        ext = fmt.get("ext", "m4a")
                        formats.append({
                            "format_id": fmt["format_id"],
                            "label": "Audio",
                            "type": "audio",
                            "filesize": filesize,
                            "ext": ext
                        })
        
        # Sort: video by quality (descending), then audio
        video_fmts = [f for f in formats if f["type"] == "video"]
        audio_fmts = [f for f in formats if f["type"] == "audio"]
        video_fmts.sort(key=lambda x: int(x["label"].rstrip("p")) if x["label"] != "unknown" else 0, reverse=True)
        formats = video_fmts[:5] + audio_fmts[:2]
        
        return {
            "title": info.get("title", "Unknown"),
            "channel": info.get("channel", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "formats": formats
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching info: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Failed to fetch video info: {str(e)}")

@app.post("/api/download")
async def download_video(req: DownloadRequest):
    """Download video without cookies"""
    try:
        # Generate output filename
        output_template = str(DOWNLOAD_DIR / "%(title)s.%(ext)s")
        
        # Use yt-dlp to download
        result = run_yt_dlp([
            "-f", req.format_id,
            "-o", output_template,
            "--no-warnings",
            "--socket-timeout", "30",
            req.url
        ], timeout=600)
        
        # Find the downloaded file
        files = list(DOWNLOAD_DIR.glob("*"))
        if not files:
            raise Exception("Download completed but file not found")
        
        latest_file = max(files, key=os.path.getctime)
        
        return {
            "filename": latest_file.name,
            "path": str(latest_file)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Download failed: {str(e)}")

@app.get("/api/file/{filename}")
async def get_file(filename: str):
    """Serve downloaded file"""
    try:
        file_path = DOWNLOAD_DIR / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/octet-stream"
        )
    except Exception as e:
        logger.error(f"Error serving file: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

# Serve static files AFTER API routes so they don't intercept
app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
