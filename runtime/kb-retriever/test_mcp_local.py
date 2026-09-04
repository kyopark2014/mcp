import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

async def main():
    mcp_url = "http://127.0.0.1:8000/mcp"
    # headers = {}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }

    _http = create_mcp_http_client(headers=headers)
    async with _http:
        async with streamable_http_client(mcp_url, http_client=_http, terminate_on_close=False) as (read_stream, write_stream):
        
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tool_result = await session.list_tools()
                print("Available tools:")
                for tool in tool_result.tools:
                    print(f"  - {tool.name}: {tool.description}")

if __name__ == "__main__":
    asyncio.run(main())