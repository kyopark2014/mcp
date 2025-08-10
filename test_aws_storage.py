#!/usr/bin/env python3
"""
AWS Storage Functionality Test Script
"""

import asyncio
import sys
import os

# Add application directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'application'))

import mcp_storage as storage

async def test_aws_functionality():
    """Test AWS functionality."""
    
    print("=== AWS Credentials Check ===")
    credentials_status = storage.check_aws_credentials()
    print(f"Credentials status: {credentials_status}")
    print()
    
    if credentials_status.get('status') == 'error':
        print("❌ There are issues with AWS credentials.")
        print("Suggestions:")
        for suggestion in credentials_status.get('suggestions', []):
            print(f"  - {suggestion}")
        return
    
    print("=== Get AWS Account Information ===")
    try:
        account_info = await storage.get_aws_account_info()
        print(f"Account information: {account_info}")
        print()
    except Exception as e:
        print(f"❌ Failed to get account information: {e}")
        print()
    
    print("=== Get S3 Bucket List ===")
    try:
        buckets = await storage.list_buckets(max_buckets=5)
        print(f"Number of buckets: {len(buckets)}")
        for bucket in buckets:
            print(f"  - {bucket['Name']} (Created: {bucket['CreationDate']})")
        print()
    except Exception as e:
        print(f"❌ Failed to get bucket list: {e}")
        print()
    
    print("=== Check Storage Usage ===")
    try:
        storage_usage = await storage.get_total_storage_usage()
        print(f"Total storage usage: {storage_usage.get('total_size_formatted', 'N/A')}")
        print(f"Number of buckets: {storage_usage.get('bucket_count', 0)}")
        print()
    except Exception as e:
        print(f"❌ Failed to check storage usage: {e}")
        print()

if __name__ == "__main__":
    print("Starting AWS storage functionality test...")
    print()
    
    asyncio.run(test_aws_functionality())
    
    print("Test completed!")
