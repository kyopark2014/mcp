# Obsidian MCP 설정

[Obsidian MCP 서버 사용 방법](https://apidog.com/kr/blog/obsidian-mcp-server-kr/)을 참조하여, 아래와 같이 MCP를 설정합니다.

```java
{
   "mcpServers": {
       "obsidian": {
           "command": "npx",
           "args": ["-y", "obsidian-mcp", "/path/to/your/vault"]
       }
   }
}
```

이것은 [mcp_config.py](./application/mcp_config.py)에서 아래와 같이 설정할 수 있습니다.

```python
if mcp_type == "obsidian":
    return {
        "mcpServers": {
            "obsidian": {
                "command": "npx",
                "args": ["-y", "obsidian-mcp", os.path.expanduser("~/Documents/memo")]
            }
        }
    }
```
