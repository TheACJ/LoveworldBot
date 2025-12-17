import os
from typing import Optional
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class SupabaseConfig:
    """Supabase configuration and client management."""
    
    # Environment variables
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    
    # Storage configuration
    STORAGE_BUCKET_NAME: str = os.getenv("STORAGE_BUCKET_NAME", "loveworld-files")
    AUTO_DELETE_INTERVAL: int = 3600  # 1 hour in seconds
    
    # Database table names
    JOBS_TABLE: str = "scraping_jobs"
    USERS_TABLE: str = "bot_users"
    SONGS_TABLE: str = "scraped_songs"
    PROGRESS_TABLE: str = "job_progress"
    
    @classmethod
    def validate_config(cls) -> bool:
        """Validate that required environment variables are set."""
        required_vars = [cls.SUPABASE_URL, cls.SUPABASE_KEY]
        return all(var for var in required_vars)
    
    @classmethod
    def create_client(cls) -> Optional[Client]:
        """Create and return Supabase client."""
        if not cls.validate_config():
            raise ValueError("Missing required Supabase environment variables")
        
        try:
            client = create_client(cls.SUPABASE_URL, cls.SUPABASE_KEY)
            return client
        except Exception as e:
            print(f"Error creating Supabase client: {e}")
            return None
    
    @classmethod
    def create_service_client(cls) -> Optional[Client]:
        """Create service role client for admin operations."""
        if not cls.SUPABASE_SERVICE_KEY:
            print("Warning: No service role key provided")
            return cls.create_client()
        
        try:
            client = create_client(cls.SUPABASE_URL, cls.SUPABASE_SERVICE_KEY)
            return client
        except Exception as e:
            print(f"Error creating Supabase service client: {e}")
            return None

# Global instances
supabase: Optional[Client] = None
supabase_service: Optional[Client] = None

def get_supabase_client() -> Client:
    """Get or create Supabase client."""
    global supabase
    if supabase is None:
        supabase = SupabaseConfig.create_client()
        if supabase is None:
            raise RuntimeError("Failed to create Supabase client")
    return supabase

def get_supabase_service_client() -> Client:
    """Get or create Supabase service client."""
    global supabase_service
    if supabase_service is None:
        supabase_service = SupabaseConfig.create_service_client()
        if supabase_service is None:
            raise RuntimeError("Failed to create Supabase service client")
    return supabase_service

# Storage utilities
class StorageConfig:
    """Storage bucket and file management configuration."""
    
    # File type configurations
    ALLOWED_AUDIO_TYPES = {'.mp3', '.wav', '.m4a', '.aac', '.ogg'}
    ALLOWED_TEXT_TYPES = {'.txt', '.json', '.csv'}
    ALLOWED_IMAGE_TYPES = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    
    # File size limits (in bytes)
    MAX_AUDIO_SIZE = 50 * 1024 * 1024  # 50MB
    MAX_TEXT_SIZE = 10 * 1024 * 1024   # 10MB
    MAX_IMAGE_SIZE = 5 * 1024 * 1024   # 5MB
    
    # Storage paths
    AUDIO_PATH = "audio"
    LYRICS_PATH = "lyrics"
    ARCHIVES_PATH = "archives"
    TEMP_PATH = "temp"