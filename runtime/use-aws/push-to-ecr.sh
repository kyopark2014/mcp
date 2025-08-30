#!/bin/bash
set -e

# Use current time as tag
TIMESTAMP=$(date +%Y%m%d%H%M%S)

# Read accountId, region, and projectName from config.json
if [ -f "config.json" ]; then
    AWS_ACCOUNT_ID=$(python3 -c "import json; print(json.load(open('config.json'))['accountId'])")
    AWS_REGION=$(python3 -c "import json; print(json.load(open('config.json'))['region'])")
    ECR_REPOSITORY=$(python3 -c "import json; print(json.load(open('config.json'))['projectName'])")

    CURRENT_FOLDER_NAME=$(basename $(pwd))
    echo "CURRENT_FOLDER_NAME: ${CURRENT_FOLDER_NAME}"

    ECR_REPOSITORY="${ECR_REPOSITORY}_${CURRENT_FOLDER_NAME}"
    echo "ECR_REPOSITORY: ${ECR_REPOSITORY}"
else
    echo "Error: config.json file not found"
    exit 1
fi

IMAGE_TAG="${TIMESTAMP}"
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:${IMAGE_TAG}"

echo "===== Checking AWS Configuration ====="
echo "AWS Account ID: ${AWS_ACCOUNT_ID}"
echo "AWS Region: ${AWS_REGION}"
echo "ECR Repository: ${ECR_REPOSITORY}"
echo "ECR URI: ${ECR_URI}"

# Check if AWS CLI is configured
if ! command -v aws &> /dev/null; then
    echo "Error: AWS CLI is not installed"
    exit 1
fi

# Check AWS credentials
echo "===== Checking AWS Credentials ====="
if ! aws sts get-caller-identity &> /dev/null; then
    echo "Error: AWS credentials are not configured properly"
    exit 1
fi

# Check if repository exists
echo "===== Checking ECR Repository ====="
if ! aws ecr describe-repositories --region ${AWS_REGION} --repository-names ${ECR_REPOSITORY} &> /dev/null; then
    echo "Repository ${ECR_REPOSITORY} does not exist. Creating it..."
    aws ecr create-repository --repository-name ${ECR_REPOSITORY} --region ${AWS_REGION}
else
    echo "Repository ${ECR_REPOSITORY} exists."
fi

echo "===== AWS ECR Login ====="
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

echo "===== Building Docker Image ====="
docker build --platform linux/arm64 -t ${ECR_REPOSITORY}:${IMAGE_TAG} .

echo "===== Tagging for ECR Repository ====="
docker tag ${ECR_REPOSITORY}:${IMAGE_TAG} ${ECR_URI}

echo "===== Pushing Image to ECR Repository ====="
docker push ${ECR_URI}

echo "===== Complete ====="
echo "Image has been successfully built and pushed to ECR."
echo "Image URI: ${ECR_URI}"

echo "===== Deploying the Image to AgentCore ====="