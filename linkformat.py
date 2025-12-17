import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

class LinksFormatter:
    """
    Dynamic formatter to convert text-based song lists into structured JSON.
    Automatically extracts event information from URLs without hardcoding.
    """
    
    # Common event patterns found in Loveworld URLs
    EVENT_PATTERNS = [
        # Format: (url_pattern, event_name_template, extract_number)
        (r'praise-night-(\d+)', 'Praise Night {0}', True),
        (r'healing-streams-(\d+)', 'Healing Streams {0}', True),
        (r'communion-service', 'Communion Service', False),
        (r'global-thanksgiving', 'Global Thanksgiving', False),
        (r'royal-thanksgiving', 'Royal Thanksgiving', False),
        (r'ylws', 'YLWS', False),
        (r'hslhs-(\d+)[:-](\d+)', 'HSLHS {0}:{1}', True),
        (r'your-loveworld-specials', 'Your LoveWorld Specials', False),
        (r'night-of-bliss', 'Night of Bliss', False),
        (r'campus-ministry', 'Campus Ministry', False),
        (r'rhapsody-concert', 'Rhapsody Concert', False),
        (r'worship-night', 'Worship Night', False),
        (r'celebration-service', 'Celebration Service', False),
    ]
    
    # Additional context patterns (with Pastor Chris, etc.)
    CONTEXT_PATTERNS = [
        (r'with-pastor-chris', 'with Pastor Chris'),
        (r'pastor-chris', 'with Pastor Chris'),
        (r'pc-', 'with Pastor Chris'),
    ]
    
    def __init__(self, input_file: str = "input.txt", output_file: str = "links.json"):
        self.input_file = Path(input_file)
        self.output_file = Path(output_file)
    
    def parse_title_line(self, line: str) -> Optional[Tuple[str, str]]:
        """
        Parse a line like "TITLE BY ARTIST" or "TITLE - ARTIST"
        Returns (title, artist) or None if not parsable.
        """
        # Try "BY" separator first
        match = re.match(r"(.+?)\s+BY\s+(.+)$", line, re.IGNORECASE)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        
        # Try "-" separator
        match = re.match(r"(.+?)\s*-\s*(.+)$", line)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        
        return None
    
    def extract_event_from_url(self, url: str) -> Optional[str]:
        """
        Dynamically extract event information from URL patterns.
        No hardcoding of specific events.
        """
        url_lower = url.lower()
        
        event_parts = []
        
        # Check for main event patterns
        for pattern, template, has_number in self.EVENT_PATTERNS:
            match = re.search(pattern, url_lower)
            if match:
                if has_number:
                    # Extract numbers and format
                    numbers = match.groups()
                    event_name = template.format(*numbers)
                else:
                    event_name = template
                
                event_parts.append(event_name)
                break  # Use first match as primary event
        
        # Check for context (with Pastor Chris, etc.)
        for pattern, context in self.CONTEXT_PATTERNS:
            if re.search(pattern, url_lower):
                event_parts.append(context)
                break
        
        return " ".join(event_parts) if event_parts else None
    
    def normalize_artist_name(self, artist: str) -> str:
        """
        Normalize artist names to title case and handle common variations.
        """
        # Remove extra whitespace
        artist = re.sub(r'\s+', ' ', artist.strip())
        
        # Common abbreviations to preserve
        abbreviations = ['DJ', 'MC', 'DSA', 'DCNS', 'PST', 'REV']
        
        words = artist.split()
        normalized = []
        
        for word in words:
            upper_word = word.upper()
            if upper_word in abbreviations:
                normalized.append(upper_word)
            else:
                # Title case
                normalized.append(word.title())
        
        return " ".join(normalized)
    
    def format_title(self, title: str) -> str:
        """
        Format title to proper title case, handling special cases.
        """
        # Remove extra whitespace
        title = re.sub(r'\s+', ' ', title.strip())
        
        # Words that should stay lowercase in titles (unless first word)
        lowercase_words = {'a', 'an', 'the', 'and', 'but', 'or', 'for', 'nor', 
                          'on', 'at', 'to', 'from', 'by', 'of', 'in', 'with'}
        
        words = title.split()
        formatted = []
        
        for i, word in enumerate(words):
            if i == 0 or word.lower() not in lowercase_words:
                formatted.append(word.title())
            else:
                formatted.append(word.lower())
        
        return " ".join(formatted)
    
    def parse_text(self, text: str) -> List[Dict]:
        """
        Parse the input text and return structured song data.
        Expects format:
            TITLE BY ARTIST
            https://url.com/...
            (blank line optional)
            NEXT TITLE BY ARTIST
            https://url.com/...
        """
        songs = []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Skip if it's a URL (orphaned or duplicate)
            if line.startswith('http'):
                i += 1
                continue
            
            # Try to parse as title line
            parsed = self.parse_title_line(line)
            if not parsed:
                i += 1
                continue
            
            raw_title, raw_artist = parsed
            
            # Next line should be URL
            if i + 1 >= len(lines):
                break
            
            next_line = lines[i + 1]
            if not next_line.startswith('http'):
                i += 1
                continue
            
            url = next_line
            
            # Format the data
            title = self.format_title(raw_title)
            artist_name = self.normalize_artist_name(raw_artist)
            artists = f"{artist_name} and Loveworld Singers"
            event = self.extract_event_from_url(url)
            
            song = {
                "title": title,
                "artists": artists,
                "url": url
            }
            
            # Only add event if found
            if event:
                song["event"] = event
            
            songs.append(song)
            
            i += 2  # Move to next song
        
        return songs
    
    def convert_file(self) -> bool:
        """
        Read input file, convert to JSON, and save to output file.
        """
        try:
            if not self.input_file.exists():
                print(f"❌ Error: Input file '{self.input_file}' not found")
                return False
            
            # Read input
            with open(self.input_file, 'r', encoding='utf-8') as f:
                text = f.read()
            
            # Parse
            songs = self.parse_text(text)
            
            if not songs:
                print("⚠️  Warning: No songs found in input file")
                return False
            
            # Save to JSON
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(songs, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Successfully converted {len(songs)} songs")
            print(f"📄 Output saved to: {self.output_file}")
            
            # Show preview
            print("\n📋 Preview (first 3 songs):")
            for song in songs[:3]:
                print(f"  • {song['title']} - {song['artists']}")
                if 'event' in song:
                    print(f"    Event: {song['event']}")
            
            if len(songs) > 3:
                print(f"  ... and {len(songs) - 3} more")
            
            return True
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    def add_event_pattern(self, pattern: str, template: str, has_number: bool = False):
        """
        Add a custom event pattern dynamically.
        
        Args:
            pattern: Regex pattern to match in URL
            template: Template for event name (use {0}, {1} for numbers if has_number=True)
            has_number: Whether the pattern captures numbers
        
        Example:
            formatter.add_event_pattern(r'new-event-(\\\\d+)', 'New Event {0}', True)
        """
        self.EVENT_PATTERNS.append((pattern, template, has_number))


def main():
    """Main execution with user-friendly interface."""
    print("=" * 60)
    print("  Loveworld Links Formatter - Dynamic Edition")
    print("=" * 60)
    print()
    
    # Initialize formatter
    formatter = LinksFormatter(input_file="input.txt", output_file="links.json")
    
    # Check if input file exists, if not, show instructions
    if not formatter.input_file.exists():
        print("📝 No input.txt found. Creating sample file...")
        sample = """YOUR DOMINION IS FOR ETERNITY BY ENIOLA
https://loveworldlyrics.com/your-dominion-is-for-eternity-by-eniola-and-loveworld-singers-july-communion-service/

GREAT KING OF ALL BY MICHAELA
https://loveworldlyrics.com/great-king-of-all-by-michaela-and-loveworld-singers-praise-night-25-with-pastor-chris/

DIVINITY BY ELI-J
https://loveworldlyrics.com/divinity-by-eli-j-and-loveworld-singers-praise-night-26/
"""
        with open("input.txt", "w", encoding="utf-8") as f:
            f.write(sample)
        print("✅ Created sample input.txt file")
        print("\n📋 Instructions:")
        print("  1. Edit input.txt with your song list")
        print("  2. Format: TITLE BY ARTIST on one line, URL on next line")
        print("  3. Run this script again")
        print()
        return
    
    # Convert
    success = formatter.convert_file()
    
    if success:
        print("\n✨ Done! You can now use links.json with the scraper.")
    else:
        print("\n❌ Conversion failed. Check your input.txt format.")


if __name__ == "__main__":
    main()