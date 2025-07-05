FROM python:3.13-slim

RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    unzip \
    build-essential \
    gcc \
    python3-dev \
    graphviz \
    graphviz-dev \
    pkg-config \
    terminator \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install npm and Playwright
RUN npm install -g npm@latest 
RUN npm install -g @playwright/mcp@0.0.27

# Install AWS CLI
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
    && unzip awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip
 
WORKDIR /app

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
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

RUN pip install streamlit==1.41.0 streamlit-chat pandas numpy boto3
RUN pip install langchain_aws langchain langchain_community langgraph langchain_experimental
RUN pip install langgraph-supervisor langgraph-swarm
RUN pip install tavily-python==0.5.0 yfinance==0.2.52 rizaio==0.8.0 pytz==2024.2 beautifulsoup4==4.12.3
RUN pip install plotly_express==0.4.1 matplotlib==3.10.0
RUN pip install PyPDF2==3.0.1 opensearch-py
RUN pip install mcp langchain-mcp-adapters==0.0.9 wikipedia
RUN pip install aioboto3 requests uv kaleido diagrams reportlab
RUN pip install graphviz sarif-om==1.0.4

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
