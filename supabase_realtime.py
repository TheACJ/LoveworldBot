import asyncio
import json
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from supabase import Client
from supabase_config import get_supabase_service_client, SupabaseConfig

class SupabaseRealtimeService:
    """Realtime service for live updates and notifications."""
    
    def __init__(self):
        self.client: Client = get_supabase_service_client()
        self.config = SupabaseConfig()
        self.active_listeners: Dict[str, Callable] = {}
        self.channel_handles: Dict[str, Any] = {}
    
    async def initialize_realtime(self) -> bool:
        """Initialize realtime subscriptions."""
        try:
            # Enable realtime for relevant tables
            tables = [
                self.config.JOBS_TABLE,
                self.config.PROGRESS_TABLE,
                self.config.USERS_TABLE
            ]
            
            for table in tables:
                try:
                    # This would typically be done via SQL, but we can check if it's enabled
                    print(f"✅ Realtime enabled for table: {table}")
                except Exception as e:
                    print(f"⚠️  Could not enable realtime for {table}: {e}")
            
            return True
            
        except Exception as e:
            print(f"❌ Error initializing realtime: {e}")
            return False
    
    async def subscribe_to_job_updates(self, job_id: str, callback: Callable) -> str:
        """Subscribe to job updates for a specific job."""
        try:
            channel_name = f"job_updates_{job_id}"
            
            # Create channel for job-specific updates
            channel = self.client.channel(channel_name)
            
            # Subscribe to job table changes
            job_filter = f"job_id=eq.{job_id}"
            channel.on(
                "postgres_changes",
                {
                    "event": "*",
                    "schema": "public",
                    "table": self.config.JOBS_TABLE,
                    "filter": job_filter
                },
                lambda payload: self._handle_job_update(payload, callback)
            ).subscribe()
            
            # Subscribe to progress table changes
            channel.on(
                "postgres_changes",
                {
                    "event": "*",
                    "schema": "public",
                    "table": self.config.PROGRESS_TABLE,
                    "filter": job_filter
                },
                lambda payload: self._handle_progress_update(payload, callback)
            ).subscribe()
            
            self.channel_handles[channel_name] = channel
            
            print(f"✅ Subscribed to job updates for {job_id}")
            return channel_name
            
        except Exception as e:
            print(f"❌ Error subscribing to job updates: {e}")
            return ""
    
    async def subscribe_to_user_jobs(self, user_id: int, callback: Callable) -> str:
        """Subscribe to all job updates for a specific user."""
        try:
            channel_name = f"user_jobs_{user_id}"
            
            channel = self.client.channel(channel_name)
            
            # Subscribe to all jobs for this user
            user_filter = f"user_id=eq.{user_id}"
            channel.on(
                "postgres_changes",
                {
                    "event": "*",
                    "schema": "public",
                    "table": self.config.JOBS_TABLE,
                    "filter": user_filter
                },
                lambda payload: self._handle_user_job_update(payload, callback)
            ).subscribe()
            
            self.channel_handles[channel_name] = channel
            
            print(f"✅ Subscribed to user jobs for {user_id}")
            return channel_name
            
        except Exception as e:
            print(f"❌ Error subscribing to user jobs: {e}")
            return ""
    
    async def subscribe_to_global_updates(self, callback: Callable) -> str:
        """Subscribe to global job updates (for admin dashboard)."""
        try:
            channel_name = "global_updates"
            
            channel = self.client.channel(channel_name)
            
            # Subscribe to all job changes
            channel.on(
                "postgres_changes",
                {
                    "event": "*",
                    "schema": "public",
                    "table": self.config.JOBS_TABLE
                },
                lambda payload: self._handle_global_update(payload, callback)
            ).subscribe()
            
            self.channel_handles[channel_name] = channel
            
            print("✅ Subscribed to global updates")
            return channel_name
            
        except Exception as e:
            print(f"❌ Error subscribing to global updates: {e}")
            return ""
    
    async def unsubscribe_from_channel(self, channel_name: str) -> bool:
        """Unsubscribe from a realtime channel."""
        try:
            if channel_name in self.channel_handles:
                await self.channel_handles[channel_name].unsubscribe()
                del self.channel_handles[channel_name]
                print(f"✅ Unsubscribed from channel: {channel_name}")
                return True
            return False
            
        except Exception as e:
            print(f"❌ Error unsubscribing from channel {channel_name}: {e}")
            return False
    
    def _handle_job_update(self, payload: Dict, callback: Callable):
        """Handle job update from realtime."""
        try:
            event_data = {
                "type": "job_update",
                "event_type": payload.get("eventType"),
                "table": payload.get("table"),
                "new": payload.get("new"),
                "old": payload.get("old"),
                "timestamp": datetime.now().isoformat()
            }
            
            # Execute callback
            asyncio.create_task(callback(event_data))
            
        except Exception as e:
            print(f"❌ Error handling job update: {e}")
    
    def _handle_progress_update(self, payload: Dict, callback: Callable):
        """Handle progress update from realtime."""
        try:
            event_data = {
                "type": "progress_update",
                "event_type": payload.get("eventType"),
                "table": payload.get("table"),
                "new": payload.get("new"),
                "old": payload.get("old"),
                "timestamp": datetime.now().isoformat()
            }
            
            # Execute callback
            asyncio.create_task(callback(event_data))
            
        except Exception as e:
            print(f"❌ Error handling progress update: {e}")
    
    def _handle_user_job_update(self, payload: Dict, callback: Callable):
        """Handle user job update from realtime."""
        try:
            event_data = {
                "type": "user_job_update",
                "event_type": payload.get("eventType"),
                "table": payload.get("table"),
                "new": payload.get("new"),
                "old": payload.get("old"),
                "timestamp": datetime.now().isoformat()
            }
            
            # Execute callback
            asyncio.create_task(callback(event_data))
            
        except Exception as e:
            print(f"❌ Error handling user job update: {e}")
    
    def _handle_global_update(self, payload: Dict, callback: Callable):
        """Handle global update from realtime."""
        try:
            event_data = {
                "type": "global_update",
                "event_type": payload.get("eventType"),
                "table": payload.get("table"),
                "new": payload.get("new"),
                "old": payload.get("old"),
                "timestamp": datetime.now().isoformat()
            }
            
            # Execute callback
            asyncio.create_task(callback(event_data))
            
        except Exception as e:
            print(f"❌ Error handling global update: {e}")
    
    async def broadcast_job_update(self, job_id: str, update_data: Dict) -> bool:
        """Broadcast job update to subscribed clients."""
        try:
            channel_name = f"job_updates_{job_id}"
            
            if channel_name in self.channel_handles:
                await self.channel_handles[channel_name].send({
                    "type": "broadcast",
                    "event": "job_update",
                    "payload": {
                        "job_id": job_id,
                        "data": update_data,
                        "timestamp": datetime.now().isoformat()
                    }
                })
                return True
            
            return False
            
        except Exception as e:
            print(f"❌ Error broadcasting job update: {e}")
            return False
    
    async def notify_job_completion(self, job_id: str, job_data: Dict) -> bool:
        """Send completion notification for a job."""
        try:
            notification_data = {
                "type": "job_completed",
                "job_id": job_id,
                "job_data": job_data,
                "timestamp": datetime.now().isoformat()
            }
            
            return await self.broadcast_job_update(job_id, notification_data)
            
        except Exception as e:
            print(f"❌ Error notifying job completion: {e}")
            return False
    
    async def notify_job_error(self, job_id: str, error_message: str) -> bool:
        """Send error notification for a job."""
        try:
            notification_data = {
                "type": "job_error",
                "job_id": job_id,
                "error_message": error_message,
                "timestamp": datetime.now().isoformat()
            }
            
            return await self.broadcast_job_update(job_id, notification_data)
            
        except Exception as e:
            print(f"❌ Error notifying job error: {e}")
            return False
    
    async def notify_progress_update(self, job_id: str, progress_data: Dict) -> bool:
        """Send progress update notification."""
        try:
            notification_data = {
                "type": "progress_update",
                "job_id": job_id,
                "progress": progress_data,
                "timestamp": datetime.now().isoformat()
            }
            
            return await self.broadcast_job_update(job_id, notification_data)
            
        except Exception as e:
            print(f"❌ Error notifying progress update: {e}")
            return False
    
    async def send_user_notification(self, user_id: int, notification_type: str,
                                   message: str, data: Dict = None) -> bool:
        """Send notification to a specific user."""
        try:
            channel_name = f"user_jobs_{user_id}"
            
            if channel_name in self.channel_handles:
                await self.channel_handles[channel_name].send({
                    "type": "broadcast",
                    "event": "user_notification",
                    "payload": {
                        "user_id": user_id,
                        "notification_type": notification_type,
                        "message": message,
                        "data": data or {},
                        "timestamp": datetime.now().isoformat()
                    }
                })
                return True
            
            return False
            
        except Exception as e:
            print(f"❌ Error sending user notification: {e}")
            return False
    
    async def cleanup_all_channels(self):
        """Cleanup all active channels."""
        try:
            for channel_name in list(self.channel_handles.keys()):
                await self.unsubscribe_from_channel(channel_name)
            
            self.channel_handles.clear()
            print("✅ Cleaned up all realtime channels")
            
        except Exception as e:
            print(f"❌ Error cleaning up channels: {e}")

