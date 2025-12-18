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
from contextlib import asynccontextmanager
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
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    # Startup
    await initialize_supabase_services()
    yield
    # Shutdown (if needed)

app = FastAPI(title="Loveworld Scraper Bot API", version="2.0.0", lifespan=lifespan)

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
async def run_scraper(job_id: str, songs_data: List[Dict]):
    """Background task to run the scraper with Supabase integration."""
    try:
        await job_manager.update_job(job_id, status="running")
        
        # Create progress tracking
        await database_service.create_progress_record(job_id, "lyrics")
        await database_service.create_progress_record(job_id, "audio")
        
        # Validate songs data
        if not songs_data:
            await job_manager.update_job(job_id, status="failed")
            await realtime_service.notify_job_error(job_id, "Invalid or empty songs data")
            return
        
        # Setup
        base_folder = BotConfig.DOWNLOAD_DIR / f"job_{job_id}"
        base_folder.mkdir(exist_ok=True)
        
        tracker = ProgressTracker(str(base_folder / "progress.json"))
        session = create_session()
        
        # Phase 1: Lyrics
        await realtime_service.notify_progress_update(job_id, {"phase": "lyrics", "status": "started"})
        lyrics_stats = await scrape_phase_with_supabase(
            songs_data, session, tracker, base_folder, "lyrics", job_id
        )
        
        await database_service.update_job(job_id, 
            lyrics_completed=lyrics_stats["success"],
            lyrics_failed=lyrics_stats["failed"]
        )
        
        # Phase 2: Audio
        await realtime_service.notify_progress_update(job_id, {"phase": "audio", "status": "started"})
        audio_stats = await scrape_phase_with_supabase(
            songs_data, session, tracker, base_folder, "audio", job_id
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
            await job_manager.update_job(job_id, status="failed")
            await realtime_service.notify_job_error(job_id, "Failed to create archive")
        
        # Clean up local files
        import shutil
        if base_folder.exists():
            shutil.rmtree(base_folder)
        
    except Exception as e:
        error_msg = str(e)
        await job_manager.update_job(job_id, status="failed")
        await realtime_service.notify_job_error(job_id, error_msg)
        print(f"❌ Error in run_scraper: {error_msg}")
        import traceback
        traceback.print_exc()

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
    print(f"📨 Received /start from user {update.effective_user.id}")
    user = update.effective_user

    # Create or update user in database
    try:
        await database_service.create_or_update_user(
            user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        print(f"✅ User {user.id} created/updated in database")
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
    print(f"📤 Sent welcome message to user {user.id}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler."""
    print(f"📨 Received /help from user {update.effective_user.id}")
    help_text = """
🆘 **Available Commands:**

**📋 Basic Commands:**
/start - Start the bot & see welcome message
/help - Show this help message
/cancel - Cancel current operation

**🎵 Song Management:**
/addsong - Add a song interactively to your queue
/viewqueue - View your current song queue
/scrape - Start scraping your queue
/clearqueue - Clear your entire queue

**📊 Job Management:**
/status - Check status of recent jobs
/myjobs - View all your job history with download links

**📁 File Upload:**
Just send me a `links.json` or `input.txt` file and I'll process it automatically!

**💡 Workflow Tips:**

**Method 1: File Upload** (Fastest)
1️⃣ Send me your `links.json` or `input.txt` file
2️⃣ Click "✅ Start Scraping" when ready
3️⃣ Wait for completion notification
4️⃣ Download your files from Supabase cloud storage

**Method 2: Interactive Mode**
1️⃣ Use /addsong to add songs one by one
2️⃣ Use /viewqueue to review your queue
3️⃣ Use /scrape to start downloading
4️⃣ Use /status to check progress

**⚡ Features:**
☁️ Cloud storage with auto-cleanup every hour
📊 Real-time progress tracking
🗄️ Persistent job history
🔄 Resume capability for failed downloads
"""
    await update.message.reply_text(help_text)
    print(f"📤 Sent help message to user {update.effective_user.id}")

async def viewqueue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View current song queue."""
    user_id = update.effective_user.id
    queue = await user_sessions.get_queue(user_id)

    if not queue:
        await update.message.reply_text("📭 Your queue is empty. Use /addsong to add songs!")
        return

    message = f"📋 **Your Queue ({len(queue)} songs):**\n\n"
    for i, song in enumerate(queue, 1):
        message += f"{i}. {song['title']} - {song['artists']}\n"

    keyboard = [
        [InlineKeyboardButton("🚀 Start Scraping", callback_data="scrape_queue")],
        [InlineKeyboardButton("🗑️ Clear Queue", callback_data="clear_queue")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(message, reply_markup=reply_markup)

async def scrape_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start scraping the current queue."""
    user_id = update.effective_user.id
    queue = await user_sessions.get_queue(user_id)

    if not queue:
        await update.message.reply_text("📭 Your queue is empty. Use /addsong to add songs first!")
        return

    # Save queue as JSON
    # No longer saving to local file - keeping in memory only
    
    # Create job
    job_id = await job_manager.create_job(user_id, len(queue))

    # Show confirmation
    keyboard = [
        [InlineKeyboardButton("✅ Start Now", callback_data=f"scrape_{job_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{job_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🎵 Ready to scrape {len(queue)} songs!\n\n"
        f"📋 Preview:\n" +
        "\n".join([f"• {s['title']} - {s['artists']}" for s in queue[:5]]) +
        (f"\n... and {len(queue) - 5} more" if len(queue) > 5 else ""),
        reply_markup=reply_markup
    )

    # Store job metadata
    context.user_data[f"job_{job_id}"] = {"songs_data": queue}

async def clearqueue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear the current song queue."""
    user_id = update.effective_user.id
    await user_sessions.clear_queue(user_id)
    await update.message.reply_text("✅ Queue cleared successfully!")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation."""
    await update.message.reply_text(
        "❌ Operation cancelled.\n\n"
        "Use /help to see available commands."
    )
    return ConversationHandler.END

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics (Admin only)."""
    user_id = update.effective_user.id
    
    if user_id not in BotConfig.ADMIN_IDS and BotConfig.ADMIN_IDS:
        await update.message.reply_text("⛔ This command is for admins only.")
        return
    
    try:
        # Get database stats
        all_jobs = await database_service.get_all_jobs_count()
        completed_jobs = await database_service.get_completed_jobs_count()
        total_users = await database_service.get_total_users_count()
        
        message = (
            "📊 **Bot Statistics**\n\n"
            f"👥 Total Users: {total_users}\n"
            f"📋 Total Jobs: {all_jobs}\n"
            f"✅ Completed Jobs: {completed_jobs}\n"
            f"🔄 Success Rate: {(completed_jobs/all_jobs*100):.1f}%\n" if all_jobs > 0 else "🔄 Success Rate: N/A\n"
        )
        
        await update.message.reply_text(message)
    except Exception as e:
        await update.message.reply_text(f"❌ Error fetching stats: {str(e)}")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all users (Admin only)."""
    user_id = update.effective_user.id
    
    if user_id not in BotConfig.ADMIN_IDS and BotConfig.ADMIN_IDS:
        await update.message.reply_text("⛔ This command is for admins only.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "📢 **Broadcast Command**\n\n"
            "Usage: /broadcast <your message>\n\n"
            "Example: /broadcast Bot will be down for maintenance at 10 PM"
        )
        return
    
    message = " ".join(context.args)
    
    try:
        all_users = await database_service.get_all_user_ids()
        success = 0
        failed = 0
        
        await update.message.reply_text(f"📤 Broadcasting to {len(all_users)} users...")
        
        for uid in all_users:
            try:
                await context.bot.send_message(uid, f"📢 **Announcement**\n\n{message}")
                success += 1
                await asyncio.sleep(0.05)  # Rate limiting
            except Exception:
                failed += 1
        
        await update.message.reply_text(
            f"✅ Broadcast complete!\n\n"
            f"✅ Sent: {success}\n"
            f"❌ Failed: {failed}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error broadcasting: {str(e)}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check job status."""
    user_id = update.effective_user.id
    jobs = await job_manager.list_user_jobs(user_id)

    if not jobs:
        await update.message.reply_text("📭 No jobs found. Upload a file or use /addsong to get started!")
        return

    message = "📊 **Your Recent Jobs:**\n\n"
    for job in jobs[-5:]:  # Show last 5 jobs
        status_emoji = {
            "completed": "✅",
            "running": "⏳",
            "failed": "❌",
            "queued": "📋",
            "cancelled": "🚫"
        }.get(job['status'], "❓")
        
        message += (
            f"{status_emoji} **Job {job['job_id'][-8:]}**\n"
            f"   Status: {job['status'].upper()}\n"
            f"   Songs: {job['total_songs']}\n"
        )
        
        if job['status'] == 'completed' and job.get('download_url'):
            message += f"   [Download Ready]({job['download_url']})\n"
        
        message += f"\n"

    await update.message.reply_text(message)

async def myjobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all user jobs with detailed info."""
    user_id = update.effective_user.id
    jobs = await job_manager.list_user_jobs(user_id)

    if not jobs:
        await update.message.reply_text("📭 No jobs found.")
        return

    message = "📂 **All Your Jobs:**\n\n"
    for i, job in enumerate(jobs[-10:], 1):  # Last 10 jobs
        status_emoji = {
            "completed": "✅",
            "running": "⏳",
            "failed": "❌",
            "queued": "📋",
            "cancelled": "🚫"
        }.get(job['status'], "❓")
        
        message += f"{i}. {status_emoji} `{job['job_id']}`\n"
        message += f"   📅 {job['created_at'][:10]}\n"
        message += f"   🎵 {job['total_songs']} songs | Status: {job['status']}\n"
        
        if job.get('lyrics_completed') or job.get('audio_completed'):
            message += f"   📝 {job.get('lyrics_completed', 0)} lyrics | 🎧 {job.get('audio_completed', 0)} audio\n"
        
        if job['status'] == 'completed' and job.get('download_url'):
            keyboard = [[InlineKeyboardButton("📥 Download", url=job['download_url'])]]
            reply_markup = InlineKeyboardMarkup(keyboard)
        
        message += "\n"

    await update.message.reply_text(message, parse_mode='Markdown')

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads (JSON or TXT) - Upload directly to Supabase."""
    file = await update.message.document.get_file()
    file_name = update.message.document.file_name
    user_id = update.effective_user.id

    # Check file size
    if update.message.document.file_size > BotConfig.MAX_FILE_SIZE:
        await update.message.reply_text("❌ File too large! Maximum size is 10MB.")
        return

    await update.message.reply_text("⏳ Processing your file...")

    try:
        # Download file to memory first
        file_bytes = await file.download_as_bytearray()
        
        # Process based on file type
        if file_name.endswith('.json'):
            # Parse JSON from bytes
            import json
            songs = json.loads(file_bytes.decode('utf-8'))
        elif file_name.endswith('.txt'):
            # Convert TXT to JSON
            text = file_bytes.decode('utf-8')
            formatter = LinksFormatter()
            songs = formatter.parse_text(text)
        else:
            await update.message.reply_text("❌ Unsupported file type. Send .json or .txt files only.")
            return

        if not songs:
            await update.message.reply_text("❌ No valid songs found in file.")
            return

        # Create job first to get job_id
        job_id = await job_manager.create_job(user_id, len(songs))
        
        # Convert songs to JSON bytes
        json_data = json.dumps(songs, indent=2).encode('utf-8')
        
        # Upload JSON to Supabase Storage
        upload_result = await storage_service.upload_file_from_bytes(
            json_data,
            f"songs_{job_id}.json",
            job_id,
            file_type="temp",
            mime_type="application/json"
        )
        
        if not upload_result:
            await update.message.reply_text("❌ Failed to upload file to storage. Please try again.")
            return
        
        storage_path = upload_result["storage_path"]

        # Show confirmation
        keyboard = [
            [InlineKeyboardButton("✅ Start Scraping", callback_data=f"scrape_{job_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{job_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"✅ Found {len(songs)} songs!\n\n"
            f"📋 Preview:\n" +
            "\n".join([f"• {s['title']} - {s['artists']}" for s in songs[:5]]) +
            (f"\n... and {len(songs) - 5} more" if len(songs) > 5 else ""),
            reply_markup=reply_markup
        )

        # Store job metadata with storage path and songs data
        context.user_data[f"job_{job_id}"] = {
            "storage_path": storage_path,
            "songs_data": songs  # Store in memory for quick access
        }

    except Exception as e:
        await update.message.reply_text(f"❌ Error processing file: {str(e)}")
        print(f"❌ File processing error: {e}")
        import traceback
        traceback.print_exc()

async def addsong_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start interactive song addition."""
    await update.message.reply_text(
        "🎵 Let's add a song!\n\n"
        "First, send me the **song title**:"
    )
    return TITLE

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive song title."""
    session = await user_sessions.get_or_create(update.effective_user.id)
    session["current_song"]["title"] = update.message.text

    await update.message.reply_text(
        f"✅ Title: {update.message.text}\n\n"
        "Now send me the **artist name**:"
    )
    return ARTIST

async def receive_artist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive artist name."""
    session = await user_sessions.get_or_create(update.effective_user.id)
    session["current_song"]["artists"] = f"{update.message.text} and Loveworld Singers"

    await update.message.reply_text(
        f"✅ Artist: {update.message.text}\n\n"
        "Now send me the **URL** to the song page:"
    )
    return URL

async def receive_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive song URL."""
    url = update.message.text
    if not url.startswith('http'):
        await update.message.reply_text("❌ Invalid URL. Please send a valid URL starting with http:// or https://")
        return URL

    session = await user_sessions.get_or_create(update.effective_user.id)
    session["current_song"]["url"] = url

    # Extract event from URL
    formatter = LinksFormatter()
    event = formatter.extract_event_from_url(url)

    keyboard = [
        [InlineKeyboardButton("✅ Confirm & Add", callback_data="confirm_add")],
        [InlineKeyboardButton("🔄 Add Event Name", callback_data="add_event")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_add")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    summary = (
        f"📝 **Song Summary:**\n\n"
        f"Title: {session['current_song']['title']}\n"
        f"Artist: {session['current_song']['artists']}\n"
        f"URL: {url}\n"
    )

    if event:
        summary += f"Event: {event} (auto-detected)\n"
        session["current_song"]["event"] = event

    await update.message.reply_text(summary, reply_markup=reply_markup)
    return CONFIRM

async def receive_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive optional event name."""
    session = await user_sessions.get_or_create(update.effective_user.id)
    session["current_song"]["event"] = update.message.text

    keyboard = [
        [InlineKeyboardButton("✅ Confirm & Add", callback_data="confirm_add")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_add")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"✅ Event: {update.message.text}\n\n"
        "Ready to add this song?",
        reply_markup=reply_markup
    )
    return CONFIRM

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = query.data

    # Scrape job from file upload
    if data.startswith("scrape_"):
        job_id = data.replace("scrape_", "")
        job_meta = context.user_data.get(f"job_{job_id}")

        if not job_meta:
            await query.edit_message_text("❌ Job not found.")
            return

        await query.edit_message_text("🚀 Starting scraper... This may take a while.\n\n⏳ You'll receive updates as the job progresses.")

        # Get songs data from memory
        songs_data = job_meta.get("songs_data")
        if not songs_data:
            await query.edit_message_text("❌ Songs data not found. Please upload the file again.")
            return
        
        # Start scraping with songs data
        asyncio.create_task(run_scraper(job_id, songs_data))

        # Send progress updates
        asyncio.create_task(send_progress_updates(context, query.message.chat_id, job_id))

    # Scrape queue
    elif data == "scrape_queue":
        queue = await user_sessions.get_queue(user_id)
        
        if not queue:
            await query.edit_message_text("📭 Queue is empty!")
            return
        
        # Create job
        job_id = await job_manager.create_job(user_id, len(queue))
        context.user_data[f"job_{job_id}"] = {"songs_data": queue}

        await query.edit_message_text("🚀 Starting scraper... Processing your queue.\n\n⏳ You'll receive updates soon.")

        # Start scraping with songs data
        asyncio.create_task(run_scraper(job_id, queue))
        asyncio.create_task(send_progress_updates(context, query.message.chat_id, job_id))
        
        # Clear queue after starting
        await user_sessions.clear_queue(user_id)

    # Clear queue
    elif data == "clear_queue":
        await user_sessions.clear_queue(user_id)
        await query.edit_message_text("✅ Queue cleared successfully!")

    # Cancel job
    elif data.startswith("cancel_"):
        job_id = data.replace("cancel_", "")
        await query.edit_message_text("❌ Job cancelled.")
        await job_manager.update_job(job_id, status="cancelled")

    # Confirm add song
    elif data == "confirm_add":
        session = await user_sessions.get_or_create(user_id)
        await user_sessions.add_song(user_id, session["current_song"])
        await user_sessions.clear_current(user_id)

        queue = await user_sessions.get_queue(user_id)

        await query.edit_message_text(
            f"✅ Song added to queue!\n\n"
            f"Queue size: {len(queue)} songs\n\n"
            "Use /addsong to add more or /scrape to start downloading."
        )
        return ConversationHandler.END

    # Add event
    elif data == "add_event":
        await query.edit_message_text("Send me the event name (e.g., 'Praise Night 25'):")
        return EVENT

    # Cancel add
    elif data == "cancel_add":
        await user_sessions.clear_current(user_id)
        await query.edit_message_text("❌ Song addition cancelled.")
        return ConversationHandler.END

async def send_progress_updates(context: ContextTypes.DEFAULT_TYPE, chat_id: int, job_id: str):
    """Send periodic progress updates."""
    while True:
        await asyncio.sleep(10)  # Update every 10 seconds

        job = await job_manager.get_job(job_id)
        if not job:
            break

        if job["status"] == "completed":
            download_url = f"{BotConfig.WEBHOOK_URL}/api/download/{job_id}"
            await context.bot.send_message(
                chat_id,
                f"✅ **Download Complete!**\n\n"
                f"Lyrics: {job['progress'].get('lyrics_completed', 0)} completed\n"
                f"Audio: {job['progress'].get('audio_completed', 0)} completed\n\n"
                f"Download your files: {download_url}"
            )
            break

        elif job["status"] == "failed":
            await context.bot.send_message(
                chat_id,
                f"❌ **Scraping Failed**\n\n"
                f"Error: {job.get('error', 'Unknown error')}"
            )
            break

        elif job["status"] == "running":
            progress = job.get("progress", {})
            await context.bot.send_message(
                chat_id,
                f"⏳ **In Progress...**\n\n"
                f"Lyrics: {progress.get('lyrics_completed', 0)} / {job['total_songs']}\n"
                f"Status: {job['status']}"
            )

# --- Bot Setup ---
def setup_bot():
    """Setup and return the bot application."""
    print("🔧 Setting up bot handlers...")
    application = Application.builder().token(BotConfig.TELEGRAM_TOKEN).build()
    
    # Commands
    application.add_handler(CommandHandler("start", start))
    print("  ✅ Registered /start handler")
    application.add_handler(CommandHandler("help", help_command))
    print("  ✅ Registered /help handler")
    application.add_handler(CommandHandler("addsong", addsong_start))
    print("  ✅ Registered /addsong handler")
    application.add_handler(CommandHandler("viewqueue", viewqueue))
    print("  ✅ Registered /viewqueue handler")
    application.add_handler(CommandHandler("scrape", scrape_queue))
    print("  ✅ Registered /scrape handler")
    application.add_handler(CommandHandler("clearqueue", clearqueue))
    print("  ✅ Registered /clearqueue handler")
    application.add_handler(CommandHandler("status", status_command))
    print("  ✅ Registered /status handler")
    application.add_handler(CommandHandler("myjobs", myjobs))
    print("  ✅ Registered /myjobs handler")
    application.add_handler(CommandHandler("cancel", cancel_command))
    print("  ✅ Registered /cancel handler")
    
    # Admin commands
    if BotConfig.ADMIN_IDS:
        application.add_handler(CommandHandler("stats", stats_command))
        print("  ✅ Registered /stats handler (admin)")
        application.add_handler(CommandHandler("broadcast", broadcast_command))
        print("  ✅ Registered /broadcast handler (admin)")
    
    # File handler
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    print("  ✅ Registered file handler")

    # General message handler for debugging
    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle general text messages for debugging."""
        print(f"📨 Received text message: '{update.message.text}' from user {update.effective_user.id}")
        await update.message.reply_text("I received your message! Try /start or /help for commands.")

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("  ✅ Registered text message handler")
    
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
        fallbacks=[CommandHandler("cancel", cancel_command)],
        per_user=True,
        per_chat=True
    )
    application.add_handler(conv_handler)
    print("  ✅ Registered conversation handler for /addsong")
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(button_handler))
    print("  ✅ Registered callback query handler")
    
    print(f"✅ Bot setup complete with {len(application.handlers[0])} handlers")
    
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

    if len(sys.argv) > 1 and sys.argv[1] == "bot":
        # Run as polling bot (for development)
        print("🤖 Starting Telegram Bot (Polling Mode)...")

        async def run_bot():
            # Verify token first
            if BotConfig.TELEGRAM_TOKEN == "YOUR_BOT_TOKEN_HERE":
                print("❌ ERROR: TELEGRAM_BOT_TOKEN not set!")
                print("Please set the TELEGRAM_BOT_TOKEN environment variable.")
                return
            
            print(f"🔑 Using token: {BotConfig.TELEGRAM_TOKEN[:10]}...")
            
            await initialize_supabase_services()
            bot_app = setup_bot()
            
            print("🔧 Initializing bot application...")
            await bot_app.initialize()
            
            print("🚀 Starting bot polling...")
            await bot_app.start()
            
            print("✅ Bot is now running. Press Ctrl+C to stop.")
            print(f"📱 Bot username: @{(await bot_app.bot.get_me()).username}")
            
            try:
                await bot_app.updater.start_polling(drop_pending_updates=True)
                
                # Keep the bot running
                import signal
                stop_event = asyncio.Event()
                
                def signal_handler(sig, frame):
                    print("\n⚠️ Received stop signal, shutting down...")
                    stop_event.set()
                
                signal.signal(signal.SIGINT, signal_handler)
                signal.signal(signal.SIGTERM, signal_handler)
                
                await stop_event.wait()
                
            except KeyboardInterrupt:
                print("\n⚠️ Received keyboard interrupt, shutting down...")
            finally:
                print("🛑 Stopping bot...")
                await bot_app.updater.stop()
                await bot_app.stop()
                await bot_app.shutdown()
                print("✅ Bot stopped successfully")

        try:
            asyncio.run(run_bot())
        except KeyboardInterrupt:
            print("\n👋 Bot shutdown complete")
    else:
        # Run FastAPI with webhook
        print("🚀 Starting FastAPI Server with Supabase Integration...")
        print(f"📡 Webhook URL: {BotConfig.WEBHOOK_URL}")

        @app.post("/webhook")
        async def webhook(update: dict):
            # Create bot app instance for webhook handling
            bot_app = setup_bot()
            await bot_app.initialize()
            try:
                await bot_app.bot.set_webhook(f"{BotConfig.WEBHOOK_URL}/webhook")
            except Exception as e:
                print(f"⚠️  Warning: Could not set webhook: {e}")
            await bot_app.process_update(Update.de_json(update, bot_app.bot))
            return {"ok": True}

        uvicorn.run(app, host="0.0.0.0", port=BotConfig.PORT)