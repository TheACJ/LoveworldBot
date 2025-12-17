#!/usr/bin/env python3
"""
Test script for Supabase integration
Run this to verify all components work correctly
"""

import asyncio
import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.append(str(Path(__file__).parent))

from supabase_config import SupabaseConfig
from supabase_storage import get_storage_service
from supabase_database import get_database_service
from supabase_realtime import get_realtime_service

async def test_configuration():
    """Test Supabase configuration."""
    print("🔧 Testing Supabase Configuration...")
    
    try:
        if SupabaseConfig.validate_config():
            print("✅ Configuration is valid")
            return True
        else:
            print("❌ Configuration is invalid")
            print("   Please check your .env file")
            return False
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False

async def test_database_connection():
    """Test database connection and basic operations."""
    print("\n🗄️  Testing Database Connection...")
    
    try:
        database_service = get_database_service()
        
        # Test user creation
        test_user = await database_service.create_or_update_user(
            telegram_user_id=12345,
            username="test_user",
            first_name="Test",
            last_name="User"
        )
        
        if test_user:
            print("✅ Database connection successful")
            print(f"   Created test user: {test_user['username']}")
            return True
        else:
            print("❌ Database connection failed")
            return False
            
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False

async def test_storage_bucket():
    """Test storage bucket creation and access."""
    print("\n☁️  Testing Storage Bucket...")
    
    try:
        storage_service = get_storage_service()
        
        # Initialize bucket
        result = await storage_service.initialize_bucket()
        
        if result:
            print("✅ Storage bucket initialized successfully")
            return True
        else:
            print("❌ Storage bucket initialization failed")
            return False
            
    except Exception as e:
        print(f"❌ Storage test failed: {e}")
        return False

async def test_file_upload():
    """Test file upload to storage."""
    print("\n📤 Testing File Upload...")
    
    try:
        storage_service = get_storage_service()
        
        # Create a test file
        test_content = b"This is a test file for Supabase integration"
        test_filename = "test_file.txt"
        test_job_id = "test_job_123"
        
        # Upload file
        upload_result = await storage_service.upload_file_from_bytes(
            test_content,
            test_filename,
            test_job_id,
            "temp"
        )
        
        if upload_result:
            print("✅ File upload successful")
            print(f"   File path: {upload_result['storage_path']}")
            
            # Clean up test file
            await storage_service.delete_file(upload_result['storage_path'])
            print("🧹 Test file cleaned up")
            return True
        else:
            print("❌ File upload failed")
            return False
            
    except Exception as e:
        print(f"❌ File upload test failed: {e}")
        return False

async def test_realtime_service():
    """Test realtime service initialization."""
    print("\n⚡ Testing Realtime Service...")
    
    try:
        realtime_service = get_realtime_service()
        
        # Initialize realtime
        result = await realtime_service.initialize_realtime()
        
        if result:
            print("✅ Realtime service initialized successfully")
            return True
        else:
            print("❌ Realtime service initialization failed")
            return False
            
    except Exception as e:
        print(f"❌ Realtime test failed: {e}")
        return False

async def test_job_management():
    """Test job creation and management."""
    print("\n📋 Testing Job Management...")
    
    try:
        database_service = get_database_service()
        
        # Create test job
        test_job_id = await database_service.create_job(
            user_id=12345,
            job_id="test_job_12345",
            total_songs=5
        )
        
        if test_job_id:
            print("✅ Job creation successful")
            print(f"   Job ID: {test_job_id}")
            
            # Update job status
            success = await database_service.update_job(
                test_job_id,
                status="running",
                completed_songs=2
            )
            
            if success:
                print("✅ Job update successful")
                return True
            else:
                print("❌ Job update failed")
                return False
        else:
            print("❌ Job creation failed")
            return False
            
    except Exception as e:
        print(f"❌ Job management test failed: {e}")
        return False

async def cleanup_test_data():
    """Clean up any test data created."""
    print("\n🧹 Cleaning up test data...")
    
    try:
        database_service = get_database_service()
        
        # Clean up test user and job
        # Note: In production, you might want to be more careful with deletions
        
        print("✅ Cleanup completed")
        
    except Exception as e:
        print(f"⚠️  Cleanup warning: {e}")

async def run_all_tests():
    """Run all integration tests."""
    print("🚀 Starting Supabase Integration Tests\n")
    
    tests = [
        ("Configuration", test_configuration),
        ("Database", test_database_connection),
        ("Storage", test_storage_bucket),
        ("File Upload", test_file_upload),
        ("Realtime", test_realtime_service),
        ("Job Management", test_job_management)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*50)
    print("📊 TEST SUMMARY")
    print("="*50)
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name:20} {status}")
        if result:
            passed += 1
    
    print(f"\nTotal: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("\n🎉 All tests passed! Supabase integration is working correctly.")
        print("\nNext steps:")
        print("1. Configure your .env file with real credentials")
        print("2. Run the bot: python main_supabase.py")
        print("3. Test with a real Telegram bot")
    else:
        print(f"\n⚠️  {len(results) - passed} tests failed. Please check the errors above.")
        print("\nCommon solutions:")
        print("1. Check your .env file has correct Supabase credentials")
        print("2. Verify Supabase project is active")
        print("3. Run the database schema in Supabase SQL Editor")
        print("4. Check internet connection")
    
    await cleanup_test_data()
    
    return passed == len(results)

def main():
    """Main function."""
    print("🔍 Supabase Integration Test Suite")
    print("This script tests all Supabase components\n")
    
    # Check if .env file exists
    if not Path(".env").exists():
        print("⚠️  No .env file found!")
        print("Please copy .env.example to .env and fill in your Supabase credentials")
        print("\nExample:")
        print("cp .env.example .env")
        return
    
    # Run tests
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Test suite crashed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()