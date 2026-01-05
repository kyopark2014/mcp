#!/bin/bash

# Agent Docker Build Script (with ARG credentials)
echo "🚀 Agent Docker Build Script (with ARG credentials)"
echo "=========================================================="

echo "   Region: ${AWS_DEFAULT_REGION:-us-west-2}"

# Build Docker image with build arguments
echo ""
echo "🔨 Building Docker image with ARG credentials..."
sudo docker build \
    --platform linux/amd64 \
    -t agent:latest .

if [ $? -eq 0 ]; then
    echo "✅ Docker image built successfully"
else
    echo "❌ Docker build failed"
    exit 1
fi 