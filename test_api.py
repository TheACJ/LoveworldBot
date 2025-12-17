#!/usr/bin/env python3
"""
API Test Script - Tests FastAPI endpoints
Run this while the server is running: python main_supabase.py
"""

import asyncio
import json
import aiohttp
import sys
from pathlib import Path

async def test_api_endpoints():
    """Test all API endpoints."""
    base_url = "http://localhost:8000"
    
    print("=== Testing FastAPI Endpoints ===\n")
    
    async with aiohttp.ClientSession() as session:
        
        # Test 1: Health check
        print("1. Testing health check...")
        try:
            async with session.get(f"{base_url}/") as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"   ✅ Health check: {data}")
                else:
                    print(f"   ❌ Health check failed: {response.status}")
        except Exception as e:
            print(f"   ❌ Health check error: {e}")
        
        # Test 2: Create scrape job
        print("\n2. Testing job creation...")
        try:
            job_data = {
                "songs": [
                    {
                        "title": "Test Song",
                        "artist": "Test Artist",
                        "url": "https://example.com/test-song"
                    }
                ]
            }
            
            async with session.post(
                f"{base_url}/api/scrape",
                json=job_data
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"   ✅ Job created: {data}")
                    job_id = data.get("job_id")
                else:
                    print(f"   ❌ Job creation failed: {response.status}")
                    job_id = None
        except Exception as e:
            print(f"   ❌ Job creation error: {e}")
            job_id = None
        
        # Test 3: Get job status (if job was created)
        if job_id:
            print("\n3. Testing job status...")
            try:
                async with session.get(f"{base_url}/api/job/{job_id}") as response:
                    if response.status == 200:
                        data = await response.json()
                        print(f"   ✅ Job status: {data}")
                    else:
                        print(f"   ❌ Job status failed: {response.status}")
            except Exception as e:
                print(f"   ❌ Job status error: {e}")
        
        # Test 4: Test invalid job
        print("\n4. Testing invalid job...")
        try:
            async with session.get(f"{base_url}/api/job/invalid_job_123") as response:
                if response.status == 404:
                    print("   ✅ Invalid job correctly returns 404")
                else:
                    print(f"   ❌ Expected 404, got {response.status}")
        except Exception as e:
            print(f"   ❌ Invalid job test error: {e}")
        
        # Test 5: Test user jobs
        print("\n5. Testing user jobs...")
        try:
            async with session.get(f"{base_url}/api/jobs/user/12345") as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"   ✅ User jobs: {data}")
                else:
                    print(f"   ❌ User jobs failed: {response.status}")
        except Exception as e:
            print(f"   ❌ User jobs error: {e}")
        
        # Test 6: Test download endpoint (should fail for incomplete job)
        if job_id:
            print("\n6. Testing download endpoint...")
            try:
                async with session.get(f"{base_url}/api/download/{job_id}") as response:
                    if response.status == 400:
                        print("   ✅ Download correctly blocked for incomplete job")
                    else:
                        print(f"   ❌ Expected 400, got {response.status}")
            except Exception as e:
                print(f"   ❌ Download test error: {e}")
    
    print("\n=== API Testing Complete ===")

def main():
    """Main function."""
    print("FastAPI Endpoint Tester")
    print("Make sure the server is running: python main_supabase.py")
    print("This script will test all API endpoints.\n")
    
    # Check if server is likely running
    try:
        import aiohttp
    except ImportError:
        print("Installing aiohttp for testing...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp"])
        import aiohttp
    
    # Run tests
    asyncio.run(test_api_endpoints())
    
    print("\n💡 Tips:")
    print("- Run 'python main_supabase.py' first to start the server")
    print("- Check server logs for detailed information")
    print("- Test with real Supabase credentials for full functionality")

if __name__ == "__main__":
    main()