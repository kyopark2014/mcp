#!/bin/bash

# Agent Docker Run Script (for ARG-built images)
echo "🚀 Agent Docker Run Script"
echo "=================================="

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

# Check if image exists
if ! sudo docker images | grep -q "${DOCKER_NAME}.*latest"; then
    echo "❌ Docker image '${DOCKER_NAME}:latest' not found."
    echo "   Please build the image first using:"
    echo "   ./build-docker.sh"
    exit 1
fi

# Stop and remove existing container if it exists
echo "🧹 Cleaning up existing container..."
sudo docker stop ${DOCKER_NAME}-container 2>/dev/null || true
sudo docker rm ${DOCKER_NAME}-container 2>/dev/null || true

# Disable OpenTelemetry for local development
echo "🔍 OpenTelemetry disabled for local development"

# Run Docker container
echo ""
echo "🚀 Starting Docker container..."
sudo docker run -d \
    --platform linux/arm64 \
    --name ${DOCKER_NAME}-container \
    -p 8000:8000 \
    -e OTEL_TRACES_SAMPLER=always_off \
    -e OTEL_METRICS_EXPORTER=none \
    -e OTEL_LOGS_EXPORTER=none \
    -e OTEL_RESOURCE_DETECTORS=none \
    ${DOCKER_NAME}:latest
   
if [ $? -eq 0 ]; then
    echo "✅ Container started successfully!"
    echo ""
    echo "🌐 Access your application at: http://localhost:8080"
    echo ""
    echo "📊 Container status:"
    sudo sudo docker ps | grep ${DOCKER_NAME}-container
    echo ""
    echo "📝 To view logs: sudo docker logs ${DOCKER_NAME}-container"
    echo "🛑 To stop: sudo docker stop ${DOCKER_NAME}-container"
    echo "🗑️  To remove: sudo docker rm ${DOCKER_NAME}-container"
    echo ""
    echo "🔍 To test AWS credentials in container:"
    echo "   sudo docker exec -it ${DOCKER_NAME}-container aws sts get-caller-identity"
else
    echo "❌ Failed to start container"
    exit 1
fi 