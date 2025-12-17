import os
import json
import asyncio
import tempfile
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
import zipfile

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import uvicorn

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# Import your scraper modules
from main3 import (
    Config, ProgressTracker, create_session, 
    scrape_phase, load_json_file, sanitize_filename
)
from linkformat import LinksFormatter

# Supabase Integration
from supabase_config import SupabaseConfig, get_supabase_client
from supabase_storage import get_storage_service
from supabase_database import get_database_service
from supabase_realtime import get_realtime_service

# --- Configuration ---
class BotConfig:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-domain.com")
    PORT = int(os.getenv("PORT", 8000))
    ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    DOWNLOAD_DIR = Path("bot_downloads")
    
    # Supabase integration
    USE_SUPABASE = True
    
BotConfig.DOWNLOAD_DIR.mkdir(exist_ok=True)

# --- Pydantic Models ---
class SongSubmission(BaseModel):
    title: str
    artist: str
    url: HttpUrl
    event: Optional[str] = None

class BatchSubmission(BaseModel):
    songs: List[SongSubmission]

class ScrapeStatus(BaseModel):
    job_id: str
    status: str
    progress: Dict
    download_url: Optional[str] = None

# --- Conversation States ---
TITLE, ARTIST, URL, EVENT, CONFIRM = range(5)

# --- Supabase Services ---
storage_service = get_storage_service()
database_service = get_database_service()
realtime_service = get_realtime_service()

# --- Job Management (Updated for Supabase) ---
class JobManager:
    """Manages scraping jobs using Supabase Database."""
    
    def __init__(self):
        self.jobs: Dict[str, Dict] = {}
        self.lock = asyncio.Lock()
    
    async def create_job(self, user_id: int, songs_count: int) -> str:
        """Create a new scraping job in Supabase."""
        job_id = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        try:
            # Create job in database
            job_data = await database_service.create_job(user_id, job_id, songs_count)
            if job_data:
                async with self.lock:
                    self.jobs[job_id] = {
                        "job_id": job_id,
                        "user_id": user_id,
                        "status": "queued",
                        "total_songs": songs_count,
                        "progress": {"completed": 0, "failed": 0},
                        "created_at": datetime.now().isoformat(),
                        "download_url": None,
                        "storage_path": None
                    }
                return job_id
            else:
                raise Exception("Failed to create job in database")
                
        except Exception as e:
            print(f"❌ Error creating job: {e}")
            raise
    
    async def update_job(self, job_id: str, **kwargs):
        """Update job status in both memory and database."""
        async with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(kwargs)
        
        # Update in database
        try:
            await database_service.update_job(job_id, **kwargs)
        except Exception as e:
            print(f"⚠️  Warning: Could not update job in database: {e}")
    
    async def get_job(self, job_id: str) -> Optional[Dict]:
        """Get job details from memory cache."""
        async with self.lock:
            return self.jobs.get(job_id)
    
    async def list_user_jobs(self, user_id: int) -> List[Dict]:
        """List all jobs for a user from database."""
        try:
            db_jobs = await database_service.get_user_jobs(user_id)
            
            # Update local cache
            for job in db_jobs:
                job_id = job["job_id"]
                async with self.lock:
                    self.jobs[job_id] = job
            
            return db_jobs
            
        except Exception as e:
            print(f"❌ Error listing user jobs: {e}")
            return []

job_manager = JobManager()

