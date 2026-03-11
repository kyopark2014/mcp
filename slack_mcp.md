# Slack 설정

1. Slack App 생성
   
   - https://api.slack.com/apps 접속
   - "Create New App" → "From scratch" 선택
   - App 이름과 워크스페이스 선택

2. Bot Token Scopes 추가

   - "OAuth & Permissions" 메뉴로 이동
   - "Bot Token Scopes"에 다음 권한 추가:
     - channels:history
     - channels:read
     - chat:write
     - users:read
     - groups:history
     - groups:read

3. App 설치 및 Token 복사

   - "Install to Workspace" 클릭
   - 생성된 "Bot User OAuth Token" (xoxb-로 시작) 복사

4. Team ID 확인
   - Slack API인 https://api.slack.com/apps 접속합니다.
   - 아래와 같이 App ID를 확인할 수 있습니다.
   - MCP 등록할 때에 slack_team_id로 App ID를 사용합니다.

<img width="1025" height="270" alt="noname" src="https://github.com/user-attachments/assets/6561fc02-c348-4330-9758-cc309af9d672" />