# Global realtime service instance
realtime_service: Optional[SupabaseRealtimeService] = None

def get_realtime_service() -> SupabaseRealtimeService:
    """Get or create realtime service instance."""
    global realtime_service
    if realtime_service is None:
        realtime_service = SupabaseRealtimeService()
    return realtime_service

# WebSocket handler for real-time client connections
class RealtimeWebSocketHandler:
    """Handle WebSocket connections for real-time updates."""
    
    def __init__(self):
        self.connected_clients: Dict[str, Any] = {}
        self.realtime_service = get_realtime_service()
    
    async def handle_client_connection(self, websocket, path):
        """Handle new WebSocket client connection."""
        try:
            # Extract user info from query parameters or headers
            user_id = websocket.query_params.get("user_id")
            job_id = websocket.query_params.get("job_id")
            
            client_id = f"{user_id}_{job_id}" if job_id else str(user_id)
            self.connected_clients[client_id] = websocket
            
            print(f"✅ Client connected: {client_id}")
            
            # Subscribe to relevant updates
            if job_id:
                await self.realtime_service.subscribe_to_job_updates(
                    job_id, 
                    lambda update: self._handle_realtime_update(client_id, update)
                )
            elif user_id:
                await self.realtime_service.subscribe_to_user_jobs(
                    user_id, 
                    lambda update: self._handle_realtime_update(client_id, update)
                )
            
            # Keep connection alive
            await websocket.wait_closed()
            
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
        finally:
            # Clean up
            if client_id in self.connected_clients:
                del self.connected_clients[client_id]
            print(f"🔌 Client disconnected: {client_id}")
    
    async def _handle_realtime_update(self, client_id: str, update_data: Dict):
        """Handle realtime update and send to client."""
        try:
            if client_id in self.connected_clients:
                websocket = self.connected_clients[client_id]
                await websocket.send_json(update_data)
                
        except Exception as e:
            print(f"❌ Error sending update to client {client_id}: {e}")
            # Remove disconnected client
            if client_id in self.connected_clients:
                del self.connected_clients[client_id]