# --- User Session Management (Updated for Supabase) ---
class UserSession:
    """Manages user session data using Supabase Database."""
    
    def __init__(self):
        self.sessions: Dict[int, Dict] = {}
        self.lock = asyncio.Lock()
    
    async def get_or_create(self, user_id: int) -> Dict:
        async with self.lock:
            if user_id not in self.sessions:
                # Try to get from database first
                try:
                    db_session = await database_service.get_or_create_user_session(user_id)
                    if db_session:
                        self.sessions[user_id] = db_session
                        return db_session
                except Exception as e:
                    print(f"⚠️  Warning: Could not get session from database: {e}")
                
                # Fallback to in-memory session
                self.sessions[user_id] = {
                    "id": f"local_{user_id}",
                    "user_id": user_id,
                    "current_song": {},
                    "song_queue": []
                }
            return self.sessions[user_id]
    
    async def add_song(self, user_id: int, song: Dict):
        session = await self.get_or_create(user_id)
        async with self.lock:
            session["song_queue"].append(song)
        
        # Update in database
        try:
            await database_service.update_user_session(
                session["id"], 
                song_queue=session["song_queue"]
            )
        except Exception as e:
            print(f"⚠️  Warning: Could not update session in database: {e}")
    
    async def clear_current(self, user_id: int):
        session = await self.get_or_create(user_id)
        async with self.lock:
            session["current_song"] = {}
    
    async def get_queue(self, user_id: int) -> List[Dict]:
        session = await self.get_or_create(user_id)
        async with self.lock:
            return session["song_queue"].copy()
    
    async def clear_queue(self, user_id: int):
        session = await self.get_or_create(user_id)
        async with self.lock:
            session["song_queue"] = []
        
        # Update in database
        try:
            await database_service.update_user_session(
                session["id"], 
                song_queue=[]
            )
        except Exception as e:
            print(f"⚠️  Warning: Could not update session in database: {e}")

user_sessions = UserSession()

# --- FastAPI App ---
app = FastAPI(title="Loveworld Scraper Bot API", version="2.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Loveworld Scraper Bot API with Supabase", "status": "running"}

@app.post("/api/scrape")
async def create_scrape_job(
    submission: BatchSubmission,
    background_tasks: BackgroundTasks,
    user_id: int = 0
):
    """Create a new scraping job from song submissions."""
    songs = [song.dict() for song in submission.songs]
    
    # Create job
    job_id = await job_manager.create_job(user_id, len(songs))
    
    # Save songs data to temporary file for processing
    temp_file = BotConfig.DOWNLOAD_DIR / f"temp_{user_id}_{datetime.now().timestamp()}.json"
    with open(temp_file, 'w') as f:
        json.dump(songs, f, indent=2)
    
    # Start scraping in background
    background_tasks.add_task(run_scraper, job_id, temp_file)
    
    return {"job_id": job_id, "status": "queued", "songs_count": len(songs)}

@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """Get the status of a scraping job."""
    job = await job_manager.get_job(job_id)
    if not job:
        # Try to get from database
        db_job = await database_service.get_job(job_id)
        if db_job:
            return db_job
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job

@app.get("/api/jobs/user/{user_id}")
async def get_user_jobs(user_id: int):
    """Get all jobs for a user."""
    jobs = await job_manager.list_user_jobs(user_id)
    return {"jobs": jobs}

@app.get("/api/download/{job_id}")
async def download_results(job_id: str):
    """Get download URL for completed job."""
    job = await database_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job not completed yet")
    
    if not job.get("download_url"):
        raise HTTPException(status_code=404, detail="Download not available")
    
    return {"download_url": job["download_url"]}

