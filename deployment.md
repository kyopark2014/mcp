# 인프라 설치하기

## Bedrock 사용 권한 설정하기

LLM으로 Anthropic Claude, Amazon Nova을 사용하기 위하여, Amazon Bedrock의 us-west-2, us-east-1, us-east-2 리전을 사용합니다. [Model access](https://us-west-2.console.aws.amazon.com/bedrock/home?region=us-west-2#/modelaccess)에 접속해서 [Edit]를 선택하여 "Anthropic Claude", "Amazon Nova", "Titan Text Embeddings V2"의 모델들 enable 합니다.

## 설치하기

### EC2를 사용하여 설치 환경 구성하기

여기서는 편의상 us-west-2 (Oregon) 리전을 사용합니다.

#### EC2 생성

[EC2 - Launch an Instance](https://us-west-2.console.aws.amazon.com/ec2/home?region=us-west-2#LaunchInstances:)에 접속하여 Name으로 "chatbot"이라고 입력합니다.

![noname](https://github.com/user-attachments/assets/acdac538-ea1e-4b32-a7f8-efc2b0e34664)

OS로 기본값인 "Amazon Linux"를 유지하고, Amazon Machine Image (AMI)도 기본값을 그대로 사용합니다.

Instance Type은 "m5.large"를 선택하고, Key pair는 "Proceeding without a key pair"를 선택합니다. 

[Configure storage]는 편의상 80G로 변경하고 [Launch instance]를 선택하여 EC2를 설치합니다. 

![noname](https://github.com/user-attachments/assets/84edf46d-0aa8-478c-8727-1301cf32f4db)

이후 아래와 같이 instance를 선택하여 EC2 instance 화면으로 이동하거나, console에서 [EC-Instances](https://us-west-2.console.aws.amazon.com/ec2/home?region=us-west-2#Instances:)로 접속합니다. 

![noname](https://github.com/user-attachments/assets/f5c82338-3e05-4c26-bdef-642c81f2c5d2)

아래와 같이 instance에서 [Connect]를 선택하여 [Session Manager]로 접속합니다. 

#### 관련 패키지 설치

편의상 C-Shell로 변경후 필요한 패키지로 git, node.js, npm, docker를 설치하고 환경을 설절정합니다. 

```text
csh
cd && sudo yum install git nodejs npm docker -y
sudo usermod -a -G docker ec2-user
sudo newgrp docker
sudo service docker start
sudo npm install -g aws-cdk --prefix /usr/local
```

### 소스 다운로드 및 설치 

1) 소스를 다운로드합니다.

```java
git clone https://github.com/kyopark2014/mcp
```

2) cdk 폴더로 이동하여 필요한 라이브러리를 설치합니다.

```java
cd mcp/cdk-mcp-rag/ && npm install
```

3) CDK 사용을 위해 Boostraping을 수행합니다.

아래 명령어로 Account ID를 확인합니다.

```java
aws sts get-caller-identity --query Account --output text
```

아래와 같이 bootstrap을 수행합니다. 여기서 "account-id"는 상기 명령어로 확인한 12자리의 Account ID입니다. bootstrap 1회만 수행하면 되므로, 기존에 cdk를 사용하고 있었다면 bootstrap은 건너뛰어도 됩니다.

```java
cdk bootstrap aws://[account-id]/us-west-2
```

만약 AWS CLI가 설치가 안되어서 bootstrap이 실패하는 경우에는 아래 명령어로 설치합니다.

```text
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```

4) 아래 명령어로 인프라를 설치합니다.

```java
cdk deploy --require-approval never --all
```

인프라가 설치가 되면 아래와 같은 Output을 확인할 수 있습니다. 

![image](https://github.com/user-attachments/assets/05a74dcb-89ea-4e7e-9f6c-d58799c26d6f)


5) [Console-SecretManage](https://us-west-2.console.aws.amazon.com/secretsmanager/listsecrets?region=us-west-2)에서 생성한 API에 대한 Credential을 입력합니다.

검색, 날씨, 로그 분석을 위해 외부와 같은 API에 대한 credential을 발급받아서 입력합니다. 

- 일반 검색을 위하여 [Tavily Search](https://app.tavily.com/sign-in)에 접속하여 가입 후 API Key를 발급합니다. 이것은 tvly-로 시작합니다.  
- 날씨 검색을 위하여 [openweathermap](https://home.openweathermap.org/api_keys)에 접속하여 API Key를 발급합니다.
- [langsmith.md](https://github.com/kyopark2014/langgraph-agent/blob/main/langsmith.md)를 참조하여 [LangSmith](https://www.langchain.com/langsmith)에 가입후 API Key를 발급 받습니다.

[Secret manager](https://us-west-2.console.aws.amazon.com/secretsmanager/listsecrets?region=us-west-2)에 접속하여, [openweathermap-bedrock-agent](https://us-west-2.console.aws.amazon.com/secretsmanager/secret?name=openweathermap-bedrock-agent&region=us-west-2), [tavilyapikey-bedrock-agent](https://us-west-2.console.aws.amazon.com/secretsmanager/secret?name=tavilyapikey-bedrock-agent&region=us-west-2), [langsmithapikey-bedrock-agent](https://us-west-2.console.aws.amazon.com/secretsmanager/secret?name=langsmithapikey-bedrock-agent&region=us-west-2)에 접속하여, [Retrieve secret value]를 선택 후, api key를 입력합니다.


6) 만약 Streamlit에서 AWS Credential이 필요하다면, [Console-EC2](https://us-west-2.console.aws.amazon.com/ec2/home?region=us-west-2#Instances:instanceState=running)에서 "app-for-mcp-rag"을 선택한 후에 [Connect]를 선택합니다. 여러가지 옵션 중에서 Session Manager를 선택한 후에 [connect]를 접속한 후에 console로 접속합니다. 아래 명령어를 이용하여 ec2-user에 AWS Credential을 입력합니다.

```text
sudo runuser -l ec2-user -c 'aws configure'
```

AWS Credential을 입력합니다.

![noname](https://github.com/user-attachments/assets/bd372ce9-9e9b-403c-8d87-220cec1b1b90)


7) Output의 distributionDomainNameforbedrockagent의 URL을 이용하여 접속합니다. 처음 접속시에는 Knowledge base 생성등의 초기화를 하므로 수초에서 수십초 정도 기다릴 수 있습니다. 이때 실행된 화면은 아래와 같습니다.

![image](https://github.com/user-attachments/assets/82112d2a-a18e-40b6-b683-56d3513aa00c)

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

