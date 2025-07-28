"""
Live-view browser tool with Amazon Nova Act SDK
source: https://github.com/awslabs/amazon-bedrock-agentcore-samples/blob/main/01-tutorials/05-AgentCore-tools/02-Agent-Core-browser-tool/01-browser-with-NovaAct/02_agentcore-browser-tool-live-view-with-nova-act.ipynb
"""

from bedrock_agentcore.tools.browser_client import browser_session
from nova_act import NovaAct
from rich.console import Console
from rich.panel import Panel
import threading
import queue
from interactive_tools.browser_viewer import BrowserViewerServer
import logging
import sys
import json
import boto3
import os

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("rag")

def load_config():
    config = None
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config

config = load_config()

bedrock_region = config['region']
projectName = config['projectName']

console = Console()

starting_page = "https://www.amazon.com"

# api key to get weather information in agent
secretsmanager = boto3.client(
    service_name='secretsmanager',
    region_name=bedrock_region
)

# api key to use nova act
nova_act_key = ""
try:
    get_nova_act_api_secret = secretsmanager.get_secret_value(
        SecretId=f"nova-act-{projectName}"
    )
    #print('get_nova_act_api_secret: ', get_nova_act_api_secret)
    secret_string = get_nova_act_api_secret['SecretString']
    
    # Try to parse as JSON first
    try:
        secret = json.loads(secret_string)
        if "nova_act_api_key" in secret:
            nova_act_key = secret['nova_act_api_key']
        else:
            # If no JSON structure, use the string directly
            nova_act_key = secret_string
    except json.JSONDecodeError:
        # If not JSON, use the string directly
        nova_act_key = secret_string
    
    print('nova_act_api_key loaded successfully')
    print(f'Secret string length: {len(secret_string)}')
    print(f'First 10 chars: {secret_string[:10]}...')

except Exception as e: 
    logger.info(f"nova act credential is required: {e}")
    # raise e
    pass

def _nova_act_worker(prompt, ws_url, headers, result_queue, error_queue):
    """NovaAct worker function"""
    try:
        print(f"NovaAct API key length: {len(nova_act_key) if nova_act_key else 0}")
        print(f"NovaAct API key set: {bool(nova_act_key)}")
        
        with NovaAct(
            cdp_endpoint_url=ws_url,
            cdp_headers=headers,
            preview={"playwright_actuation": True},
            nova_act_api_key=nova_act_key,
            starting_page=starting_page,
        ) as nova_act:
            print(f"Executing NovaAct with prompt: {prompt}")
            
            # Perform the search action
            search_result = nova_act.act(prompt)
            print(f"Search result type: {type(search_result)}")
            print(f"Search result: {search_result}")
            
            # Create a simple result message
            final_result = f"Successfully searched for '{prompt}' on Amazon. The search results are now visible in the browser. You can view the products, prices, and descriptions in the browser window."
            
            result_queue.put(final_result)
    except Exception as e:
        print(f"NovaAct error: {e}")
        error_queue.put(e)

def live_view_with_nova_act(prompt):
    """Run the browser live viewer with display sizing."""
    console.print(
        Panel(
            "[bold cyan]Browser Live Viewer[/bold cyan]\n\n"
            "This demonstrates:\n"
            "• Live browser viewing with DCV\n"
            "• Configurable display sizes (not limited to 900×800)\n"
            "• Proper display layout callbacks\n\n"
            "[yellow]Note: Requires Amazon DCV SDK files[/yellow]",
            title="Browser Live Viewer",
            border_style="blue",
        )
    )

    result = None  # Initialize result variable
    viewer = None
    
    try:
        # Step 1: Create browser session
        with browser_session(bedrock_region) as client:
            ws_url, headers = client.generate_ws_headers()

            # Step 2: Start viewer server
            console.print("\n[cyan]Step 3: Starting viewer server...[/cyan]")
            viewer = BrowserViewerServer(client, port=8000)
            viewer_url = viewer.start(open_browser=True)

            # Step 3: Show features
            console.print("\n[bold green]Viewer Features:[/bold green]")
            console.print(
                "• Default display: 1600×900 (configured via displayLayout callback)"
            )
            console.print("• Size options: 720p, 900p, 1080p, 1440p")
            console.print("• Real-time display updates")
            console.print("• Take/Release control functionality")

            console.print("\n[yellow]Press Ctrl+C to stop[/yellow]")

            # Step 4: Use Nova Act in separate thread to avoid asyncio conflicts
            result_queue = queue.Queue()
            error_queue = queue.Queue()
            
            nova_thread = threading.Thread(
                target=_nova_act_worker,
                args=(prompt, ws_url, headers, result_queue, error_queue)
            )
            nova_thread.start()
            nova_thread.join()  # Wait for completion
            
            # Check for errors first
            if not error_queue.empty():
                error = error_queue.get()
                raise error
            
            # Get result
            if not result_queue.empty():
                result = result_queue.get()
                console.print(f"\n[bold green]Final Result:[/bold green] {result}")
                
                # Ensure result is a string
                if not isinstance(result, str):
                    result = str(result)
    
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        result = f"Browser search failed: {str(e)}"
    finally:
        console.print("\n\n[yellow]Shutting down...[/yellow]")
        
        # Clean up viewer server safely
        if viewer is not None:
            try:
                viewer.stop()
                console.print("✅ Viewer server stopped")
            except Exception as viewer_error:
                console.print(f"⚠️ Error stopping viewer server: {viewer_error}")
    
    # Ensure we always return a string
    if result is None:
        result = "Browser search completed without result"
    elif not isinstance(result, str):
        result = str(result)
    
    return result