# Loveworld Scraper Bot - FastAPI + Telegram

A robust FastAPI application integrated with Telegram Bot for downloading Loveworld song lyrics and audio files.

## Features

✅ **File Upload Support**
- Upload `links.json` directly
- Upload `input.txt` with automatic formatting
- Automatic validation and processing

✅ **Interactive Song Addition**
- Add songs one by one via conversation
- Auto-detect event names from URLs
- Queue management (view, clear, add)

✅ **Background Processing**
- Asynchronous scraping
- Progress tracking and updates
- Job status monitoring

✅ **REST API**
- Full API access for programmatic use
- Job management endpoints
- Download completed results

## Quick Start

### 1. Setup

```bash
# Clone or create project directory
mkdir loveworld-bot && cd loveworld-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your bot token and webhook URL
```

### 2. Get Telegram Bot Token

1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot` and follow instructions
3. Copy the bot token
4. Add to `.env` file

### 3. Run Locally (Development)

```bash
# Method 1: Polling mode (no webhook needed)
python telegram_bot_api.py bot

# Method 2: API + Webhook mode (requires public URL)
python telegram_bot_api.py
```

### 4. Deploy to Production

#### Using Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

#### Manual Deployment

```bash
# Using gunicorn
gunicorn telegram_bot_api:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

# Using uvicorn directly
uvicorn telegram_bot_api:app --host 0.0.0.0 --port 8000 --workers 4
```

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and overview |
| `/help` | Show all commands |
| `/addsong` | Add a song interactively |
| `/viewqueue` | View your song queue |
| `/clearqueue` | Clear your queue |
| `/scrape` | Start scraping your queue |
| `/status` | Check job status |
| `/cancel` | Cancel current operation |

## Usage Examples

### 1. Upload JSON File

1. Prepare your `links.json`:
```json
[
  {
    "title": "King of Eternity",
    "artists": "Sylvia and Loveworld Singers",
    "url": "https://loveworldlyrics.com/king-of-eternity...",
    "event": "Royal Thanksgiving with Pastor Chris"
  }
]
```

2. Send the file to the bot
3. Bot will parse and show preview
4. Click "Start Scraping" to begin

### 2. Upload Text File

1. Create `input.txt`:
```
King of Eternity by Sylvia
https://loveworldlyrics.com/king-of-eternity...

Lord Overall by Eli-J
https://loveworldlyrics.com/lord-over-all...
```

2. Send to bot
3. Bot auto-converts to JSON format
4. Click "Start Scraping"

### 3. Interactive Mode

```
You: /addsong
Bot: Let's add a song! First, send me the song title:

You: King of Eternity
Bot: ✅ Title: King of Eternity
     Now send me the artist name:

You: Sylvia
Bot: ✅ Artist: Sylvia
     Now send me the URL:

You: https://loveworldlyrics.com/king-of-eternity...
Bot: [Shows preview with buttons]
     - ✅ Confirm & Add
     - 🔄 Add Event Name
     - ❌ Cancel
```

## API Endpoints

### Create Scrape Job
```bash
POST /api/scrape
Content-Type: application/json

{
  "songs": [
    {
      "title": "Song Title",
      "artist": "Artist Name",
      "url": "https://...",
      "event": "Optional Event"
    }
  ]
}
```

### Get Job Status
```bash
GET /api/job/{job_id}
```

### List User Jobs
```bash
GET /api/jobs/user/{user_id}
```

### Download Results
```bash
GET /api/download/{job_id}
```

## Deployment Options

### Option 1: Railway

1. Create account at [railway.app](https://railway.app)
2. Click "New Project" → "Deploy from GitHub"
3. Add environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `WEBHOOK_URL` (use Railway-provided URL)
4. Deploy!

### Option 2: Render

1. Create account at [render.com](https://render.com)
2. New Web Service → Connect repository
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `python telegram_bot_api.py`
5. Add environment variables

### Option 3: DigitalOcean App Platform

1. Create account at [digitalocean.com](https://digitalocean.com)
2. Apps → Create App
3. Select GitHub repository
4. Configure environment variables
5. Deploy

### Option 4: VPS (Linux Server)

```bash
# On your server
git clone <your-repo>
cd loveworld-bot

# Install dependencies
pip install -r requirements.txt

# Run with systemd
sudo nano /etc/systemd/system/loveworld-bot.service
```

Systemd service file:
```ini
[Unit]
Description=Loveworld Bot Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/loveworld-bot
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python telegram_bot_api.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable loveworld-bot
sudo systemctl start loveworld-bot
```

## Configuration

### Environment Variables

```bash
# Required
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
WEBHOOK_URL=https://your-domain.com

# Optional
PORT=8000
ADMIN_IDS=123456789,987654321
MAX_WORKERS=3
```

### Bot Configuration (in code)

```python
class BotConfig:
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    DOWNLOAD_DIR = Path("bot_downloads")
```

## Monitoring

### Check Logs

```bash
# Docker
docker-compose logs -f bot

# Systemd
sudo journalctl -u loveworld-bot -f

# Direct
tail -f /path/to/logs/bot.log
```

### Health Check

```bash
curl http://localhost:8000/
# Should return: {"message": "Loveworld Scraper Bot API", "status": "running"}
```

## Troubleshooting

### Bot Not Responding

1. Check bot token is correct
2. Verify webhook URL is accessible
3. Check logs for errors
4. Test with `/start` command

### Files Not Downloading

1. Check disk space
2. Verify download directory permissions
3. Check network connectivity
4. Review job status: `/status`

### Webhook Issues

1. Ensure HTTPS (required by Telegram)
2. Check webhook is set: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
3. Use polling mode for testing: `python telegram_bot_api.py bot`

### Rate Limiting

If hitting rate limits:
1. Reduce `MAX_WORKERS` in `Config`
2. Increase delays between requests
3. Use queue system for large batches

## Advanced Features

### Custom Event Patterns

Add custom event patterns to `linkformat.py`:

```python
formatter = LinksFormatter()
formatter.add_event_pattern(
    pattern=r'special-event-(\d+)',
    template='Special Event {0}',
    has_number=True
)
```

### Admin Commands

Restrict certain commands to admins:

```python
if update.effective_user.id not in BotConfig.ADMIN_IDS:
    await update.message.reply_text("⛔ Admin only command")
    return
```

### Database Integration

For persistent storage, add PostgreSQL:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(os.getenv("DATABASE_URL"))
SessionLocal = sessionmaker(bind=engine)
```

## Performance Tips

1. **Parallel Processing**: Adjust `MAX_WORKERS` based on server capacity
2. **Caching**: Store frequently accessed data in Redis
3. **CDN**: Use CDN for serving downloaded files
4. **Load Balancing**: Use nginx for multiple instances
5. **Database**: PostgreSQL for job tracking at scale

## Security

1. **Environment Variables**: Never commit `.env` file
2. **HTTPS**: Always use HTTPS for webhooks
3. **Input Validation**: All user inputs are validated
4. **Rate Limiting**: Implement rate limiting for API
5. **Admin Access**: Restrict sensitive operations

## License

MIT License - Feel free to use and modify!

## Support

For issues or questions:
- Create an issue on GitHub
- Contact: your-email@example.com

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/)
- [python-telegram-bot](https://python-telegram-bot.org/)
- [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/)
- [Rich](https://rich.readthedocs.io/)

---

**Happy Scraping! 🎵**
