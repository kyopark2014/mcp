# AWS Infrastructure Installer

boto3를 사용하여 AWS 인프라 리소스를 생성하는 Python 스크립트입니다.  
CDK 스택과 동등한 AWS 인프라를 프로그래밍 방식으로 배포합니다.

## 목차

1. [개요](#개요)
2. [설정값](#설정값)
3. [생성되는 리소스](#생성되는-리소스)
4. [주요 함수](#주요-함수)
5. [실행 방법](#실행-방법)
6. [배포 순서](#배포-순서)

---

## 개요

이 스크립트는 AI 기반 채팅 애플리케이션을 위한 전체 AWS 인프라를 자동으로 생성합니다.

### 주요 특징
- **완전 자동화**: 단일 스크립트로 전체 인프라 배포
- **멱등성**: 이미 존재하는 리소스는 재사용
- **에러 핸들링**: 각 단계별 예외 처리 및 롤백 지원
- **로깅**: 상세한 배포 진행 상황 출력

---

## 설정값

```python
# 기본 설정
project_name = "es-us"          # 프로젝트 이름 (최소 3자)
region = "us-west-2"            # AWS 리전
git_name = "es-us-project"      # Git 저장소 이름

# 자동 생성되는 변수
account_id = sts_client.get_caller_identity()["Account"]
bucket_name = f"storage-for-{project_name}-{account_id}-{region}"
vector_index_name = project_name

# 커스텀 헤더 (CloudFront-ALB 통신용)
custom_header_name = "X-Custom-Header"
custom_header_value = f"{project_name}_12dab15e4s31"
```

---

## 생성되는 리소스

### 1. S3 버킷
- **이름**: `storage-for-{project_name}-{account_id}-{region}`
- **설정**: 
  - CORS 활성화 (GET, POST, PUT)
  - 퍼블릭 액세스 차단
  - `docs/` 폴더 자동 생성

### 2. IAM 역할

| 역할 | 설명 |
|------|------|
| `role-knowledge-base-for-{project_name}-{region}` | Bedrock Knowledge Base용 역할 |
| `role-agent-for-{project_name}-{region}` | Bedrock Agent용 역할 |
| `role-ec2-for-{project_name}-{region}` | EC2 인스턴스용 역할 |
| `role-lambda-rag-for-{project_name}-{region}` | Lambda RAG용 역할 |
| `role-agentcore-memory-for-{project_name}-{region}` | AgentCore Memory용 역할 |

### 3. Secrets Manager
- `openweathermap-{project_name}`: Weather API 키
- `tavilyapikey-{project_name}`: Tavily API 키

### 4. OpenSearch Serverless
- **컬렉션**: Vector 검색용 서버리스 컬렉션
- **정책**: 암호화, 네트워크, 데이터 액세스 정책
- **인덱스**: KNN 벡터 검색 인덱스 (1024차원)

### 5. VPC 네트워킹

```
VPC (10.20.0.0/16)
├── Public Subnets (2개 AZ)
│   ├── Internet Gateway 연결
│   └── NAT Gateway 호스팅
├── Private Subnets (2개 AZ)
│   └── NAT Gateway를 통한 아웃바운드
├── Security Groups
│   ├── ALB SG (포트 80)
│   └── EC2 SG (포트 8501, 443)
└── VPC Endpoints
    └── Bedrock Runtime 엔드포인트
```

### 6. Application Load Balancer
- **타입**: Internet-facing Application Load Balancer
- **리스너**: HTTP 포트 80
- **타겟 그룹**: EC2 인스턴스 (포트 8501)

### 7. CloudFront 배포
- **오리진**: 
  - 기본: ALB (동적 컨텐츠)
  - `/images/*`, `/docs/*`: S3 (정적 컨텐츠)
- **캐시 정책**: Managed-CachingDisabled
- **프로토콜**: HTTP → HTTPS 리다이렉트

### 8. EC2 인스턴스
- **타입**: t3.medium
- **AMI**: Amazon Linux 2023 ECS Optimized
- **볼륨**: 80GB gp3 (암호화)
- **배포 위치**: Private Subnet

### 9. Bedrock Knowledge Base
- **스토리지**: OpenSearch Serverless
- **임베딩 모델**: Amazon Titan Embed Text v2 (1024차원)
- **파싱 모델**: Claude Sonnet
- **청킹**: Hierarchical (1500/300 토큰)

---

## 주요 함수

### 인프라 생성 함수

#### `create_s3_bucket()`
S3 버킷 생성 및 CORS, 퍼블릭 액세스 차단 설정

```python
def create_s3_bucket() -> str:
    """Create S3 bucket with CORS configuration."""
    # 버킷 생성
    # CORS 설정 (GET, POST, PUT 허용)
    # 퍼블릭 액세스 차단
    # docs/ 폴더 생성
    return bucket_name
```

#### `create_iam_role()`
IAM 역할 생성 및 관리형 정책 연결

```python
def create_iam_role(role_name: str, assume_role_policy: Dict, 
                    managed_policies: Optional[List[str]] = None) -> str:
    """Create IAM role."""
    # 역할 생성
    # Trust Policy 설정
    # 관리형 정책 연결
    return role_arn
```

#### `create_opensearch_collection()`
OpenSearch Serverless 컬렉션 및 보안 정책 생성

```python
def create_opensearch_collection(ec2_role_arn: str = None, 
                                 knowledge_base_role_arn: str = None) -> Dict[str, str]:
    """Create OpenSearch Serverless collection and policies."""
    # 암호화 정책 생성
    # 네트워크 정책 생성 (퍼블릭 액세스)
    # 데이터 액세스 정책 생성
    # 컬렉션 생성 (VECTORSEARCH 타입)
    return {"arn": collection_arn, "endpoint": collection_endpoint}
```

#### `create_vpc()`
VPC, 서브넷, 보안 그룹, VPC 엔드포인트 생성

```python
def create_vpc() -> Dict[str, str]:
    """Create VPC with subnets and security groups."""
    # VPC 생성 (DNS 활성화)
    # 퍼블릭/프라이빗 서브넷 생성
    # Internet Gateway, NAT Gateway 생성
    # 보안 그룹 생성
    # VPC 엔드포인트 생성
    return {
        "vpc_id": vpc_id,
        "public_subnets": public_subnets,
        "private_subnets": private_subnets,
        "alb_sg_id": alb_sg_id,
        "ec2_sg_id": ec2_sg_id
    }
```

#### `create_alb()`
Application Load Balancer 생성

```python
def create_alb(vpc_info: Dict[str, str]) -> Dict[str, str]:
    """Create Application Load Balancer."""
    # 최소 2개 AZ의 퍼블릭 서브넷 검증
    # 보안 그룹 연결
    # Internet-facing ALB 생성
    return {"arn": alb_arn, "dns": alb_dns}
```

#### `create_cloudfront_distribution()`
CloudFront 배포 생성 (ALB + S3 하이브리드)

```python
def create_cloudfront_distribution(alb_info: Dict[str, str], 
                                   s3_bucket_name: str) -> Dict[str, str]:
    """Create CloudFront distribution with hybrid ALB + S3 origins."""
    # Origin Access Identity 생성
    # S3 버킷 정책 업데이트
    # CloudFront 배포 생성
    #   - 기본 오리진: ALB
    #   - /images/*, /docs/*: S3
    return {"id": distribution_id, "domain": distribution_domain}
```

#### `create_ec2_instance()`
EC2 인스턴스 생성 및 User Data 스크립트 설정

```python
def create_ec2_instance(vpc_info: Dict[str, str], ec2_role_arn: str, 
                        knowledge_base_role_arn: str, opensearch_info: Dict[str, str],
                        s3_bucket_name: str, cloudfront_domain: str, 
                        knowledge_base_id: str) -> str:
    """Create EC2 instance."""
    # 최신 Amazon Linux 2023 AMI 조회
    # User Data 스크립트 생성 (Docker 설치, 앱 배포)
    # 프라이빗 서브넷에 인스턴스 생성
    return instance_id
```

#### `create_knowledge_base_with_opensearch()`
Bedrock Knowledge Base 생성

```python
def create_knowledge_base_with_opensearch(opensearch_info: Dict[str, str], 
                                          knowledge_base_role_arn: str, 
                                          s3_bucket_name: str) -> str:
    """Create Knowledge Base with correct OpenSearch collection."""
    # 벡터 인덱스 생성
    # Knowledge Base 생성 (Titan Embed v2)
    # S3 데이터 소스 생성
    return knowledge_base_id
```

### 헬퍼 함수

| 함수 | 설명 |
|------|------|
| `attach_inline_policy()` | IAM 역할에 인라인 정책 연결 |
| `create_security_group()` | 보안 그룹 생성 |
| `create_vpc_endpoint()` | VPC 엔드포인트 생성 |
| `create_public_subnets()` | 퍼블릭 서브넷 생성 |
| `create_private_subnets()` | 프라이빗 서브넷 생성 |
| `get_or_create_internet_gateway()` | Internet Gateway 조회/생성 |
| `get_or_create_nat_gateway()` | NAT Gateway 조회/생성 |
| `classify_subnets()` | 서브넷을 퍼블릭/프라이빗으로 분류 |
| `wait_for_subnet_available()` | 서브넷 가용 상태 대기 |
| `wait_for_nat_gateway()` | NAT Gateway 가용 상태 대기 |
| `create_vector_index_in_opensearch()` | OpenSearch에 벡터 인덱스 생성 |
| `check_application_ready()` | 애플리케이션 준비 상태 확인 |

---

## 실행 방법

### 기본 실행 (전체 인프라 배포)

```bash
python installer.py
```

### 기존 EC2 인스턴스에 설정 스크립트 실행

```bash
# 인스턴스 이름으로 자동 탐색
python installer.py --run-setup

# 특정 인스턴스 ID 지정
python installer.py --run-setup i-1234567890abcdef0
```

### EC2 서브넷 배포 검증

```bash
python installer.py --verify-deployment
```

---

## 배포 순서

스크립트는 다음 순서로 리소스를 생성합니다:

```
[1/10] Secrets Manager 시크릿 생성
       ↓
[2/10] S3 버킷 생성
       ↓
[3/10] IAM 역할 생성
       • Knowledge Base 역할
       • Agent 역할
       • EC2 역할
       ↓
[4/10] OpenSearch Serverless 컬렉션 생성
       • 암호화/네트워크/데이터 액세스 정책
       • 컬렉션 생성 및 활성화 대기
       ↓
[5/10] Bedrock Knowledge Base 생성
       • 벡터 인덱스 생성
       • Knowledge Base 생성
       • S3 데이터 소스 연결
       ↓
[6/10] VPC 네트워킹 리소스 생성
       • VPC, 서브넷 생성
       • IGW, NAT Gateway 생성
       • 보안 그룹 생성
       • VPC 엔드포인트 생성
       ↓
[7/10] Application Load Balancer 생성
       ↓
[8/10] CloudFront 배포 생성
       • OAI 생성
       • S3 버킷 정책 업데이트
       • ALB + S3 하이브리드 오리진
       ↓
[9/10] EC2 인스턴스 생성
       • User Data 스크립트로 Docker 앱 배포
       • 프라이빗 서브넷에 배포
       ↓
[10/10] ALB 타겟 그룹 및 리스너 생성
        • EC2 인스턴스 등록
        • HTTP 리스너 생성
        ↓
애플리케이션 준비 상태 확인
        ↓
완료 - config.json 업데이트
```

---

## 배포 완료 후

배포가 완료되면 다음 정보가 출력됩니다:

```
================================================================
Infrastructure Deployment Completed Successfully!
================================================================
Summary:
  S3 Bucket: storage-for-es-us-{account_id}-us-west-2
  VPC ID: vpc-xxxxxxxxx
  Public Subnets: subnet-xxx, subnet-yyy
  Private Subnets: subnet-aaa, subnet-bbb
  ALB DNS: http://alb-for-es-us-xxxxxx.us-west-2.elb.amazonaws.com/
  CloudFront Domain: https://xxxxxxxxx.cloudfront.net
  EC2 Instance ID: i-xxxxxxxxx (deployed in private subnet)
  OpenSearch Endpoint: https://xxxxxxxx.us-west-2.aoss.amazonaws.com
  Knowledge Base ID: XXXXXXXXXX

Total deployment time: XX.XX minutes
================================================================
```

### 주의사항
- CloudFront 배포는 완전히 활성화되기까지 15-20분이 소요될 수 있습니다
- EC2 인스턴스의 User Data 스크립트가 애플리케이션을 설치하고 시작합니다
- `application/config.json` 파일이 자동으로 업데이트됩니다

---

## 에러 처리

스크립트는 다음과 같은 에러를 자동으로 처리합니다:

| 상황 | 처리 방법 |
|------|----------|
| 리소스 이미 존재 | 기존 리소스 재사용 |
| 서브넷 부족 | 자동으로 서브넷 생성 |
| CIDR 충돌 | 대체 CIDR 블록 자동 선택 |
| 정책 이미 존재 | 기존 정책 업데이트 |
| 타임아웃 | 재시도 로직 적용 |

배포 실패 시 상세한 에러 메시지와 스택 트레이스가 출력됩니다.
