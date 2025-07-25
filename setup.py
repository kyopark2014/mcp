from setuptools import setup, find_packages

# 의존성 충돌을 해결하기 위해 직접 의존성 목록을 정의합니다
requirements = [
    "streamlit==1.41.0",
    "streamlit-chat",
    "pandas",
    "numpy",
    "boto3",
    "langchain_aws",
    "langchain",
    "langchain_community",
    "langgraph",
    "langchain_experimental",
    "langgraph-supervisor",
    "langgraph-swarm",
    "tavily-python==0.5.0",
    "yfinance==0.2.52",
    "rizaio==0.8.0",
    "pytz>=2025.2",
    "beautifulsoup4==4.12.3",
    "plotly_express==0.4.1",
    "matplotlib==3.10.0",
    "PyPDF2==3.0.1",
    "opensearch-py",
    "mcp",
    "langchain-mcp-adapters>=0.1.9",
    "wikipedia",
    "aioboto3",
    "requests",
    "uv",
    "kaleido",
    "diagrams",
    "graphviz",
    "sarif-om==1.0.4",
    "arxiv==2.2.0",
    "chembl-webresource-client==0.10.9",
    "pytrials==1.0.0",
    "strands-agents>=1.0.1",
    # strands-agents-tools 버전 제약 완화
    "strands-agents-tools",
    "reportlab",
    "arize-phoenix",
    "colorama",
    # rich 버전 명시 (streamlit과 호환되는 버전)
    "rich==13.9.0",
]

setup(
    name="mcp-app",
    version="0.1.0",
    author="AWS",
    author_email="example@example.com",
    description="MCP Application for RAG and other AI capabilities",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/mcp",
    packages=["application"],
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "mcp-app=application.app:main",
        ],
    },
)
