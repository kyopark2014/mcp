import chat
import logging
import sys
import utils
import os

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-config")

config = utils.load_config()
print(f"config: {config}")

aws_region = config["region"] if "region" in config else "us-west-2"
projectName = config["projectName"] if "projectName" in config else "mcp"
workingDir = os.path.dirname(os.path.abspath(__file__))
logger.info(f"workingDir: {workingDir}")

mcp_user_config = {}    
def load_config(mcp_type):
    if mcp_type == "image generation":
        mcp_type = 'image_generation'
    elif mcp_type == "aws diagram":
        mcp_type = 'aws_diagram'
    elif mcp_type == "aws document":
        mcp_type = 'aws_documentation'
    elif mcp_type == "aws cost":
        mcp_type = 'aws_cost'
    elif mcp_type == "ArXiv":
        mcp_type = 'arxiv'
    elif mcp_type == "aws cloudwatch":
        mcp_type = 'aws_cloudwatch'
    elif mcp_type == "aws storage":
        mcp_type = 'aws_storage'
    elif mcp_type == "knowledge base":
        mcp_type = 'knowledge_base_lambda'
    elif mcp_type == "repl coder":
        mcp_type = 'repl_coder'
    elif mcp_type == "agentcore coder":
        mcp_type = 'agentcore_coder'
    elif mcp_type == "aws cli":
        mcp_type = 'aws_cli'
    elif mcp_type == "text editor":
        mcp_type = 'text_editor'
    elif mcp_type == "aws-api":
        mcp_type = 'aws-api-mcp-server'
    elif mcp_type == "aws-knowledge":
        mcp_type = 'aws-knowledge-mcp-server'

    if mcp_type == "basic":
        return {
            "mcpServers": {
                "search": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_basic.py"
                    ]
                }
            }
        }
    elif mcp_type == "image_generation":
        return {
            "mcpServers": {
                "imageGeneration": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_image_generation.py"
                    ]
                }
            }
        }    
    elif mcp_type == "airbnb":
        return {
            "mcpServers": {
                "airbnb": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "@openbnb/mcp-server-airbnb",
                        "--ignore-robots-txt"
                    ]
                }
            }
        }
    elif mcp_type == "playwright":
        return {
            "mcpServers": {
                "playwright": {
                    "command": "npx",
                    "args": [
                        "@playwright/mcp@latest"
                    ]
                }
            }
        }
    elif mcp_type == "obsidian":
        return {
            "mcpServers": {
                "mcp-obsidian": {
                "command": "npx",
                "args": [
                    "-y",
                    "@smithery/cli@latest",
                    "run",
                    "mcp-obsidian",
                    "--config",
                    "{\"vaultPath\":\"/\"}"
                ]
                }
            }
        }
    elif mcp_type == "aws_diagram":
        return {
            "mcpServers": {
                "awslabs.aws-diagram-mcp-server": {
                    "command": "uvx",
                    "args": ["awslabs.aws-diagram-mcp-server"],
                    "env": {
                        "FASTMCP_LOG_LEVEL": "ERROR"
                    },
                }
            }
        }
    
    elif mcp_type == "aws_documentation":
        return {
            "mcpServers": {
                "awslabs.aws-documentation-mcp-server": {
                    "command": "uvx",
                    "args": ["awslabs.aws-documentation-mcp-server@latest"],
                    "env": {
                        "FASTMCP_LOG_LEVEL": "ERROR"
                    }
                }
            }
        }
    
    elif mcp_type == "aws_cost":
        return {
            "mcpServers": {
                "aws_cost": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_aws_cost.py"
                    ]
                }
            }
        }    
    elif mcp_type == "aws_cloudwatch":
        return {
            "mcpServers": {
                "aws_cloudwatch_log": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_aws_log.py"
                    ],
                    "env": {
                        "AWS_REGION": aws_region,
                        "FASTMCP_LOG_LEVEL": "ERROR"
                    }
                }
            }
        }  
    
    elif mcp_type == "aws_storage":
        return {
            "mcpServers": {
                "aws_storage": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_aws_storage.py"
                    ]
                }
            }
        }    
        
    elif mcp_type == "arxiv":
        return {
            "mcpServers": {
                "arxiv-mcp-server": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "@smithery/cli@latest",
                        "run",
                        "arxiv-mcp-server",
                        "--config",
                        "{\"storagePath\":\"/Users/ksdyb/Downloads/ArXiv\"}"
                    ]
                }
            }
        }
    
    elif mcp_type == "firecrawl":
        return {
            "mcpServers": {
                "firecrawl-mcp": {
                    "command": "npx",
                    "args": ["-y", "firecrawl-mcp"],
                    "env": {
                        "FIRECRAWL_API_KEY": utils.firecrawl_key
                    }
                }
            }
        }
        
    elif mcp_type == "knowledge_base_lambda":
        return {
            "mcpServers": {
                "knowledge_base_lambda": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_lambda_knowledge_base.py"
                    ]
                }
            }
        }    
    
    elif mcp_type == "repl_coder":
        return {
            "mcpServers": {
                "repl_coder": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_repl_coder.py"
                    ]
                }
            }
        }    
    elif mcp_type == "agentcore_coder":
        return {
            "mcpServers": {
                "agentcore_coder": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_agentcore_coder.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "aws_cli":
        return {
            "mcpServers": {
                "aw-cli": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_aws_cli.py"
                    ]
                }
            }
        }    
    
    elif mcp_type == "tavily":
        return {
            "mcpServers": {
                "tavily-mcp": {
                    "command": "npx",
                    "args": ["-y", "tavily-mcp@0.1.4"],
                    "env": {
                        "TAVILY_API_KEY": utils.tavily_key
                    },
                }
            }
        }
    elif mcp_type == "wikipedia":
        return {
            "mcpServers": {
                "wikipedia": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_wikipedia.py"
                    ]
                }
            }
        }      
    elif mcp_type == "terminal":
        return {
            "mcpServers": {
                "iterm-mcp": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "iterm-mcp"
                    ]
                }
            }
        }
    
    elif mcp_type == "filesystem":
        return {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": [
                        "@modelcontextprotocol/server-filesystem",
                        "~/"
                    ]
                }
            }
        }
    
    elif mcp_type == "puppeteer":
        return {
            "mcpServers": {
                "puppeteer": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-puppeteer"]
                }
            }
        }
    
    elif mcp_type == "perplexity":
        return {
            "mcpServers": {
                "perplexity-mcp": {                    
                    "command": "uvx",
                    "args": [
                        "perplexity-mcp"
                    ],
                    "env": {
                        "PERPLEXITY_API_KEY": utils.perplexity_key,
                        "PERPLEXITY_MODEL": "sonar"
                    }
                }
            }
        }

    elif mcp_type == "text_editor":
        return {
            "mcpServers": {
                "textEditor": {
                    "command": "npx",
                    "args": ["-y", "mcp-server-text-editor"]
                }
            }
        }
    
    elif mcp_type == "context7":
        return {
            "mcpServers": {
                "context7": {
                    "command": "npx",
                    "args": ["-y", "@upstash/context7-mcp@latest"]
                }
            }
        }
    
    elif mcp_type == "pubmed":
        return {
            "mcpServers": {
                "pubmed": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_pubmed.py"  
                    ]
                }
            }
        }
    
    elif mcp_type == "chembl":
        return {
            "mcpServers": {
                "chembl": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_chembl.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "clinicaltrial":
        return {
            "mcpServers": {
                "clinicaltrial": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_clinicaltrial.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "arxiv-manual":
        return {
            "mcpServers": {
                "arxiv-manager": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_arxiv.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "tavily-search":
        return {
            "mcpServers": {
                "tavily-manager": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_tavily.py"
                    ]
                }
            }
        }
    elif mcp_type == "use_aws":
        return {
            "mcpServers": {
                "use_aws": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_use_aws.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "use_aws":
        return {
            "mcpServers": {
                "use_aws": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_use_aws.py"
                    ],
                    "env": {
                        "AWS_REGION": aws_region,
                        "FASTMCP_LOG_LEVEL": "ERROR"
                    }
                }
            }
        }
    
    elif mcp_type == "aws_knowledge_base":  # AWS Labs cloudwatch-logs MCP Server
        return {
            "mcpServers": {
                "aws_knowledge_base": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_kb.py"
                    ],
                    "env": {
                        "KB_INCLUSION_TAG_KEY": projectName
                    }
                }
            }
        }
    
    elif mcp_type == "aws-api-mcp-server": 
        return {
            "mcpServers": {
                "awslabs.aws-api-mcp-server": {
                    "command": "uvx",
                    "args": [
                        "awslabs.aws-api-mcp-server@latest"
                    ],
                    "env": {
                        "AWS_REGION": aws_region,
                        "AWS_API_MCP_WORKING_DIR": workingDir
                    }
                }
            }
        }
    
    elif mcp_type == "aws-knowledge-mcp-server":
        return {
            "mcpServers": {
                "aws-knowledge-mcp-server": {
                    "command": "npx",
                    "args": [
                        "mcp-remote",
                        "https://knowledge-mcp.global.api.aws"
                    ]
                }
            }
        }
    elif mcp_type == "agentcore-browser":
        return {
            "mcpServers": {
                "agentcore-browser": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_browser.py"
                    ]
                }
            }
        }
    
    elif mcp_type == "long-term memory":
        return {
            "mcpServers": {
                "long-term memory": {
                    "command": "python",
                    "args": [f"{workingDir}/mcp_server_long_term_memory.py"]
                }
            }
        }
    
    elif mcp_type == "short-term memory":
        return {
            "mcpServers": {
                "short-term memory": {
                    "command": "python",
                    "args": [f"{workingDir}/mcp_server_short_term_memory.py"]
                }
            }
        }
    
    elif mcp_type == "사용자 설정":
        return mcp_user_config

def load_selected_config(mcp_servers: dict):
    logger.info(f"mcp_servers: {mcp_servers}")
    
    loaded_config = {}
    for server in mcp_servers:
        config = load_config(server)        
        if config:
            loaded_config.update(config["mcpServers"])
    return {
        "mcpServers": loaded_config
    }
