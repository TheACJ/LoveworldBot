import asyncio
import hashlib
import mimetypes
import os
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple, BinaryIO
from datetime import datetime, timedelta
from supabase import Client
from supabase_config import get_supabase_service_client, StorageConfig, SupabaseConfig
import aiofiles

class SupabaseStorageService:
    """Supabase Storage service with auto-deletion functionality."""
    
    def __init__(self):
        self.client: Client = get_supabase_service_client()
        self.bucket_name = SupabaseConfig.STORAGE_BUCKET_NAME
        self.auto_delete_interval = SupabaseConfig.AUTO_DELETE_INTERVAL
        
    async def initialize_bucket(self) -> bool:
        """Initialize the storage bucket if it doesn't exist."""
        try:
            # Check if bucket exists
            buckets = self.client.storage.list_buckets()
            bucket_exists = any(bucket.name == self.bucket_name for bucket in buckets)
            
            if not bucket_exists:
                # Create bucket with public access disabled
                self.client.storage.create_bucket(
                    self.bucket_name,
                    options={
                        "public": False,
                        "file_size_limit": 52428800,  # 50MB
                        "allowed_mime_types": [
                            "audio/*", "text/*", "application/zip", "application/json"
                        ]
                    }
                )
                print(f"✅ Created storage bucket: {self.bucket_name}")
            
            return True
        except Exception as e:
            print(f"❌ Error initializing bucket: {e}")
            return False
    
    def _get_file_hash(self, file_path: str) -> str:
        """Generate SHA256 hash for file identification."""
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    
    def _get_file_info(self, file_path: str) -> Dict:
        """Get file information."""
        path = Path(file_path)
        return {
            "name": path.name,
            "extension": path.suffix.lower(),
            "size": path.stat().st_size,
            "mime_type": mimetypes.guess_type(file_path)[0],
            "created_at": datetime.fromtimestamp(path.stat().st_ctime)
        }
    
    def _is_file_allowed(self, file_info: Dict) -> bool:
        """Check if file type and size are allowed."""
        ext = file_info["extension"]
        size = file_info["size"]
        
        # Check file type
        allowed_types = (
            StorageConfig.ALLOWED_AUDIO_TYPES | 
            StorageConfig.ALLOWED_TEXT_TYPES | 
            StorageConfig.ALLOWED_IMAGE_TYPES
        )
        
        if ext not in allowed_types:
            return False
        
        # Check file size based on type
        if ext in StorageConfig.ALLOWED_AUDIO_TYPES and size > StorageConfig.MAX_AUDIO_SIZE:
            return False
        elif ext in StorageConfig.ALLOWED_TEXT_TYPES and size > StorageConfig.MAX_TEXT_SIZE:
            return False
        elif ext in StorageConfig.ALLOWED_IMAGE_TYPES and size > StorageConfig.MAX_IMAGE_SIZE:
            return False
        
        return True
    
    def _get_storage_path(self, file_info: Dict, job_id: str, file_type: str) -> str:
        """Generate storage path for file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_map = {
            "audio": StorageConfig.AUDIO_PATH,
            "lyrics": StorageConfig.LYRICS_PATH,
            "archive": StorageConfig.ARCHIVES_PATH,
            "temp": StorageConfig.TEMP_PATH
        }
        
        folder = folder_map.get(file_type, StorageConfig.TEMP_PATH)
        filename = f"{timestamp}_{file_info['name']}"
        
        return f"{job_id}/{folder}/{filename}"
    
    async def upload_file(self, local_file_path: str, job_id: str, 
                         file_type: str = "temp") -> Optional[Dict]:
        """Upload file to Supabase Storage."""
        try:
            file_info = self._get_file_info(local_file_path)
            
            if not self._is_file_allowed(file_info):
                raise ValueError(f"File type or size not allowed: {file_info}")
            
            storage_path = self._get_storage_path(file_info, job_id, file_type)
            
            # Upload file
            with open(local_file_path, 'rb') as file:
                response = self.client.storage.from_(self.bucket_name).upload(
                    storage_path, 
                    file,
                    file_options={
                        "content-type": file_info["mime_type"]
                    }
                )
            
            if response:
                return {
                    "storage_path": storage_path,
                    "file_info": file_info,
                    "uploaded_at": datetime.now().isoformat(),
                    "job_id": job_id,
                    "file_type": file_type
                }
            return None
            
        except Exception as e:
            print(f"❌ Error uploading file {local_file_path}: {e}")
            return None
    
    async def upload_file_from_bytes(self, file_data: bytes, filename: str, 
                                   job_id: str, file_type: str = "temp",
                                   mime_type: str = None) -> Optional[Dict]:
        """Upload file from bytes data."""
        try:
            if mime_type is None:
                mime_type = mimetypes.guess_type(filename)[0]
            
            storage_path = self._get_storage_path(
                {"name": filename}, job_id, file_type
            )
            
            response = self.client.storage.from_(self.bucket_name).upload(
                storage_path,
                file_data,
                file_options={"content-type": mime_type}
            )
            
            if response:
                return {
                    "storage_path": storage_path,
                    "filename": filename,
                    "size": len(file_data),
                    "mime_type": mime_type,
                    "uploaded_at": datetime.now().isoformat(),
                    "job_id": job_id,
                    "file_type": file_type
                }
            return None
            
        except Exception as e:
            print(f"❌ Error uploading file from bytes: {e}")
            return None
    
    async def download_file(self, storage_path: str) -> Optional[bytes]:
        """Download file from Supabase Storage."""
        try:
            response = self.client.storage.from_(self.bucket_name).download(storage_path)
            return response
        except Exception as e:
            print(f"❌ Error downloading file {storage_path}: {e}")
            return None
    
    async def get_signed_url(self, storage_path: str, expires_in: int = 3600) -> Optional[str]:
        """Get signed URL for file download."""
        try:
            response = self.client.storage.from_(self.bucket_name).create_signed_url(
                storage_path, expires_in
            )
            return response.get("signedURL")
        except Exception as e:
            print(f"❌ Error creating signed URL for {storage_path}: {e}")
            return None
    
    async def delete_file(self, storage_path: str) -> bool:
        """Delete file from Supabase Storage."""
        try:
            response = self.client.storage.from_(self.bucket_name).remove([storage_path])
            return len(response) > 0
        except Exception as e:
            print(f"❌ Error deleting file {storage_path}: {e}")
            return False
    
    async def create_archive_and_upload(self, local_folder_path: str, 
                                      job_id: str) -> Optional[Dict]:
        """Create ZIP archive and upload to storage."""
        try:
            import zipfile
            import tempfile
            
            # Create temporary ZIP file
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
                zip_path = temp_zip.name
            
            # Create ZIP archive
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                folder_path = Path(local_folder_path)
                if folder_path.exists():
                    for file_path in folder_path.rglob('*'):
                        if file_path.is_file():
                            arcname = file_path.relative_to(folder_path)
                            zipf.write(file_path, arcname)
            
            # Upload ZIP file
            upload_result = await self.upload_file(zip_path, job_id, "archive")
            
            # Clean up temporary file
            os.unlink(zip_path)
            
            return upload_result
            
        except Exception as e:
            print(f"❌ Error creating archive for job {job_id}: {e}")
            return None
    
    async def cleanup_old_files(self) -> Dict[str, int]:
        """Clean up files older than the specified interval."""
        try:
            # List all objects in the bucket
            objects = self.client.storage.from_(self.bucket_name).list()
            
            deleted_count = 0
            error_count = 0
            current_time = time.time()
            
            for obj in objects:
                # Get file metadata
                file_path = obj.get('name')
                if not file_path:
                    continue
                
                # Get object metadata
                try:
                    metadata = self.client.storage.from_(self.bucket_name).get_public_metadata(file_path)
                    created_at = metadata.get('created_at')
                    
                    if created_at:
                        # Parse created_at timestamp
                        file_time = datetime.fromisoformat(created_at.replace('Z', '+00:00')).timestamp()
                        
                        # Check if file is older than auto-delete interval
                        if current_time - file_time > self.auto_delete_interval:
                            # Delete file
                            if await self.delete_file(file_path):
                                deleted_count += 1
                            else:
                                error_count += 1
                                
                except Exception as e:
                    print(f"⚠️  Error processing file {file_path}: {e}")
                    error_count += 1
            
            return {
                "deleted_files": deleted_count,
                "errors": error_count,
                "cleanup_time": datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Error during cleanup: {e}")
            return {"deleted_files": 0, "errors": 1, "error_message": str(e)}
    
    async def start_auto_cleanup_scheduler(self):
        """Start automatic cleanup scheduler."""
        async def cleanup_task():
            while True:
                try:
                    await asyncio.sleep(self.auto_delete_interval)
                    result = await self.cleanup_old_files()
                    print(f"🧹 Cleanup completed: {result}")
                except Exception as e:
                    print(f"❌ Cleanup task error: {e}")
        
        # Start cleanup task in background
        asyncio.create_task(cleanup_task())
    
    async def get_file_info(self, storage_path: str) -> Optional[Dict]:
        """Get file information from storage."""
        try:
            metadata = self.client.storage.from_(self.bucket_name).get_public_metadata(storage_path)
            return metadata
        except Exception as e:
            print(f"❌ Error getting file info for {storage_path}: {e}")
            return None
    
    async def list_job_files(self, job_id: str) -> List[Dict]:
        """List all files for a specific job."""
        try:
            objects = self.client.storage.from_(self.bucket_name).list(
                prefix=f"{job_id}/",
                limit=100
            )
            
            files_info = []
            for obj in objects:
                if obj.get('name'):
                    metadata = await self.get_file_info(obj['name'])
                    files_info.append({
                        "path": obj['name'],
                        "size": obj.get('metadata', {}).get('size', 0),
                        "created_at": metadata.get('created_at') if metadata else None,
                        "type": obj['name'].split('/')[-2] if '/' in obj['name'] else 'unknown'
                    })
            
            return files_info
            
        except Exception as e:
            print(f"❌ Error listing job files for {job_id}: {e}")
            return []

# Global storage service instance
storage_service: Optional[SupabaseStorageService] = None

def get_storage_service() -> SupabaseStorageService:
    """Get or create storage service instance."""
    global storage_service
    if storage_service is None:
        storage_service = SupabaseStorageService()
    return storage_service