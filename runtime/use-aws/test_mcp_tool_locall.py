import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def test_mcp_tools():
    """Test MCP server tools"""
    
    mcp_url = "http://127.0.0.1:8000/mcp"
    headers = {}
    
    print("Testing local MCP server with basic tools...")
    print(f"Connecting to: {mcp_url}")
    
    try:
        async with streamablehttp_client(mcp_url, headers, timeout=120, terminate_on_close=False) as (
            read_stream, write_stream, _,):
            
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                
                # Get list of available tools
                tool_result = await session.list_tools()
                print(f"\nAvailable tools: {len(tool_result.tools)}")
                for tool in tool_result.tools:
                    print(f"  - {tool.name}: {tool.description[:100]}...")
                
                # Test AWS S3 bucket list retrieval
                print("\n=== Testing AWS S3 List Buckets ===")
                s3_params = {
                    "service_name": "s3",
                    "operation_name": "list_buckets",
                    "parameters": {},
                    "region": "us-west-2",
                    "label": "List S3 buckets"
                }
                
                print("8. S3 list_buckets 호출 중...")
                try:
                    result = await asyncio.wait_for(session.call_tool("use_aws", s3_params), timeout=60)
                    print(f"10. S3 list_buckets 성공!")
                    print(f"Result: {result}")
                    
                    if hasattr(result, 'content') and result.content:
                        for content in result.content:
                            if hasattr(content, 'text'):
                                print(f"Content: {content.text}")
                except asyncio.TimeoutError:
                    print("❌ S3 list_buckets 타임아웃 (60초)")
                except Exception as s3_error:
                    print(f"❌ S3 list_buckets 실패: {s3_error}")
                
                # Test AWS EC2 instance list retrieval
                print("\n=== Testing AWS EC2 Describe Instances ===")
                ec2_params = {
                    "service_name": "ec2",
                    "operation_name": "describe_instances",
                    "parameters": {"MaxResults": 5},
                    "region": "us-west-2",
                    "label": "List EC2 instances"
                }
                
                print("9. EC2 describe_instances 호출 중...")
                try:
                    result = await asyncio.wait_for(session.call_tool("use_aws", ec2_params), timeout=60)
                    print(f"12. EC2 describe_instances 성공!")
                    print(f"Result: {result}")
                    
                    if hasattr(result, 'content') and result.content:
                        for content in result.content:
                            if hasattr(content, 'text'):
                                print(f"Content: {content.text}")
                except asyncio.TimeoutError:
                    print("❌ EC2 describe_instances 타임아웃 (60초)")
                except Exception as ec2_error:
                    print(f"❌ EC2 describe_instances 실패: {ec2_error}")
                
                print("\n=== MCP Connection Test Complete ===")                
                                
    except Exception as e:
        print(f"Error testing MCP server: {e}")
        print(f"Error type: {type(e).__name__}")

if __name__ == "__main__":
    asyncio.run(test_mcp_tools())