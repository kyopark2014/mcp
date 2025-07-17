# AWS API MCP

[aws-api-mcp-server](https://github.com/awslabs/mcp/tree/main/src/aws-api-mcp-server)에 따라 아래와 같이 AWS API MCP를 사용할 수 있습니다.

```python
{
  "mcpServers": {
    "awslabs.aws-api-mcp-server": {
      "command": "uvx",
      "args": [
        "awslabs.aws-api-mcp-server@latest"
      ],
      "env": {
        "AWS_REGION": aws_region,
        "AWS_API_MCP_WORKING_DIR": workingDir
      }
    }
  }
}
```

세부 동작은 [server.py](https://github.com/awslabs/mcp/blob/main/src/aws-api-mcp-server/awslabs/aws_api_mcp_server/server.py)을 참조합니다.


