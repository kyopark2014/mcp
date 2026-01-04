# 인프라 설치하기

## 설치하기

### 소스 다운로드 및 설치 

1) 소스를 다운로드합니다.

```java
git clone https://github.com/kyopark2014/mcp
```

2) mcp 폴더로 이동하여 installer.py로 설치합니다.

```text
cd mcp && python installer.py
```

설치 중간에 검색, 날씨, 로그 분석을 위해 외부와 같은 API에 대한 credential을 발급받아서 입력하여야 합니다.

- 일반 검색을 위하여 [Tavily Search](https://app.tavily.com/sign-in)에 접속하여 가입 후 API Key를 발급합니다. 이것은 tvly-로 시작합니다.  
- 날씨 검색을 위하여 [openweathermap](https://home.openweathermap.org/api_keys)에 접속하여 API Key를 발급합니다.
- [langsmith.md](https://github.com/kyopark2014/langgraph-agent/blob/main/langsmith.md)를 참조하여 [LangSmith](https://www.langchain.com/langsmith)에 가입후 API Key를 발급 받습니다.

[Secret manager](https://us-west-2.console.aws.amazon.com/secretsmanager/listsecrets?region=us-west-2)에 접속하여, [openweathermap-bedrock-agent](https://us-west-2.console.aws.amazon.com/secretsmanager/secret?name=openweathermap-bedrock-agent&region=us-west-2), [tavilyapikey-bedrock-agent](https://us-west-2.console.aws.amazon.com/secretsmanager/secret?name=tavilyapikey-bedrock-agent&region=us-west-2), [langsmithapikey-bedrock-agent](https://us-west-2.console.aws.amazon.com/secretsmanager/secret?name=langsmithapikey-bedrock-agent&region=us-west-2)에 접속하여, [Retrieve secret value]를 선택 후, api key를 입력합니다.


설치가 완료되면 CloudFront의 도메인으로 접속할 수 있습니다. 단, 설치 명령어 완료후에도 docker script 실행을 위해 약 15분 정도 기다린 후 실행합니다.

3) 삭제

아래와 같이 uninstaller.py로 삭제 할 수 있습니다.

```text
python uninstaller.py
```

5) [Console-SecretManage](https://us-west-2.console.aws.amazon.com/secretsmanager/listsecrets?region=us-west-2)에서 생성한 API에 대한 Credential을 입력합니다.



## 실행환경 (선택)

### CloudWatch Log 활용하기

Streamlit이 설치된 EC2에 접속해서 아래 명령어로 config를 생성합니다.

```text
cat << EOF > /tmp/config.json
{
    "agent":{
        "metrics_collection_interval":60,
        "debug":false
    },
    "metrics": {
        "namespace": "CloudWatch/BedrockAgentMetrics",
        "metrics_collected":{
          "cpu":{
             "resources":[
                "*"
             ],
             "measurement":[
                {
                   "name":"cpu_usage_idle",
                   "rename":"CPU_USAGE_IDLE",
                   "unit":"Percent"
                },
                {
                   "name":"cpu_usage_nice",
                   "unit":"Percent"
                },
                "cpu_usage_guest"
             ],
             "totalcpu":false,
             "metrics_collection_interval":10
          },
          "mem":{
             "measurement":[
                "mem_used",
                "mem_cached",
                "mem_total"
             ],
             "metrics_collection_interval":1
          },          
          "processes":{
             "measurement":[
                "running",
                "sleeping",
                "dead"
             ]
          }
       },
        "append_dimensions":{
            "InstanceId":"\${aws:InstanceId}",
            "ImageId":"\${aws:ImageId}",
            "InstanceType":"\${aws:InstanceType}",
            "AutoScalingGroupName":"\${aws:AutoScalingGroupName}"
        }
    },
    "logs":{
       "logs_collected":{
          "files":{
             "collect_list":[
                {
                   "file_path":"/var/log/application/logs.log",
                   "log_group_name":"mcp-rag.log",
                   "log_stream_name":"mcp-rag.log",
                   "timezone":"UTC"
                }
             ]
          }
       }
    }
}
EOF
```

이후 아래 명령어로 amazon-cloudwatch-agent의 환경을 업데이트하면 자동으로 실행이 됩니다.

```text
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/tmp/config.json
```

만약 정상적으로 동작하지 않는다면 아래 명령어로 상태를 확인합니다. 

```text
amazon-cloudwatch-agent-ctl -m ec2 -a status
systemctl status amazon-cloudwatch-agent
ps -ef|grep amazon-cloudwatch-agent
```

문제 발생시 로그 확인하는 방법입니다.

```text
cat /opt/aws/amazon-cloudwatch-agent/logs/configuration-validation.log
cat /opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log
```

만약 CloudWatch Agent가 설치되지 않은 instance일 경우에는 아래 명령어로 설치합니다.

```text
sudo yum install amazon-cloudwatch-agent
```

### Local에서 실행하기 

Output의 environmentforbedrockagent의 내용을 복사하여 [config.json](./application/config.json)을 업데이트 합니다. 이미 "aws configure"가 설정되어 있어야합니다.

만약 visual studio code 사용자라면 config.json 파일은 아래 명령어를 사용합니다.

```text
code application/config.json
```

아래와 같이 필요한 패키지를 설치합니다.

```text
python3 -m venv venv
source venv/bin/activate
pip install streamlit streamlit_chat 
pip install boto3 langchain_aws langchain langchain_community langgraph opensearch-py
pip install beautifulsoup4 pytz tavily-python
```

아래와 같은 명령어로 streamlit을 실행합니다. 

```text
streamlit run application/app.py
```

### EC2에서 로그를 보면서 실행하기

개발 및 검증을 위해서는 로그를 같이 보면서 실행하는것이 필요합니다. 로컬 환경에서도 충분히 테스트 가능하지만 다른 인프라와 연동이 필요할 경우에 때로는 EC2에서 실행하면서 로그를 볼 필요가 있습니다. 

아래의 명령어로 실행중인 streamlit을 중지시키고, session manager에서 streamlit을 실행합니다.

```text
sudo systemctl stop streamlit
sudo runuser -l ec2-user -c "/home/ec2-user/.local/bin/streamlit run /home/ec2-user/bedrock-agent/application/app.py"
```

이때, ec2-user의 github 코드를 업데이트하는 명령어는 아래와 같습니다.

```text
sudo runuser -l ec2-user -c 'cd /home/ec2-user/mcp-rag && git pull'
```

### Streamlit 관련 중요한 명령어들

- Streamlit 재실행 및 상태 확인

```text
sudo systemctl stop streamlit
sudo systemctl start streamlit
sudo systemctl status streamlit -l
```

- Streamlit의 환경설정 내용 확인

```text
sudo runuser -l ec2-user -c "/home/ec2-user/.local/bin/streamlit config show"
```

- Streamlit의 service 설정을 바꾸고 재실행하는 경우

```text
sudo systemctl disable streamlit.service
sudo systemctl enable streamlit.service
sudo systemctl start streamlit
```

- Steam의 지속 실행을 위해 service로 등록할때 필요한 streamlit.service의 생성

```text
sudo sh -c "cat <<EOF > /etc/systemd/system/streamlit.service
[Unit]
Description=Streamlit
After=network-online.target

[Service]
User=ec2-user
Group=ec2-user
Restart=always
ExecStart=/home/ec2-user/.local/bin/streamlit run /home/ec2-user/mcp-rag/application/app.py

[Install]
WantedBy=multi-user.target
EOF"
```

- Streamlit의 포트를 8501에서 8080으로 변경하기 위한 환겨얼정

```text
runuser -l ec2-user -c "cat <<EOF > /home/ec2-user/.streamlit/config.toml
[server]
port=${targetPort}
EOF"
```

