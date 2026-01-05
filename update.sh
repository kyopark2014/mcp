#!/bin/bash

# Update script: git pull, rebuild and run Docker
echo "🔄 Update Script"
echo "=================================="

# Step 1: Git pull
echo ""
echo "📥 Pulling latest changes from git..."

# Stash config.json changes if it exists and has local modifications
if [ -f config.json ] && ! git diff --quiet config.json 2>/dev/null; then
    echo "💾 Stashing local config.json changes..."
    git stash push -m "Auto-stash config.json before update" config.json
    CONFIG_STASHED=true
else
    CONFIG_STASHED=false
fi

git pull

if [ $? -ne 0 ]; then
    echo "❌ Git pull failed"
    # Restore stashed config.json if pull failed
    if [ "$CONFIG_STASHED" = true ]; then
        echo "🔄 Restoring stashed config.json..."
        git stash pop 2>/dev/null || true
    fi
    exit 1
fi

# Restore stashed config.json after successful pull
if [ "$CONFIG_STASHED" = true ]; then
    echo "🔄 Restoring stashed config.json..."
    git stash pop 2>/dev/null || true
fi

echo "✅ Git pull completed successfully"

# Step 2: Stop and remove all running Docker containers
echo ""
echo "🛑 Stopping all running Docker containers..."
sudo docker stop $(sudo docker ps -q) 2>/dev/null || true

echo "🧹 Removing stopped containers..."
sudo docker rm $(sudo docker ps -aq) 2>/dev/null || true

echo "✅ Docker cleanup completed"

# Step 3: Build Docker image
echo ""
echo "🔨 Building Docker image..."
#./build-docker-with-args.sh
./build-docker.sh

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed"
    exit 1
fi

# Step 4: Run Docker container
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

