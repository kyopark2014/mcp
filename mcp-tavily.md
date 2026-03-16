## Tavily

인터넷 검색시 Tavily MCP를 이용할 수 있습니다. Tavily는 유료이지만 일 1000건까지 무료로 사용할 수 있습니다.

### MCP 설정

[mcp_server_tavily.py](./application/mcp_server_tavily.py)을 이용해 구현합니다.

```java
{
   "mcpServers":{
      "tavily-search":{
         "command":"python",
         "args":[
            "f""{workingDir}/mcp_server_tavily.py"
         ]
      }
   }
}
```

[installer.py](./installer.py)에서 secret으로 설정후에 [utils.py](./application/utils.py)에서 TAVILY_API_KEY로 등록하여 활용합니다.
