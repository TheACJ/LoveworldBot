import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4
from supabase import Client
from supabase_config import get_supabase_service_client, SupabaseConfig

class SupabaseDatabaseService:
    """Database service for Supabase operations."""
    
    def __init__(self):
        self.client: Client = get_supabase_service_client()
        self.config = SupabaseConfig()
    
    # User Management
    async def create_or_update_user(self, telegram_user_id: int, username: str = None, 
                                  first_name: str = None, last_name: str = None,
                                  is_admin: bool = False) -> Optional[Dict]:
        """Create or update bot user."""
        try:
            user_data = {
                "telegram_user_id": telegram_user_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "is_admin": is_admin,
                "last_activity": datetime.now().isoformat()
            }
            
            response = self.client.table(self.config.USERS_TABLE).upsert(
                user_data,
                on_conflict="telegram_user_id"
            ).execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except Exception as e:
            print(f"❌ Error creating/updating user: {e}")
            return None
    
    async def get_user(self, telegram_user_id: int) -> Optional[Dict]:
        """Get user by Telegram user ID."""
        try:
            response = self.client.table(self.config.USERS_TABLE).select("*").eq(
                "telegram_user_id", telegram_user_id
            ).execute()
            
            return response.data[0] if response.data else None
            
        except Exception as e:
            print(f"❌ Error getting user: {e}")
            return None
    
    # Job Management
    async def create_job(self, user_id: int, job_id: str, total_songs: int) -> Optional[Dict]:
        """Create a new scraping job."""
        try:
            job_data = {
                "job_id": job_id,
                "user_id": user_id,
                "status": "queued",
                "total_songs": total_songs,
                "progress_data": {},
                "created_at": datetime.now().isoformat()
            }
            
            response = self.client.table(self.config.JOBS_TABLE).insert(job_data).execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except Exception as e:
            print(f"❌ Error creating job: {e}")
            return None
    
    async def update_job(self, job_id: str, **kwargs) -> bool:
        """Update job with new data."""
        try:
            # Convert datetime objects to ISO strings
            for key, value in kwargs.items():
                if isinstance(value, datetime):
                    kwargs[key] = value.isoformat()
            
            response = self.client.table(self.config.JOBS_TABLE).update(kwargs).eq(
                "job_id", job_id
            ).execute()
            
            return len(response.data) > 0
            
        except Exception as e:
            print(f"❌ Error updating job: {e}")
            return False
    
    async def get_job(self, job_id: str) -> Optional[Dict]:
        """Get job by job ID."""
        try:
            response = self.client.table(self.config.JOBS_TABLE).select("*").eq(
                "job_id", job_id
            ).execute()
            
            return response.data[0] if response.data else None
            
        except Exception as e:
            print(f"❌ Error getting job: {e}")
            return None
    
    async def get_user_jobs(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Get all jobs for a user."""
        try:
            response = self.client.table(self.config.JOBS_TABLE).select("*").eq(
                "user_id", user_id
            ).order("created_at", desc=True).limit(limit).execute()
            
            return response.data
            
        except Exception as e:
            print(f"❌ Error getting user jobs: {e}")
            return []
    
    async def update_job_progress(self, job_id: str, progress_data: Dict) -> bool:
        """Update job progress."""
        try:
            response = self.client.table(self.config.JOBS_TABLE).update({
                "progress_data": progress_data,
                "updated_at": datetime.now().isoformat()
            }).eq("job_id", job_id).execute()
            
            return len(response.data) > 0
            
        except Exception as e:
            print(f"❌ Error updating job progress: {e}")
            return False
    
    async def set_job_download_url(self, job_id: str, download_url: str, 
                                 storage_path: str) -> bool:
        """Set job download URL and storage path."""
        try:
            response = self.client.table(self.config.JOBS_TABLE).update({
                "download_url": download_url,
                "storage_path": storage_path,
                "updated_at": datetime.now().isoformat()
            }).eq("job_id", job_id).execute()
            
            return len(response.data) > 0
            
        except Exception as e:
            print(f"❌ Error setting job download URL: {e}")
            return False
    
    # Song Management
    async def add_scraped_song(self, job_id: str, song_data: Dict) -> Optional[Dict]:
        """Add a scraped song to database."""
        try:
            # Get job UUID from job_id
            job = await self.get_job(job_id)
            if not job:
                return None
            
            song_record = {
                "job_id": job["id"],
                "song_title": song_data.get("title", "Unknown"),
                "artist": song_data.get("artist", "Unknown Artist"),
                "original_url": song_data.get("url", ""),
                "event_name": song_data.get("event"),
                "has_lyrics": song_data.get("lyrics_saved", False),
                "has_audio": song_data.get("audio_saved", False),
                "scraped_at": datetime.now().isoformat()
            }
            
            response = self.client.table(self.config.SONGS_TABLE).insert(song_record).execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except Exception as e:
            print(f"❌ Error adding scraped song: {e}")
            return None
    
    async def update_song_storage_paths(self, song_id: str, lyrics_path: str = None,
                                      audio_path: str = None, audio_filename: str = None,
                                      audio_size: int = None) -> bool:
        """Update song storage paths."""
        try:
            update_data = {}
            if lyrics_path:
                update_data["lyrics_storage_path"] = lyrics_path
            if audio_path:
                update_data["audio_storage_path"] = audio_path
            if audio_filename:
                update_data["audio_filename"] = audio_filename
            if audio_size:
                update_data["audio_size_bytes"] = audio_size
            
            if not update_data:
                return True
            
            response = self.client.table(self.config.SONGS_TABLE).update(update_data).eq(
                "id", song_id
            ).execute()
            
            return len(response.data) > 0
            
        except Exception as e:
            print(f"❌ Error updating song storage paths: {e}")
            return False
    
    async def get_job_songs(self, job_id: str) -> List[Dict]:
        """Get all songs for a job."""
        try:
            job = await self.get_job(job_id)
            if not job:
                return []
            
            response = self.client.table(self.config.SONGS_TABLE).select("*").eq(
                "job_id", job["id"]
            ).execute()
            
            return response.data
            
        except Exception as e:
            print(f"❌ Error getting job songs: {e}")
            return []
    
    # Progress Tracking
    async def create_progress_record(self, job_id: str, phase: str) -> Optional[Dict]:
        """Create progress tracking record."""
        try:
            job = await self.get_job(job_id)
            if not job:
                return None
            
            progress_data = {
                "job_id": job["id"],
                "phase": phase,
                "status": "running",
                "updated_at": datetime.now().isoformat()
            }
            
            response = self.client.table(self.config.PROGRESS_TABLE).insert(progress_data).execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except Exception as e:
            print(f"❌ Error creating progress record: {e}")
            return None
    
    async def update_progress(self, job_id: str, phase: str, current_index: int,
                            total_songs: int, current_song_title: str = None,
                            status: str = "running") -> bool:
        """Update progress tracking."""
        try:
            job = await self.get_job(job_id)
            if not job:
                return False
            
            progress_percentage = (current_index / total_songs * 100) if total_songs > 0 else 0
            
            response = self.client.table(self.config.PROGRESS_TABLE).update({
                "current_song_index": current_index,
                "total_songs": total_songs,
                "status": status,
                "progress_percentage": round(progress_percentage, 2),
                "current_song_title": current_song_title,
                "updated_at": datetime.now().isoformat()
            }).eq("job_id", job["id"]).eq("phase", phase).execute()
            
            return len(response.data) > 0
            
        except Exception as e:
            print(f"❌ Error updating progress: {e}")
            return False
    
    async def get_job_progress(self, job_id: str) -> List[Dict]:
        """Get all progress records for a job."""
        try:
            job = await self.get_job(job_id)
            if not job:
                return []
            
            response = self.client.table(self.config.PROGRESS_TABLE).select("*").eq(
                "job_id", job["id"]
            ).execute()
            
            return response.data
            
        except Exception as e:
            print(f"❌ Error getting job progress: {e}")
            return []
    
    # User Sessions
    async def get_or_create_user_session(self, user_id: int, session_type: str = "addsong") -> Optional[Dict]:
        """Get or create user session."""
        try:
            # First try to get existing active session
            response = self.client.table(self.config.USERS_TABLE).select("*").eq(
                "user_id", user_id
            ).eq("session_type", session_type).eq("is_active", True).execute()
            
            if response.data:
                return response.data[0]
            
            # Create new session
            session_data = {
                "user_id": user_id,
                "session_type": session_type,
                "current_song_data": {},
                "song_queue": [],
                "is_active": True
            }
            
            response = self.client.table(self.config.USERS_TABLE).insert(session_data).execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except Exception as e:
            print(f"❌ Error getting/creating user session: {e}")
            return None
    
    async def update_user_session(self, session_id: str, current_song_data: Dict = None,
                                song_queue: List = None, is_active: bool = None) -> bool:
        """Update user session."""
        try:
            update_data = {}
            if current_song_data is not None:
                update_data["current_song_data"] = current_song_data
            if song_queue is not None:
                update_data["song_queue"] = song_queue
            if is_active is not None:
                update_data["is_active"] = is_active
            
            update_data["updated_at"] = datetime.now().isoformat()
            
            response = self.client.table(self.config.USERS_TABLE).update(update_data).eq(
                "id", session_id
            ).execute()
            
            return len(response.data) > 0
            
        except Exception as e:
            print(f"❌ Error updating user session: {e}")
            return False
    
    # Statistics and Analytics
    async def get_job_statistics(self) -> Dict:
        """Get overall job statistics."""
        try:
            response = self.client.table(self.config.JOBS_TABLE).select("status").execute()
            
            if not response.data:
                return {"total": 0, "completed": 0, "running": 0, "failed": 0, "queued": 0}
            
            stats = {"total": len(response.data)}
            for job in response.data:
                status = job["status"]
                stats[status] = stats.get(status, 0) + 1
            
            return stats
            
        except Exception as e:
            print(f"❌ Error getting job statistics: {e}")
            return {"total": 0, "completed": 0, "running": 0, "failed": 0, "queued": 0}
    
    async def cleanup_old_jobs(self, days_old: int = 30) -> int:
        """Clean up jobs older than specified days."""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days_old)).isoformat()
            
            # Get old jobs
            response = self.client.table(self.config.JOBS_TABLE).select("id").lt(
                "created_at", cutoff_date
            ).execute()
            
            if not response.data:
                return 0
            
            job_ids = [job["id"] for job in response.data]
            
            # Delete related records first (due to foreign key constraints)
            self.client.table(self.config.SONGS_TABLE).delete().in_("job_id", job_ids).execute()
            self.client.table(self.config.PROGRESS_TABLE).delete().in_("job_id", job_ids).execute()
            self.client.table(self.config.USERS_TABLE).delete().in_("job_id", job_ids).execute()
            
            # Delete jobs
            self.client.table(self.config.JOBS_TABLE).delete().in_("id", job_ids).execute()
            
            return len(job_ids)
            
        except Exception as e:
            print(f"❌ Error cleaning up old jobs: {e}")
            return 0

# Global database service instance
database_service: Optional[SupabaseDatabaseService] = None

def get_database_service() -> SupabaseDatabaseService:
    """Get or create database service instance."""
    global database_service
    if database_service is None:
        database_service = SupabaseDatabaseService()
    return database_service