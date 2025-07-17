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

