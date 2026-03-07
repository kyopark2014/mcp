# draw.io로 architecture 그리기

## draw.io 활용하기

[Draw.io MCP Server](https://github.com/jgraph/drawio-mcp)을 참조하여 구현할 수 있습니다.

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

## AWS의 Draw.io MCP Server 활용

[AWS의  Draw.io MCP Server](https://github.com/aws-samples/sample-drawio-mcp)을 활용하여 MCP로 제공할 수 있습니다.

```java
{
  "mcpServers": {
    "drawio": {
      "command": "npx",
      "args": [
        "-y",
        "https://github.com/aws-samples/sample-drawio-mcp/releases/latest/download/drawio-mcp-server-latest.tgz",
        "--no-cache"
      ],
      "type": "stdio"
    }
  }
}
```

이때의 결과로 drawio 파일을 얻으면, [drawio.com]([https://www.drawio.com/](https://app.diagrams.net/))을 접속한 후에 [다음에서 열기] - [URL]을 아래와 같이 선택합니다.

<img width="494" height="328" alt="image" src="https://github.com/user-attachments/assets/f9864d23-49f8-4174-bb29-cc8ddaa215b4" />

이후 생성된 drawio파일의 링크를 입력하면 아래와 같은 결과를 얻을 수 있습니다.

<img width="991" height="774" alt="image" src="https://github.com/user-attachments/assets/a81f1900-15db-4306-b5f7-88f728dc7ad8" />
