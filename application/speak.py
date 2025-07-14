import os
import subprocess
from typing import Any
import logging
import sys
import boto3

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from strands.types.tools import ToolResult, ToolUse
from strands import tool
from strands_tools.utils import console_util

logging.basicConfig(
    level=logging.INFO,  
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("strands-agent")


TOOL_SPEC = {
    "name": "speak",
    "description": (
        "Generate speech from text using either say command (fast mode) on macOS, or Amazon Polly (high "
        "quality mode) on other operating systems. Set play_audio to false to only generate the audio file "
        "instead of also playing."
    ),
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to convert to speech",
                },
                "mode": {
                    "type": "string",
                    "description": "Speech mode - 'fast' for macOS say command or 'polly' for AWS Polly",
                    "enum": ["fast", "polly"],
                    "default": "fast",
                },
                "voice_id": {
                    "type": "string",
                    "description": "The Polly voice ID to use (e.g., Joanna, Matthew) - only used in polly mode",
                    "default": "Joanna",
                },
                "output_path": {
                    "type": "string",
                    "description": "Path where to save the audio file (only for polly mode)",
                    "default": "speech_output.mp3",
                },
                "play_audio": {
                    "type": "boolean",
                    "description": "Whether to play the audio through speakers after generation",
                    "default": True,
                },
            },
            "required": ["text"],
        }
    },
}


def create_status_table(
    mode: str,
    text: str,
    voice_id: str = None,
    output_path: str = None,
    play_audio: bool = True,
) -> Table:
    """Create a rich table showing speech parameters."""
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Parameter", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Mode", mode)
    table.add_row("Text", text[:50] + "..." if len(text) > 50 else text)
    table.add_row("Play Audio", str(play_audio))
    if mode == "polly":
        table.add_row("Voice ID", voice_id)
        table.add_row("Output Path", output_path)

    return table

def display_speech_status(console: Console, status: str, message: str, style: str):
    """Display a status message in a styled panel."""
    console.print(
        Panel(
            f"[{style}]{message}[/{style}]",
            title=f"[bold {style}]{status}[/bold {style}]",
            border_style=style,
        )
    )

@tool
def speak(tool: ToolUse, **kwargs: Any) -> ToolResult:
    speak_default_style = os.getenv("SPEAK_DEFAULT_STYLE", "green")
    speak_default_mode = os.getenv("SPEAK_DEFAULT_MODE", "polly")  # fast
    speak_default_voice_id = os.getenv("SPEAK_DEFAULT_VOICE_ID", "Jihye")
    speak_default_output_path = os.getenv("SPEAK_DEFAULT_OUTPUT_PATH", "speech_output.mp3")
    speak_default_play_audio = os.getenv("SPEAK_DEFAULT_PLAY_AUDIO", "True").lower() == "true"
    console = console_util.create()

    tool_use_id = tool["toolUseId"]
    tool_input = tool["input"]

    logger.info(f"tool_input = {tool_input}")
    logger.info(f"tool_input type = {type(tool_input)}")

    try:
        if isinstance(tool_input, str):
            text = tool_input
            logger.info(f"DEBUG: Using direct string, text = {text}")
        elif isinstance(tool_input, dict):
            if "tool" in tool_input and "input" in tool_input["tool"]:
                text = tool_input["tool"]["input"]
                logger.info(f"DEBUG: Using nested structure, text = {text}")
            elif "text" in tool_input:
                text = tool_input["text"]
                logger.info(f"DEBUG: Using direct structure, text = {text}")
            else:   
                text = str(tool_input.get("input", tool_input.get("text", "")))
                logger.info(f"DEBUG: Using fallback, text = {text}")
        else:
            text = str(tool_input)
            logger.info(f"DEBUG: Using string conversion, text = {text}")
    except Exception as e:
        logger.info(f"DEBUG: Error extracting text: {e}")
        text = str(tool_input)  
    
    # For string input, use default values for other parameters
    if isinstance(tool_input, str):
        mode = speak_default_mode
        play_audio = speak_default_play_audio
    else:
        mode = tool_input.get("mode", speak_default_mode)
        play_audio = tool_input.get("play_audio", speak_default_play_audio)

    try:
        if mode == "fast":
            # Display status table
            console.print(create_status_table(mode, text, play_audio=play_audio))

            # Show progress while speaking
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                if play_audio:
                    progress.add_task("Speaking...", total=None)
                    # Use macOS say command
                    subprocess.run(["say", text], check=True)
                    result_message = "🗣️ Text spoken using macOS say command"
                else:
                    progress.add_task("Processing...", total=None)
                    # Just process the text without playing
                    result_message = "🗣️ Text processed using macOS say command (audio not played)"

            display_speech_status(console, "Success", result_message, speak_default_style)
            return {
                "toolUseId": tool_use_id,
                "status": "success",
                "content": [{"text": result_message}],
            }
        else:  # polly mode
            if isinstance(tool_input, dict):
                voice_id = tool_input.get("voice_id", speak_default_voice_id)
                output_path = tool_input.get("output_path", speak_default_output_path)
            else:
                voice_id = speak_default_voice_id
                output_path = speak_default_output_path
                
            output_path = os.path.expanduser(output_path)

            # Display status table
            console.print(create_status_table(mode, text, voice_id, output_path, play_audio))

            # Create Polly client
            polly_client = boto3.client("polly", region_name="us-west-2")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                # Add synthesis task
                synthesis_task = progress.add_task("Synthesizing speech...", total=None)

                # Synthesize speech
                response = polly_client.synthesize_speech(
                    Engine="neural", OutputFormat="mp3", Text=text, VoiceId=voice_id
                )

                # Save the audio stream
                if "AudioStream" in response:
                    progress.update(synthesis_task, description="Saving audio file...")
                    with open(output_path, "wb") as file:
                        file.write(response["AudioStream"].read())

                    # Play the generated audio if play_audio is True
                    if play_audio:
                        progress.update(synthesis_task, description="Playing audio...")
                        subprocess.run(["afplay", output_path], check=True)
                        result_message = f"✨ Generated and played speech using Polly (saved to {output_path})"
                    else:
                        result_message = f"✨ Generated speech using Polly (saved to {output_path}, audio not played)"

                    display_speech_status(console, "Success", result_message, speak_default_style)
                    return {
                        "toolUseId": tool_use_id,
                        "status": "success",
                        "content": [{"text": result_message}],
                    }
                else:
                    display_speech_status(console, "Error", "❌ No AudioStream in response from Polly", "red")
                    return {
                        "toolUseId": tool_use_id,
                        "status": "error",
                        "content": [{"text": "❌ No AudioStream in response from Polly"}],
                    }

    except Exception as e:
        error_message = f"❌ Error generating speech: {str(e)}"
        logger.info(f"DEBUG: Exception in speak function: {e}")
        import traceback
        logger.info(f"DEBUG: Traceback: {traceback.format_exc()}")
        display_speech_status(console, "Error", error_message, "red")
        return {
            "toolUseId": tool_use_id,
            "status": "error",
            "content": [{"text": error_message}],
        }