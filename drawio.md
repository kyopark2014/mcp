# draw.io 활용하기

아래와 같이 필요한 패키지를 설치합니다.

```text
npx @drawio/mcp
```

아래 MCP config를 추가합니다.

```java
{
  "mcpServers": {
    "drawio": {
      "command": "npx",
      "args": ["@drawio/mcp"]
    }
  }
}
```
