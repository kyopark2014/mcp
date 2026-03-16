## Notion MCP

Notion에서는 [Official Notion MCP Server](https://github.com/makenotion/notion-mcp-server)와 같은 MCP 서버를 제공하고 있습니다. 아래 방식으로 token을 생성한 후에, mcp.json에 관련정보를 설정한 후 agent에서 활용합니다.

1) [Notion API Integration](https://www.notion.so/profile/integrations)에 접속하여 [새 API 통합]을 선택합니다.
2) 아래와 같이 입력후 저장합니다.

<img width="573" height="535" alt="image" src="https://github.com/user-attachments/assets/787561ad-0b61-4a1a-91ea-72d7556e6358" />

3) API Secret를 복사합니다. 

4) 사용권한 Tab에서 적절한 페이지를 선택합니다.

<img width="664" height="340" alt="image" src="https://github.com/user-attachments/assets/872e7054-1135-4dde-aa6a-756a7ad928b0" />

### MCP 설정

Secret에서 notion api key를 가져와서 env로 넣어줍니다. 

```java
{
   "mcpServers":{
      "notionApi":{
         "command":"npx",
         "args":[
            "-y",
            "@notionhq/notion-mcp-server"
         ],
         "env":{
            "NOTION_TOKEN":"utils.notion_api_key"
         }
      }
   }
}
```
