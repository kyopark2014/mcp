#!/bin/bash

# Agent Docker Build Script (with ARG credentials)
echo "🚀 Agent Docker Build Script (with ARG credentials)"
echo "=========================================================="

# Get AWS credentials from local AWS CLI configuration
AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id)
AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key)
AWS_DEFAULT_REGION=$(aws configure get region)
AWS_SESSION_TOKEN=$(aws configure get aws_session_token)

echo "   Region: ${AWS_DEFAULT_REGION:-us-west-2}"

if [ -f "config.json" ]; then
    PROJECT_NAME=$(python3 -c "import json; print(json.load(open('config.json'))['projectName'])")

    CURRENT_FOLDER_NAME=$(basename $(pwd))
    echo "CURRENT_FOLDER_NAME: ${CURRENT_FOLDER_NAME}"

    DOCKER_NAME="${PROJECT_NAME}_${CURRENT_FOLDER_NAME}"
    echo "DOCKER_NAME: ${DOCKER_NAME}"
else
    echo "Error: config.json file not found"
    exit 1
fi

# Build Docker image with build arguments
echo ""
echo "🔨 Building Docker image with ARG credentials..."
sudo docker build \
    --platform linux/arm64 \
    --build-arg AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    --build-arg AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    --build-arg AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" \
    --build-arg AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
    -t ${DOCKER_NAME}:latest .

if [ $? -eq 0 ]; then
    echo "✅ Docker image built successfully with embedded credentials"
    echo ""
    echo "🚀 To run the container:"
    echo "   sudo docker run -d --name ${DOCKER_NAME} -p 8080:8080 ${DOCKER_NAME}:latest"
    echo ""
    echo "⚠️  Note: AWS credentials are embedded in the Docker image"
    echo "   - Do not share this image publicly"
    echo "   - For production, use environment variables or IAM roles"
else
    echo "❌ Docker build failed"
    exit 1
fi 