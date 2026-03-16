## URL에서 정보 가져오기

검색된 결과에 URL이 있으면 playwright 기반의 web fetch를 이용해 필요한 정보를 markdown으로 가져올 수 있습니다.

```java
{
   "mcpServers":{
      "web_fetch":{
         "command":"npx",
         "args":[
            "-y",
            "mcp-server-fetch-typescript"
         ]
      }
   }
}
```

playwright를 위해 아래와 같은 설정을 [Dockerfile](./Dockerfile)에 포함하여야 합니다.

```text
# Install Node.js and npm (for npx)
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install mcp-server-fetch-typescript and Playwright browsers
RUN npx -y mcp-server-fetch-typescript --version 2>/dev/null || true && \
    npx playwright install --with-deps chromium
```

MAC같은 local 환경에서 실행시 아래와 같이 수동으로 설치합니다.

```text
npx playwright install --with-deps chromium
```

Web Fetch로 아래와 같이 html을 markdown으로 변환하여 활용합니다.

<img width="700" alt="image" src="https://github.com/user-attachments/assets/56dc77ea-4cb8-4317-af00-6a21ce5be9d0" />
