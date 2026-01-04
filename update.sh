#!/bin/bash

# Update script: git pull, rebuild and run Docker
echo "🔄 Update Script"
echo "=================================="

# Step 1: Git pull
echo ""
echo "📥 Pulling latest changes from git..."
git pull

if [ $? -ne 0 ]; then
    echo "❌ Git pull failed"
    exit 1
fi

echo "✅ Git pull completed successfully"

# Step 2: Build Docker image
echo ""
echo "🔨 Building Docker image..."
./build-docker-with-args.sh

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed"
    exit 1
fi

# Step 3: Run Docker container
echo ""
echo "🚀 Running Docker container..."
./run-docker.sh

if [ $? -ne 0 ]; then
    echo "❌ Docker run failed"
    exit 1
fi

echo ""
echo "✅ Update completed successfully!"
echo "🌐 Access your application at: http://localhost:8501"

