### Google Service

Google기반의 메일이나 캘린더를 가져올 때 MCP를 이용할 수 있습니다.

### GOG CLI

아래와 같이 GOG CLI를 설치합니다. 

```text
brew install steipete/tap/gogcli
```

먼저 json 형태의 credential을 다운받아야 합니다. 아래와 같은 작업을 수행합니다.

1. [Google Cloud Console](https://console.cloud.google.com)에서 OAuth 클라이언트를 만들기 위해 새 프로젝트 생성 (또는 기존 프로젝트 선택)을 수행합니다.

2. API 활성화를 위해 Gmail API, Google Calendar API, Google Drive API 을 설정합니다.


3. OAuth 동의 화면 구성은 "User Type: External"로 하고, 테스트 사용자에 본인 이메일 추가합니다.
   
4. OAuth 클라이언트 ID를 생성합니다. 이때 사용할 gmail을 테스트 사용자로 등록하여야 합니다.

- Application type: Desktop app

- 이름: "goo"

5. client_secret_xxx.json를 다운로드합니다.

브라우저가 있으면 아래와 같이 수행합니다.

```text
gog auth credentials /path/to/client_secret_xxx.json
```

이후 아래와 같이 메 일주소를 등록합니다. service를 지정하지 않으면 appscript, calendar, chat, classroom, contacts, docs, drive, forms, gmail, people, sheets, slides, tasks가 등록됩니다.

```text
gog auth add your-email@gmail.com
```

지정을 하면 아래와 같이 일부만 허용할 수 있습니다.

```text
gog auth add your-email@gmail.com --services gmail,calendar,drive,contacts
```

인증된 정보는 아래 명령어로 확인할 수 있습니다.

```text
gog auth list 
```

EC2와 같이 브라우저가 없는 경우에 dashboard에 접속해서 chat에서 "gmail을 등록해주세요"라고 입력후 주어진 가이드에 따라 수행합니다. "gog auth add"를 수행시 localhost로 수행되는 url을 받아서 client에서 수행하여야 하므로 dashboard의 chat에서 수행하여야 합니다.
