#!/bin/bash

# Update script: git pull, rebuild and run Docker
echo "Update Script"
echo "=================================="

# Step 1: Git pull
echo ""
echo "Pulling latest changes from git..."

# Stash config.json changes if it exists and has local modifications
if [ -f config.json ] && ! git diff --quiet config.json 2>/dev/null; then
    echo "Stashing local config.json changes..."
    git stash push -m "Auto-stash config.json before update" config.json
    CONFIG_STASHED=true
else
    CONFIG_STASHED=false
fi

git pull

if [ $? -ne 0 ]; then
    echo "ERROR: Git pull failed"
    # Restore stashed config.json if pull failed
    if [ "$CONFIG_STASHED" = true ]; then
        echo "Restoring stashed config.json..."
        git stash pop 2>/dev/null || true
    fi
    exit 1
fi

# Restore stashed config.json after successful pull
if [ "$CONFIG_STASHED" = true ]; then
    echo "Restoring stashed config.json..."
    git stash pop 2>/dev/null || true
fi

echo "Git pull completed successfully"

# Step 2: Build Docker image
echo ""
echo "Building Docker image..."

echo "Region: ${AWS_DEFAULT_REGION:-us-west-2}"

# Build Docker image with build arguments
sudo docker build \
    --platform linux/amd64 \
    -t agent:latest .

if [ $? -ne 0 ]; then
    echo "ERROR: Docker build failed"
    exit 1
fi

echo "Docker image built successfully"

# Step 3: Run Docker container
echo ""
echo "Starting Docker container..."

# Stop all running containers
echo "Stopping all running Docker containers..."
sudo docker stop $(sudo docker ps -q) 2>/dev/null || true

# Remove all containers
echo "Removing all Docker containers..."
sudo docker rm $(sudo docker ps -aq) 2>/dev/null || true

# Run Docker container
sudo docker run -d \
    --platform linux/amd64 \
    --name agent-container \
    -p 8501:8501 \
    agent:latest

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to start container"
    exit 1
fi

echo "Container started successfully"
echo ""
echo "Container status:"
sudo docker ps | grep agent-container
echo ""
echo "To view logs: sudo docker logs agent-container"
echo "To stop: sudo docker stop agent-container"
echo "To remove: sudo docker rm agent-container"

echo ""
echo "Update completed successfully!"

