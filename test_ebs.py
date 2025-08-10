#!/usr/bin/env python3
"""
EBS 기능 테스트 스크립트
"""

import asyncio
import sys
import os

# application 디렉토리를 Python 경로에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), 'application'))

import mcp_storage as storage

async def test_ebs():
    """EBS 기능을 테스트합니다."""
    
    print("=== EBS Volumes Usage Test ===")
    try:
        ebs_volumes = await storage.get_ebs_volumes_usage()
        print(f"EBS volumes: {ebs_volumes}")
        print()
    except Exception as e:
        print(f"❌ EBS volumes test failed: {e}")
        print()
    
    print("=== EBS Snapshots Usage Test ===")
    try:
        ebs_snapshots = await storage.get_ebs_snapshots_usage()
        print(f"EBS snapshots: {ebs_snapshots}")
        print()
    except Exception as e:
        print(f"❌ EBS snapshots test failed: {e}")
        print()

if __name__ == "__main__":
    print("Starting EBS functionality test...")
    print()
    
    asyncio.run(test_ebs())
    
    print("Test completed!")
