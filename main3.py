import os
import json
import re
import requests
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.panel import Panel
from rich.theme import Theme
from rich.tree import Tree
from rich.table import Table
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Configuration ---
class Config:
    BASE_FOLDER = "Loveworld_Downloads"
    INPUT_FILE = "links.json"
    PROGRESS_FILE = "scraper_progress.json"
    REQUEST_TIMEOUT = 15
    DOWNLOAD_TIMEOUT = 120  # 2 minutes for large audio files
    MAX_RETRIES = 2
    BACKOFF_FACTOR = 0.5
    CHUNK_SIZE = 65536  # 64KB chunks for faster download
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    MAX_WORKERS = 3  # Parallel downloads
    
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "highlight": "bold magenta",
})

console = Console(theme=custom_theme)

# --- Progress Tracking ---
class ProgressTracker:
    """Tracks which songs have been successfully processed."""
    
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.data = self._load()
    
    def _load(self) -> Dict:
        """Load progress from file."""
        if self.filepath.exists():
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {"completed": {}, "failed": {}}
        return {"completed": {}, "failed": {}}
    
    def _save(self):
        """Save progress to file."""
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            console.print(f"[warning]Could not save progress: {e}[/]")
    
    def is_completed(self, url: str) -> bool:
        """Check if a URL has been successfully processed."""
        return url in self.data["completed"]
    
    def mark_completed(self, url: str, has_lyrics: bool, has_audio: bool):
        """Mark a URL as completed."""
        self.data["completed"][url] = {
            "lyrics": has_lyrics,
            "audio": has_audio,
            "timestamp": time.time()
        }
        self._save()
    
    def needs_audio(self, url: str) -> bool:
        """Check if we need to download audio for this URL."""
        if url in self.data["completed"]:
            return not self.data["completed"][url].get("audio", False)
        return True
    
    def needs_lyrics(self, url: str) -> bool:
        """Check if we need to download lyrics for this URL."""
        if url in self.data["completed"]:
            return not self.data["completed"][url].get("lyrics", False)
        return True
    
    def mark_failed(self, url: str, reason: str):
        """Mark a URL as failed."""
        self.data["failed"][url] = {
            "reason": reason,
            "timestamp": time.time()
        }
        self._save()
    
    def get_stats(self) -> Dict:
        """Get completion statistics."""
        return {
            "completed": len(self.data.get("completed", {})),
            "failed": len(self.data.get("failed", {}))
        }

# --- Session Management ---
def create_session() -> requests.Session:
    """Creates a requests session with retry logic and proper headers."""
    session = requests.Session()
    
    retry_strategy = Retry(
        total=Config.MAX_RETRIES,
        backoff_factor=Config.BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": Config.USER_AGENT})
    
    return session

# --- Helper Functions ---
def sanitize_filename(name: str) -> str:
    """Removes illegal characters from filenames/folder names."""
    sanitized = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    sanitized = re.sub(r'\s+', ' ', sanitized)
    return sanitized[:200]

def load_json_file(filepath: str) -> Optional[List[Dict]]:
    """Loads and validates JSON file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            console.print(f"[error]Error: {filepath} must contain a JSON array[/]")
            return None
        
        required_fields = ["title", "artists", "url"]
        for idx, item in enumerate(data):
            missing_fields = [field for field in required_fields if field not in item]
            if missing_fields:
                console.print(
                    f"[warning]Warning: Item {idx} missing fields: {', '.join(missing_fields)}[/]"
                )
        
        return data
    
    except FileNotFoundError:
        console.print(f"[error]Error: File '{filepath}' not found[/]")
        return None
    except json.JSONDecodeError as e:
        console.print(f"[error]Error: Invalid JSON in '{filepath}': {str(e)}[/]")
        return None
    except Exception as e:
        console.print(f"[error]Error loading '{filepath}': {str(e)}[/]")
        return None

def get_lyrics(soup: BeautifulSoup) -> Optional[str]:
    """Extracts lyrics from the entry-content div, preserving <br> tags as line breaks."""
    content_div = soup.find("div", class_="entry-content entry clearfix")
    if not content_div:
        content_div = soup.find("div", class_="entry-content")
    
    if not content_div:
        return None
    
    paragraphs = content_div.find_all("p")
    lyrics_sections = []
    
    for p in paragraphs:
        # Replace <br> tags with newlines before extracting text
        for br in p.find_all("br"):
            br.replace_with("\n")
        
        text = p.get_text().strip()
        if text and not text.startswith(('Download', 'Listen', 'Share')):
            lyrics_sections.append(text)
    
    return "\n\n".join(lyrics_sections) if lyrics_sections else None

def get_audio_url(soup: BeautifulSoup) -> Optional[str]:
    """Extracts the audio source URL from various possible locations."""
    # Strategy 1: Figure > Audio
    figure = soup.find("figure")
    if figure:
        audio = figure.find("audio")
        if audio and audio.get("src"):
            return audio["src"]
    
    # Strategy 2: Any audio tag
    audio = soup.find("audio")
    if audio:
        if audio.get("src"):
            return audio["src"]
        source = audio.find("source")
        if source and source.get("src"):
            return source["src"]
    
    # Strategy 3: Look for download links
    download_link = soup.find("a", href=re.compile(r'\.(mp3|wav|m4a)$', re.I))
    if download_link and download_link.get("href"):
        return download_link["href"]
    
    return None

def download_file_fast(session: requests.Session, url: str, filepath: Path) -> Tuple[bool, str]:
    """Fast parallel chunked download with timeout."""
    try:
        # Get file size first
        head = session.head(url, timeout=5)
        total_size = int(head.headers.get('content-length', 0))
        
        response = session.get(url, stream=True, timeout=Config.DOWNLOAD_TIMEOUT)
        response.raise_for_status()
        
        downloaded = 0
        start_time = time.time()
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=Config.CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Timeout check
                    if time.time() - start_time > Config.DOWNLOAD_TIMEOUT:
                        return False, "Download timeout exceeded"
        
        return True, "Success"
    
    except requests.exceptions.Timeout:
        return False, "Download timeout"
    except requests.exceptions.RequestException as e:
        return False, f"Network error: {str(e)[:50]}"
    except IOError as e:
        return False, f"File error: {str(e)[:50]}"

def save_lyrics(filepath: Path, song_title: str, artist: str, url: str, lyrics: str) -> bool:
    """Saves lyrics to a text file with metadata."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Title: {song_title}\n")
            f.write(f"Artist: {artist}\n")
            f.write(f"Source: {url}\n")
            f.write(f"\n{'='*60}\n\n")
            f.write(lyrics)
        return True
    except IOError:
        return False

