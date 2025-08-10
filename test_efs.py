#!/usr/bin/env python3
"""
EFS 기능 테스트 스크립트
"""

import asyncio
import sys
import os

# application 디렉토리를 Python 경로에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), 'application'))

import mcp_storage as storage

async def test_efs():
    """EFS 기능을 테스트합니다."""
    
    print("=== EFS Usage Test ===")
    try:
        efs_usage = await storage.get_efs_usage()
        print(f"EFS usage: {efs_usage}")
        print()
    except Exception as e:
        print(f"❌ EFS usage test failed: {e}")
        print()

if __name__ == "__main__":
    print("Starting EFS functionality test...")
    print()
    
    asyncio.run(test_efs())
    
    print("Test completed!")
