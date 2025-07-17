# AWS Knowledge MCP Server

[aws-knowledge-mcp-server](https://github.com/awslabs/mcp/tree/main/src/aws-knowledge-mcp-server)에 따라 MCP 서버를 이용해 AWS 관련 지식을 검색할 수 있습니다.

검색할 수 있는 문서들은 아래와 같습니다.

- The latest AWS docs
- API references
- What's New posts
- Getting Started information
- Builder Center
- Blog posts
- Architectural references
- Well-Architected guidance

이를 위한 Config는 아래와 같습니다.

```java
{
    "mcpServers": {
        "aws-knowledge-mcp-server": {
            "url": "https://knowledge-mcp.global.api.aws"
        }
    }
}
```
