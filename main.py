import os
import json
import asyncio
import tempfile
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, FileResponse
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

# --- Configuration ---
class BotConfig:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-domain.com")
    PORT = int(os.getenv("PORT", 8000))
    ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    DOWNLOAD_DIR = Path("bot_downloads")
    
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

# --- Job Management ---
class JobManager:
    """Manages scraping jobs and their status."""
    
    def __init__(self):
        self.jobs: Dict[str, Dict] = {}
        self.lock = asyncio.Lock()
    
    async def create_job(self, user_id: int, songs_count: int) -> str:
        """Create a new scraping job."""
        job_id = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        async with self.lock:
            self.jobs[job_id] = {
                "user_id": user_id,
                "status": "queued",
                "total_songs": songs_count,
                "progress": {"completed": 0, "failed": 0},
                "created_at": datetime.now().isoformat(),
                "download_path": None
            }
        return job_id
    
    async def update_job(self, job_id: str, **kwargs):
        """Update job status."""
        async with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(kwargs)
    
    async def get_job(self, job_id: str) -> Optional[Dict]:
        """Get job details."""
        async with self.lock:
            return self.jobs.get(job_id)
    
    async def list_user_jobs(self, user_id: int) -> List[Dict]:
        """List all jobs for a user."""
        async with self.lock:
            return [
                {"job_id": jid, **details} 
                for jid, details in self.jobs.items() 
                if details["user_id"] == user_id
            ]

job_manager = JobManager()

# --- User Session Management ---
class UserSession:
    """Manages user session data for interactive submissions."""
    
    def __init__(self):
        self.sessions: Dict[int, Dict] = {}
        self.lock = asyncio.Lock()
    
    async def get_or_create(self, user_id: int) -> Dict:
        async with self.lock:
            if user_id not in self.sessions:
                self.sessions[user_id] = {
                    "current_song": {},
                    "song_queue": []
                }
            return self.sessions[user_id]
    
    async def add_song(self, user_id: int, song: Dict):
        session = await self.get_or_create(user_id)
        async with self.lock:
            session["song_queue"].append(song)
    
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

user_sessions = UserSession()

# --- FastAPI App ---
app = FastAPI(title="Loveworld Scraper Bot API", version="1.0.0")

@app.get("/")
async def root():
    return {"message": "Loveworld Scraper Bot API", "status": "running"}

@app.post("/api/scrape")
async def create_scrape_job(
    submission: BatchSubmission,
    background_tasks: BackgroundTasks,
    user_id: int = 0
):
    """Create a new scraping job from song submissions."""
    songs = [song.dict() for song in submission.songs]
    
    # Save to temporary JSON file
    temp_file = BotConfig.DOWNLOAD_DIR / f"temp_{user_id}_{datetime.now().timestamp()}.json"
    with open(temp_file, 'w') as f:
        json.dump(songs, f, indent=2)
    
    # Create job
    job_id = await job_manager.create_job(user_id, len(songs))
    
    # Start scraping in background
    background_tasks.add_task(run_scraper, job_id, temp_file)
    
    return {"job_id": job_id, "status": "queued", "songs_count": len(songs)}

@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """Get the status of a scraping job."""
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.get("/api/jobs/user/{user_id}")
async def get_user_jobs(user_id: int):
    """Get all jobs for a user."""
    jobs = await job_manager.list_user_jobs(user_id)
    return {"jobs": jobs}

@app.get("/api/download/{job_id}")
async def download_results(job_id: str):
    """Download the results of a completed job."""
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job not completed yet")
    
    if not job.get("download_path") or not Path(job["download_path"]).exists():
        raise HTTPException(status_code=404, detail="Download file not found")
    
    return FileResponse(
        job["download_path"],
        media_type="application/zip",
        filename=f"loveworld_songs_{job_id}.zip"
    )

async def run_scraper(job_id: str, json_file: Path):
    """Background task to run the scraper."""
    try:
        await job_manager.update_job(job_id, status="running")
        
        # Load songs
        json_data = load_json_file(str(json_file))
        if not json_data:
            await job_manager.update_job(job_id, status="failed", error="Invalid JSON file")
            return
        
        # Setup
        base_folder = BotConfig.DOWNLOAD_DIR / f"job_{job_id}"
        base_folder.mkdir(exist_ok=True)
        
        tracker = ProgressTracker(str(base_folder / "progress.json"))
        session = create_session()
        
        # Phase 1: Lyrics
        lyrics_stats = scrape_phase(json_data, session, tracker, base_folder, "lyrics")
        await job_manager.update_job(
            job_id,
            progress={
                "lyrics_completed": lyrics_stats["success"],
                "lyrics_failed": lyrics_stats["failed"]
            }
        )
        
        # Phase 2: Audio
        audio_stats = scrape_phase(json_data, session, tracker, base_folder, "audio")
        
        session.close()
        
        # Create zip file
        import shutil
        zip_path = BotConfig.DOWNLOAD_DIR / f"job_{job_id}.zip"
        shutil.make_archive(str(zip_path.with_suffix("")), 'zip', base_folder)
        
        # Update job
        await job_manager.update_job(
            job_id,
            status="completed",
            progress={
                "lyrics_completed": lyrics_stats["success"],
                "lyrics_failed": lyrics_stats["failed"],
                "audio_completed": audio_stats["success"],
                "audio_failed": audio_stats["failed"]
            },
            download_path=str(zip_path)
        )
        
        # Cleanup
        json_file.unlink(missing_ok=True)
        
    except Exception as e:
        await job_manager.update_job(job_id, status="failed", error=str(e))

# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler."""
    user = update.effective_user
    welcome_text = f"""
👋 Welcome {user.first_name}!

I'm the Loveworld Scraper Bot. I can help you download song lyrics and audio from Loveworld.

📋 **Options:**

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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler."""
    help_text = """
🆘 **Available Commands:**

/start - Start the bot
/help - Show this help message
/addsong - Add a song interactively
/viewqueue - View your song queue
/clearqueue - Clear your queue
/scrape - Start scraping your queue
/status - Check job status
/cancel - Cancel current operation

📁 **File Upload:**
Just send me a `links.json` or `input.txt` file and I'll process it automatically!

💡 **Tips:**
• You can add multiple songs before scraping
• Files are processed in the background
• You'll get a download link when done
"""
    await update.message.reply_text(help_text)

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads (JSON or TXT)."""
    file = await update.message.document.get_file()
    file_name = update.message.document.file_name
    user_id = update.effective_user.id
    
    # Check file size
    if update.message.document.file_size > BotConfig.MAX_FILE_SIZE:
        await update.message.reply_text("❌ File too large! Maximum size is 10MB.")
        return
    
    # Download file
    temp_path = BotConfig.DOWNLOAD_DIR / f"upload_{user_id}_{datetime.now().timestamp()}_{file_name}"
    await file.download_to_drive(temp_path)
    
    await update.message.reply_text("⏳ Processing your file...")
    
    try:
        # Process based on file type
        if file_name.endswith('.json'):
            songs = load_json_file(str(temp_path))
        elif file_name.endswith('.txt'):
            # Convert TXT to JSON
            formatter = LinksFormatter(input_file=str(temp_path))
            with open(temp_path, 'r') as f:
                text = f.read()
            songs = formatter.parse_text(text)
        else:
            await update.message.reply_text("❌ Unsupported file type. Send .json or .txt files only.")
            temp_path.unlink(missing_ok=True)
            return
        
        if not songs:
            await update.message.reply_text("❌ No valid songs found in file.")
            temp_path.unlink(missing_ok=True)
            return
        
        # Save as JSON for scraper
        json_path = temp_path.with_suffix('.json')
        with open(json_path, 'w') as f:
            json.dump(songs, f, indent=2)
        
        # Create job
        job_id = await job_manager.create_job(user_id, len(songs))
        
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
        
        # Store job metadata
        context.user_data[f"job_{job_id}"] = {"json_path": str(json_path)}
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error processing file: {str(e)}")
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

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
    
    # Scrape job
    if data.startswith("scrape_"):
        job_id = data.replace("scrape_", "")
        job_meta = context.user_data.get(f"job_{job_id}")
        
        if not job_meta:
            await query.edit_message_text("❌ Job not found.")
            return
        
        await query.edit_message_text("🚀 Starting scraper... This may take a while.")
        
        # Start scraping
        json_path = Path(job_meta["json_path"])
        asyncio.create_task(run_scraper(job_id, json_path))
        
        # Send progress updates
        asyncio.create_task(send_progress_updates(context, query.message.chat_id, job_id))
    
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
    """Start scraping the queue."""
    user_id = update.effective_user.id
    queue = await user_sessions.get_queue(user_id)
    
    if not queue:
        await update.message.reply_text("📭 Queue is empty!")
        return
    
    # Save queue to JSON
    temp_file = BotConfig.DOWNLOAD_DIR / f"queue_{user_id}_{datetime.now().timestamp()}.json"
    with open(temp_file, 'w') as f:
        json.dump(queue, f, indent=2)
    
    # Create job
    job_id = await job_manager.create_job(user_id, len(queue))
    
    await update.message.reply_text(f"🚀 Starting scraper for {len(queue)} songs...")
    
    # Start scraping
    asyncio.create_task(run_scraper(job_id, temp_file))
    asyncio.create_task(send_progress_updates(context, update.message.chat_id, job_id))
    
    # Clear queue
    await user_sessions.clear_queue(user_id)

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

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check job status."""
    user_id = update.effective_user.id
    jobs = await job_manager.list_user_jobs(user_id)
    
    if not jobs:
        await update.message.reply_text("📭 No jobs found.")
        return
    
    message = "📊 **Your Jobs:**\n\n"
    for job in jobs[-5:]:  # Show last 5 jobs
        message += (
            f"Job ID: `{job['job_id']}`\n"
            f"Status: {job['status']}\n"
            f"Songs: {job['total_songs']}\n"
            f"Created: {job['created_at']}\n\n"
        )
    
    await update.message.reply_text(message)

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
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "bot":
        # Run as polling bot (for development)
        print("🤖 Starting Telegram Bot (Polling Mode)...")
        bot_app = setup_bot()
        bot_app.run_polling()
    else:
        # Run FastAPI with webhook
        print("🚀 Starting FastAPI Server...")
        print(f"📡 Webhook URL: {BotConfig.WEBHOOK_URL}")
        
        @app.on_event("startup")
        async def startup():
            bot_app = setup_bot()
            await bot_app.bot.set_webhook(f"{BotConfig.WEBHOOK_URL}/webhook")
        
        @app.post("/webhook")
        async def webhook(update: dict):
            bot_app = setup_bot()
            await bot_app.process_update(Update.de_json(update, bot_app.bot))
            return {"ok": True}
        
        uvicorn.run(app, host="0.0.0.0", port=BotConfig.PORT)
