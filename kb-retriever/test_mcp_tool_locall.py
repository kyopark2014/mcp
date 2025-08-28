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
                
                # Test add_numbers function
                print("\n=== Testing add_numbers function ===")
                params = {
                    "keyword": "보일러 에러 코드"
                }
                
                result = await session.call_tool("retrieve", params)
                print(f"retrieve result: {result}")
                
                if hasattr(result, 'content') and result.content:
                    for content in result.content:
                        if hasattr(content, 'text'):
                            print(f"Content: {content.text}")
                                
    except Exception as e:
        print(f"Error testing MCP server: {e}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        print(f"Full traceback:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mcp_tools())