@app.websocket("/ws/job/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job updates."""
    await websocket.accept()
    
    try:
        # Subscribe to job updates
        channel_name = await realtime_service.subscribe_to_job_updates(
            job_id, 
            lambda update: websocket.send_json(update)
        )
        
        # Keep connection alive
        while True:
            await websocket.receive_text()
            
    except WebSocketDisconnect:
        await realtime_service.unsubscribe_from_channel(channel_name)

# --- Background Scraper with Supabase Integration ---
async def run_scraper(job_id: str, json_file: Path):
    """Background task to run the scraper with Supabase integration."""
    try:
        await job_manager.update_job(job_id, status="running")
        
        # Create progress tracking
        await database_service.create_progress_record(job_id, "lyrics")
        await database_service.create_progress_record(job_id, "audio")
        
        # Load songs
        json_data = load_json_file(str(json_file))
        if not json_data:
            await job_manager.update_job(job_id, status="failed", error="Invalid JSON file")
            await realtime_service.notify_job_error(job_id, "Invalid JSON file")
            return
        
        # Setup
        base_folder = BotConfig.DOWNLOAD_DIR / f"job_{job_id}"
        base_folder.mkdir(exist_ok=True)
        
        tracker = ProgressTracker(str(base_folder / "progress.json"))
        session = create_session()
        
        # Phase 1: Lyrics
        await realtime_service.notify_progress_update(job_id, {"phase": "lyrics", "status": "started"})
        lyrics_stats = await scrape_phase_with_supabase(
            json_data, session, tracker, base_folder, "lyrics", job_id
        )
        
        await database_service.update_job(job_id, 
            lyrics_completed=lyrics_stats["success"],
            lyrics_failed=lyrics_stats["failed"]
        )
        
        # Phase 2: Audio
        await realtime_service.notify_progress_update(job_id, {"phase": "audio", "status": "started"})
        audio_stats = await scrape_phase_with_supabase(
            json_data, session, tracker, base_folder, "audio", job_id
        )
        
        session.close()
        
        # Create ZIP archive and upload to Supabase Storage
        await realtime_service.notify_progress_update(job_id, {"phase": "archiving", "status": "started"})
        archive_result = await storage_service.create_archive_and_upload(str(base_folder), job_id)
        
        if archive_result:
            # Get signed URL for download
            download_url = await storage_service.get_signed_url(archive_result["storage_path"])
            
            # Update job with download information
            await database_service.set_job_download_url(job_id, download_url, archive_result["storage_path"])
            await job_manager.update_job(
                job_id,
                status="completed",
                download_url=download_url,
                storage_path=archive_result["storage_path"]
            )
            
            # Send completion notification
            await realtime_service.notify_job_completion(job_id, {
                "download_url": download_url,
                "lyrics_completed": lyrics_stats["success"],
                "audio_completed": audio_stats["success"]
            })
        else:
            await job_manager.update_job(job_id, status="failed", error="Failed to create archive")
            await realtime_service.notify_job_error(job_id, "Failed to create archive")
        
        # Cleanup
        json_file.unlink(missing_ok=True)
        
        # Clean up local files
        import shutil
        if base_folder.exists():
            shutil.rmtree(base_folder)
        
    except Exception as e:
        error_msg = str(e)
        await job_manager.update_job(job_id, status="failed", error=error_msg)
        await realtime_service.notify_job_error(job_id, error_msg)

async def scrape_phase_with_supabase(json_data: List[Dict], session, tracker, base_folder: Path, phase: str, job_id: str):
    """Scrape phase with Supabase integration for progress tracking."""
    stats = {
        "total": len(json_data),
        "success": 0,
        "skipped": 0,
        "failed": 0,
        "lyrics_saved": 0,
        "audio_saved": 0,
        "errors": []
    }
    
    try:
        for idx, item in enumerate(json_data):
            try:
                # Update progress in database
                await database_service.update_progress(
                    job_id, phase, idx, len(json_data), 
                    current_song_title=item.get("title", f"Unknown {idx}")
                )
                
                # Update progress via realtime
                progress_data = {
                    "phase": phase,
                    "current": idx + 1,
                    "total": len(json_data),
                    "percentage": ((idx + 1) / len(json_data)) * 100,
                    "current_song": item.get("title", "Unknown")
                }
                await realtime_service.notify_progress_update(job_id, progress_data)
                
                # Process song using existing logic
                from main3 import process_song
                result = process_song(item, session, tracker, base_folder, phase)
                
                # Store result in database
                if result["success"]:
                    stats["success"] += 1
                    await database_service.add_scraped_song(job_id, {
                        "title": item.get("title"),
                        "artist": item.get("artists"),
                        "url": item.get("url"),
                        "event": item.get("event"),
                        "lyrics_saved": result.get("lyrics_saved", False),
                        "audio_saved": result.get("audio_saved", False)
                    })
                    
                    if result.get("lyrics_saved"):
                        stats["lyrics_saved"] += 1
                    if result.get("audio_saved"):
                        stats["audio_saved"] += 1
                elif result.get("skip_reason"):
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1
                    error_msg = ", ".join(result["messages"]) if result["messages"] else "Unknown error"
                    stats["errors"].append(f"{item.get('title', 'Unknown')}: {error_msg}")
                
            except Exception as e:
                stats["failed"] += 1
                stats["errors"].append(f"{item.get('title', 'Unknown')}: {str(e)}")
        
        # Mark phase as completed
        await database_service.update_progress(job_id, phase, len(json_data), len(json_data), status="completed")
        
    except Exception as e:
        await database_service.update_progress(job_id, phase, 0, len(json_data), status="failed", error_details=str(e))
    
    return stats

# --- Telegram Bot Handlers (Updated for Supabase) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler."""
    user = update.effective_user
    
    # Create or update user in database
    try:
        await database_service.create_or_update_user(
            user.id, 
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
    except Exception as e:
        print(f"⚠️  Warning: Could not create user in database: {e}")
    
    welcome_text = f"""
👋 Welcome {user.first_name}!

I'm the Loveworld Scraper Bot with Supabase Cloud Storage. I can help you download song lyrics and audio from Loveworld.

📋 **Features:**

☁️ **Cloud Storage** - Files stored in Supabase with auto-deletion every hour
📊 **Real-time Updates** - Live progress tracking
🗄️ **Database** - Persistent job history
⚡ **Fast & Reliable** - Enhanced performance

**Options:**

1️⃣ **Upload Files:**
   • Send me a `links.json` file
   • Or send me an `input.txt` file

2️⃣ **Interactive Mode:**
   • Use /addsong to add songs one by one
   • Use /viewqueue to see your queue
   • Use /scrape to start downloading

3️⃣ **Quick Commands:**
   • /help - Show all commands
   • /status - Check your jobs
   • /cancel - Cancel current operation

Let's get started! 🎵
"""
    await update.message.reply_text(welcome_text)

# --- Bot Setup ---
def setup_bot():
    """Setup and return the bot application."""
    application = Application.builder().token(BotConfig.TELEGRAM_TOKEN).build()
    
    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("viewqueue", viewqueue))
    application.add_handler(CommandHandler("status", status_command))
    
    # File handler
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    
    # Conversation handler for adding songs
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("addsong", addsong_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)],
            ARTIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_artist)],
            URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)],
            EVENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_event)],
            CONFIRM: [CallbackQueryHandler(button_handler)]
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )
    application.add_handler(conv_handler)
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(button_handler))
    
    return application

