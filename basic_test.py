#!/usr/bin/env python3
"""
Basic test for Supabase integration - No Unicode characters
"""

import asyncio
import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.append(str(Path(__file__).parent))

async def test_imports():
    print("Testing imports...")
    
    try:
        from supabase_config import SupabaseConfig
        print("PASS: supabase_config imported")
        
        from supabase_storage import get_storage_service
        print("PASS: supabase_storage imported")
        
        from supabase_database import get_database_service
        print("PASS: supabase_database imported")
        
        from supabase_realtime import get_realtime_service
        print("PASS: supabase_realtime imported")
        
        return True
    except Exception as e:
        print(f"FAIL: Import failed - {e}")
        return False

async def test_config():
    print("\nTesting configuration...")
    
    try:
        from supabase_config import SupabaseConfig
        
        # Check config values
        print(f"PASS: Storage bucket = {SupabaseConfig.STORAGE_BUCKET_NAME}")
        print(f"PASS: Auto-delete = {SupabaseConfig.AUTO_DELETE_INTERVAL} seconds")
        
        return True
    except Exception as e:
        print(f"FAIL: Config test failed - {e}")
        return False

async def main():
    print("=== Supabase Integration Test ===")
    
    tests = [test_imports, test_config]
    passed = 0
    
    for test in tests:
        try:
            if await test():
                passed += 1
        except Exception as e:
            print(f"Test error: {e}")
    
    print(f"\n=== Results ===")
    print(f"Passed: {passed}/{len(tests)}")
    
    if passed == len(tests):
        print("\nSUCCESS: All basic tests passed!")
        print("\nIntegration is properly set up.")
        print("Next steps:")
        print("1. Add Supabase credentials to .env file")
        print("2. Run database schema in Supabase")
        print("3. Test with real credentials")
    else:
        print("\nFAILURE: Some tests failed")
    
    return passed == len(tests)

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)