# --- Song Processing ---
def process_song(item: Dict, session: requests.Session, tracker: ProgressTracker, 
                base_folder: Path, phase: str) -> Dict:
    """Process a single song (lyrics or audio phase)."""
    song_title = item.get("title", "Unknown Title")
    artist = item.get("artists", "Unknown Artist")
    url = item.get("url", "")
    
    result = {
        "title": song_title,
        "success": False,
        "lyrics_saved": False,
        "audio_saved": False,
        "messages": [],
        "skip_reason": None
    }
    
    if not url:
        result["messages"].append("No URL provided")
        return result
    
    folder_name = sanitize_filename(f"{song_title} - {artist}")
    song_folder = base_folder / folder_name
    song_folder.mkdir(exist_ok=True)
    
    try:
        # Phase 1: Lyrics only
        if phase == "lyrics":
            if not tracker.needs_lyrics(url):
                result["skip_reason"] = "Lyrics already downloaded"
                result["lyrics_saved"] = True
                return result
            
            response = session.get(url, timeout=Config.REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                result["messages"].append(f"HTTP {response.status_code}")
                return result
            
            soup = BeautifulSoup(response.content, 'html.parser')
            lyrics = get_lyrics(soup)
            
            if lyrics:
                lyrics_path = song_folder / "lyrics.txt"
                if save_lyrics(lyrics_path, song_title, artist, url, lyrics):
                    result["lyrics_saved"] = True
                    result["success"] = True
                    result["messages"].append("✓ Lyrics saved")
                else:
                    result["messages"].append("Failed to save lyrics")
            else:
                result["messages"].append("No lyrics found")
        
        # Phase 2: Audio only
        elif phase == "audio":
            if not tracker.needs_audio(url):
                result["skip_reason"] = "Audio already downloaded"
                result["audio_saved"] = True
                return result
            
            response = session.get(url, timeout=Config.REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                result["messages"].append(f"HTTP {response.status_code}")
                return result
            
            soup = BeautifulSoup(response.content, 'html.parser')
            audio_url = get_audio_url(soup)
            
            if audio_url:
                ext = ".mp3"
                if "." in audio_url.split("/")[-1]:
                    ext = "." + audio_url.split(".")[-1].split("?")[0]
                
                audio_filename = sanitize_filename(song_title) + ext
                audio_path = song_folder / audio_filename
                success, message = download_file_fast(session, audio_url, audio_path)
                
                if success:
                    size_mb = audio_path.stat().st_size / (1024 * 1024)
                    result["audio_saved"] = True
                    result["success"] = True
                    result["messages"].append(f"✓ {audio_filename} saved ({size_mb:.1f} MB)")
                else:
                    result["messages"].append(f"Audio failed: {message}")
            else:
                result["messages"].append("No audio URL found")
        
    except requests.exceptions.Timeout:
        result["messages"].append("Request timeout")
    except Exception as e:
        result["messages"].append(f"Error: {str(e)[:50]}")
    
    return result

# --- Main Scraper Logic ---
def scrape_phase(json_data: List[Dict], session: requests.Session, tracker: ProgressTracker,
                base_folder: Path, phase: str) -> Dict:
    """Process songs in a specific phase (lyrics or audio)."""
    stats = {
        "total": len(json_data),
        "success": 0,
        "skipped": 0,
        "failed": 0,
        "lyrics_saved": 0,
        "audio_saved": 0,
        "errors": []
    }
    
    phase_name = "Downloading Lyrics" if phase == "lyrics" else "Downloading Audio"
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=False
    ) as progress:
        
        main_task = progress.add_task(f"[highlight]{phase_name}...[/]", total=len(json_data))
        
        for idx, item in enumerate(json_data, 1):
            song_title = item.get("title", f"Unknown {idx}")
            url = item.get("url", "")
            
            progress.update(
                main_task,
                description=f"[cyan]({idx}/{len(json_data)}) {song_title[:35]}..."
            )
            
            result = process_song(item, session, tracker, base_folder, phase)
            
            if result["skip_reason"]:
                stats["skipped"] += 1
            elif result["success"]:
                stats["success"] += 1
                if result["lyrics_saved"]:
                    stats["lyrics_saved"] += 1
                if result["audio_saved"]:
                    stats["audio_saved"] += 1
                
                # Update tracker
                has_lyrics = result["lyrics_saved"] or not tracker.needs_lyrics(url)
                has_audio = result["audio_saved"] or not tracker.needs_audio(url)
                tracker.mark_completed(url, has_lyrics, has_audio)
            else:
                stats["failed"] += 1
                error_msg = ", ".join(result["messages"]) if result["messages"] else "Unknown error"
                stats["errors"].append(f"{song_title}: {error_msg}")
                tracker.mark_failed(url, error_msg)
            
            progress.advance(main_task)
            time.sleep(0.2)  # Small delay between requests
    
    return stats

def display_phase_summary(phase: str, stats: Dict):
    """Display summary for a phase."""
    phase_name = "Lyrics" if phase == "lyrics" else "Audio"
    
    table = Table(title=f"{phase_name} Phase Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan", width=25)
    table.add_column("Count", justify="right", style="green")
    
    table.add_row("Total Songs", str(stats["total"]))
    table.add_row("Successfully Downloaded", str(stats["success"]))
    table.add_row("Skipped (Already Done)", str(stats["skipped"]))
    table.add_row("Failed", str(stats["failed"]))
    
    console.print("\n")
    console.print(table)
    
    if stats["errors"] and stats["failed"] > 0:
        console.print(f"\n[warning]{len(stats['errors'])} errors in this phase[/]")

# --- Main Execution ---
def main():
    """Main entry point with two-phase processing."""
    console.print(Panel.fit(
        "[bold]Loveworld Lyrics Scraper[/]\n[dim]Enterprise Edition - Resume Capable[/]",
        style="bold magenta",
        border_style="magenta"
    ))
    
    # Load JSON file
    console.print(f"\n[info]Loading songs from '{Config.INPUT_FILE}'...[/]")
    json_data = load_json_file(Config.INPUT_FILE)
    
    if not json_data:
        console.print("[error]Failed to load songs. Exiting.[/]")
        return
    
    if len(json_data) == 0:
        console.print("[warning]No songs found in the input file.[/]")
        return
    
    console.print(f"[success]✓ Loaded {len(json_data)} songs[/]")
    
    # Initialize tracker
    tracker = ProgressTracker(Config.PROGRESS_FILE)
    prev_stats = tracker.get_stats()
    
    if prev_stats["completed"] > 0:
        console.print(f"[info]Found previous progress: {prev_stats['completed']} completed, {prev_stats['failed']} failed[/]")
        console.print("[info]Resuming from where we left off...[/]\n")
    else:
        console.print("[info]Starting fresh download...\n")
    
    base_folder = Path(Config.BASE_FOLDER)
    base_folder.mkdir(exist_ok=True)
    
    session = create_session()
    
    try:
        # Phase 1: Download all lyrics (fast)
        console.print(Panel("Phase 1: Downloading Lyrics", style="bold cyan"))
        lyrics_stats = scrape_phase(json_data, session, tracker, base_folder, "lyrics")
        display_phase_summary("lyrics", lyrics_stats)
        
        # Phase 2: Download all audio (slow)
        console.print("\n")
        console.print(Panel("Phase 2: Downloading Audio Files", style="bold cyan"))
        audio_stats = scrape_phase(json_data, session, tracker, base_folder, "audio")
        display_phase_summary("audio", audio_stats)
        
        # Final summary
        console.print("\n")
        final_table = Table(title="Final Summary", show_header=True, header_style="bold green")
        final_table.add_column("Category", style="cyan", width=25)
        final_table.add_column("Count", justify="right", style="green")
        
        final_table.add_row("Total Songs", str(len(json_data)))
        final_table.add_row("Lyrics Downloaded", str(lyrics_stats["lyrics_saved"]))
        final_table.add_row("Audio Downloaded", str(audio_stats["audio_saved"]))
        final_table.add_row("Total Errors", str(lyrics_stats["failed"] + audio_stats["failed"]))
        
        console.print(final_table)
        console.print(f"\n[success]✓ All done! Files saved to '{Config.BASE_FOLDER}/'[/]")
        console.print(f"[info]Progress saved to '{Config.PROGRESS_FILE}' - run again to retry failed items[/]")
    
    except KeyboardInterrupt:
        console.print("\n[warning]Process interrupted. Progress saved. Run again to resume.[/]")
    except Exception as e:
        console.print(f"\n[error]Fatal error: {str(e)}[/]")
    finally:
        session.close()

if __name__ == "__main__":
    main()
