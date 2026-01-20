FROM --platform=linux/amd64 python:3.13-slim

WORKDIR /app

# Install npm 
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g npm@latest 

# Install Playwright
RUN npm install -g @playwright/mcp@0.0.27

# Install Chrome and Playwright dependencies
RUN apt-get update && apt-get install -y \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome
RUN wget -q -O /tmp/google-chrome-key.pub https://dl-ssl.google.com/linux/linux_signing_key.pub \
    && gpg --dearmor < /tmp/google-chrome-key.pub > /etc/apt/trusted.gpg.d/google-chrome.gpg \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/* /tmp/google-chrome-key.pub

# Install MCP packages globally
RUN npm install -g @modelcontextprotocol/server-filesystem

# Install terminal-control-mcp (Python-based terminal MCP server)
RUN apt-get update && apt-get install -y tmux && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip install terminal-control-mcp

# Install Python packages
RUN pip install streamlit streamlit-chat
RUN pip install pandas numpy
RUN pip install boto3 langchain_aws langchain langchain_community langgraph langchain_experimental langgraph-supervisor langgraph-swarm langchain-text-splitters
RUN pip install mcp langchain-mcp-adapters
RUN pip install tavily-python==0.5.0 pytz>=2025.2
RUN pip install beautifulsoup4==4.12.3 plotly_express==0.4.1 matplotlib==3.10.0 PyPDF2==3.0.1
RUN pip install opensearch-py wikipedia aioboto3 requests
RUN pip install uv kaleido diagrams graphviz
RUN pip install sarif-om==1.0.4 arxiv==2.2.0 chembl-webresource-client==0.10.9 pytrials==1.0.0
RUN pip install strands-agents strands-agents-tools reportlab arize-phoenix colorama
RUN pip install rich==13.9.0 bedrock-agentcore claude-agent-sdk nest-asyncio finance-datareader
RUN pip install nova-act

RUN mkdir -p /root/.streamlit
COPY config.toml /root/.streamlit/

COPY . .

EXPOSE 8501

RUN npm install -g playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN npx playwright install --with-deps chromium && npx playwright install --force chrome

# Set environment variables for Playwright
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/google-chrome
ENV PLAYWRIGHT_CHROMIUM_ARGS="--no-sandbox --disable-dev-shm-usage --disable-gpu --disable-software-rasterizer --disable-setuid-sandbox --no-zygote --single-process"
ENV PLAYWRIGHT_LAUNCH_OPTIONS='{"args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-software-rasterizer", "--disable-setuid-sandbox", "--no-zygote", "--single-process"]}'

# Create necessary directories with proper permissions
RUN mkdir -p /ms-playwright && chmod -R 777 /ms-playwright
RUN mkdir -p /tmp/playwright && chmod -R 777 /tmp/playwright

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

ENTRYPOINT ["python", "-m", "streamlit", "run", "application/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
