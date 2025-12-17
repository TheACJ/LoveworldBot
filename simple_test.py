#!/usr/bin/env python3
"""
Simple test script for Supabase integration
"""

import asyncio
import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.append(str(Path(__file__).parent))

async def test_basic_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    try:
        from supabase_config import SupabaseConfig
        print("✓ supabase_config imported")
        
        from supabase_storage import get_storage_service
        print("✓ supabase_storage imported")
        
        from supabase_database import get_database_service
        print("✓ supabase_database imported")
        
        from supabase_realtime import get_realtime_service
        print("✓ supabase_realtime imported")
        
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False

async def test_configuration():
    """Test configuration validation."""
    print("\nTesting configuration...")
    
    try:
        from supabase_config import SupabaseConfig
        
        # Check if .env exists
        if not Path(".env").exists():
            print("⚠ No .env file found - this is expected for testing")
            print("  The integration will work once you add your Supabase credentials")
            return True
        
        if SupabaseConfig.validate_config():
            print("✓ Configuration is valid")
            return True
        else:
            print("⚠ Configuration missing Supabase credentials")
            print("  Add your SUPABASE_URL and SUPABASE_ANON_KEY to .env")
            return True
            
    except Exception as e:
        print(f"✗ Configuration test failed: {e}")
        return False

async def test_basic_functionality():
    """Test basic functionality without external dependencies."""
    print("\nTesting basic functionality...")
    
    try:
        from supabase_config import SupabaseConfig
        
        # Test config values
        print(f"✓ Storage bucket: {SupabaseConfig.STORAGE_BUCKET_NAME}")
        print(f"✓ Auto-delete interval: {SupabaseConfig.AUTO_DELETE_INTERVAL} seconds")
        
        return True
    except Exception as e:
        print(f"✗ Functionality test failed: {e}")
        return False

async def main():
    """Main test function."""
    print("=== Supabase Integration Test ===\n")
    
    tests = [
        test_basic_imports,
        test_configuration,
        test_basic_functionality
    ]
    
    passed = 0
    for test in tests:
        try:
            result = await test()
            if result:
                passed += 1
        except Exception as e:
            print(f"Test failed: {e}")
    
    print(f"\n=== Results ===")
    print(f"Passed: {passed}/{len(tests)}")
    
    if passed == len(tests):
        print("\n✓ All tests passed!")
        print("\nNext steps:")
        print("1. Copy .env.example to .env")
        print("2. Add your Supabase credentials to .env")
        print("3. Run the setup: python SUPABASE_SETUP.md")
        print("4. Test with real credentials: python test_supabase_integration.py")
    else:
        print("\n✗ Some tests failed")
    
    return passed == len(tests)

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)