# --- Main Execution ---
async def initialize_supabase_services():
    """Initialize Supabase services."""
    try:
        print("🔄 Initializing Supabase services...")
        
        # Initialize storage
        await storage_service.initialize_bucket()
        await storage_service.start_auto_cleanup_scheduler()
        
        # Initialize realtime
        await realtime_service.initialize_realtime()
        
        print("✅ Supabase services initialized successfully")
        
    except Exception as e:
        print(f"❌ Error initializing Supabase services: {e}")

if __name__ == "__main__":
    import sys
    
    async def startup():
        """Startup event handler."""
        await initialize_supabase_services()
        
        if len(sys.argv) > 1 and sys.argv[1] == "bot":
            # Run as polling bot (for development)
            print("🤖 Starting Telegram Bot (Polling Mode)...")
            bot_app = setup_bot()
            await bot_app.initialize()
            await bot_app.start()
            bot_app.run_polling()
        else:
            # Run FastAPI with webhook
            print("🚀 Starting FastAPI Server with Supabase Integration...")
            print(f"📡 Webhook URL: {BotConfig.WEBHOOK_URL}")
            
            @app.on_event("startup")
            async def startup_event():
                bot_app = setup_bot()
                await bot_app.initialize()
                try:
                    await bot_app.bot.set_webhook(f"{BotConfig.WEBHOOK_URL}/webhook")
                    print("✅ Webhook set successfully")
                except Exception as e:
                    print(f"⚠️  Warning: Could not set webhook: {e}")
            
            @app.post("/webhook")
            async def webhook(update: dict):
                bot_app = setup_bot()
                await bot_app.initialize()
                await bot_app.bot.set_webhook(f"{BotConfig.WEBHOOK_URL}/webhook")
                await bot_app.process_update(Update.de_json(update, bot_app.bot))
                return {"ok": True}
            
            uvicorn.run(app, host="0.0.0.0", port=BotConfig.PORT)
    
    # Run startup
    asyncio.run(startup())