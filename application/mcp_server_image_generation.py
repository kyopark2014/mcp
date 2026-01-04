import logging
import sys
import mcp_nova_canvas as canvas

from typing import Dict, Optional, Any
from langchain_experimental.tools import PythonAstREPLTool
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field
from typing import TYPE_CHECKING, List, Optional

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("nova-canvas-server")

try:
    mcp = FastMCP(
        name = "nova_canvas",
        instructions=(
            "You are a helpful assistant. "
            "You can geneate images for the user's request."
        )
    )
    logger.info("MCP server initialized successfully")
except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.info(f"{err_msg}")

######################################
# Image Generation
######################################

from nova_canvas.consts import (
    DEFAULT_CFG_SCALE,
    DEFAULT_HEIGHT,
    DEFAULT_NUMBER_OF_IMAGES,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_QUALITY,
    DEFAULT_WIDTH,
    NOVA_CANVAS_MODEL_ID,
)

# @mcp.tool(name='generate_image')
# async def mcp_generate_image(
#     ctx: Context,
#     prompt: str = Field(
#         description='The text description of the image to generate (1-1024 characters)'
#     ),
#     negative_prompt: Optional[str] = Field(
#         default=None,
#         description='Text to define what not to include in the image (1-1024 characters)',
#     ),
#     filename: Optional[str] = Field(
#         default=None,
#         description='The name of the file to save the image to (without extension)',
#     ),
#     width: int = Field(
#         default=DEFAULT_WIDTH,
#         description='The width of the generated image (320-4096, divisible by 16)',
#     ),
#     height: int = Field(
#         default=DEFAULT_HEIGHT,
#         description='The height of the generated image (320-4096, divisible by 16)',
#     ),
#     quality: str = Field(
#         default=DEFAULT_QUALITY,
#         description='The quality of the generated image ("standard" or "premium")',
#     ),
#     cfg_scale: float = Field(
#         default=DEFAULT_CFG_SCALE,
#         description='How strongly the image adheres to the prompt (1.1-10.0)',
#     ),
#     seed: Optional[int] = Field(default=None, description='Seed for generation (0-858,993,459)'),
#     number_of_images: int = Field(
#         default=DEFAULT_NUMBER_OF_IMAGES,
#         description='The number of images to generate (1-5)',
#     )):
#     """Generate an image using Amazon Nova Canvas with text prompt.

#     This tool uses Amazon Nova Canvas to generate images based on a text prompt.
#     The generated image will be saved to a file and the path will be returned.

#     ## Prompt Best Practices

#     An effective prompt often includes short descriptions of:
#     1. The subject
#     2. The environment
#     3. (optional) The position or pose of the subject
#     4. (optional) Lighting description
#     5. (optional) Camera position/framing
#     6. (optional) The visual style or medium ("photo", "illustration", "painting", etc.)

#     Do not use negation words like "no", "not", "without" in your prompt. Instead, use the
#     negative_prompt parameter to specify what you don't want in the image.

#     You should always include "people, anatomy, hands, low quality, low resolution, low detail" in your negative_prompt

#     ## Example Prompts

#     - "realistic editorial photo of female teacher standing at a blackboard with a warm smile"
#     - "whimsical and ethereal soft-shaded story illustration: A woman in a large hat stands at the ship's railing looking out across the ocean"
#     - "drone view of a dark river winding through a stark Iceland landscape, cinematic quality"

#     Returns:
#         McpImageGenerationResponse: A response containing the generated image paths.
#     """

#     logger.info("MCP tool generate_image called")
#     logger.info(f"ctx: {ctx}")
#     logger.info(f"prompt: {prompt}")
#     logger.info(f"negative_prompt: {negative_prompt}")
#     logger.info(f"filename: {filename}")
#     logger.info(f"width: {width}")
#     logger.info(f"height: {height}")
#     logger.info(f"quality: {quality}")
#     logger.info(f"cfg_scale: {cfg_scale}")
#     logger.info(f"seed: {seed}")
#     logger.info(f"number_of_images: {number_of_images}")

#     return await canvas.mcp_generate_image(ctx, prompt, negative_prompt, filename, width, height, quality, cfg_scale, seed, number_of_images)

@mcp.tool(name='generate_image_with_colors')
async def mcp_generate_image_with_colors(
    ctx: Context,
    prompt: str = Field(
        description='The text description of the image to generate (1-1024 characters)'
    ),
    colors: List[str] = Field(
        description='List of up to 10 hexadecimal color values (e.g., "#FF9800")'
    ),
    negative_prompt: Optional[str] = Field(
        default=None,
        description='Text to define what not to include in the image (1-1024 characters)',
    ),
    filename: Optional[str] = Field(
        default=None,
        description='The name of the file to save the image to (without extension)',
    ),
    width: int = Field(
        default=1024,
        description='The width of the generated image (320-4096, divisible by 16)',
    ),
    height: int = Field(
        default=1024,
        description='The height of the generated image (320-4096, divisible by 16)',
    ),
    quality: str = Field(
        default='standard',
        description='The quality of the generated image ("standard" or "premium")',
    ),
    cfg_scale: float = Field(
        default=6.5,
        description='How strongly the image adheres to the prompt (1.1-10.0)',
    ),
    seed: Optional[int] = Field(
         default=None, 
         description='Seed for generation (0-858,993,459)'
    ),
    number_of_images: int = Field(
         default=1, 
         description='The number of images to generate (1-5)'
    )):
    """Generate an image using Amazon Nova Canvas with color guidance.

    This tool uses Amazon Nova Canvas to generate images based on a text prompt and color palette.
    The generated image will be saved to a file and the path will be returned.

    ## Prompt Best Practices

    An effective prompt often includes short descriptions of:
    1. The subject
    2. The environment
    3. (optional) The position or pose of the subject
    4. (optional) Lighting description
    5. (optional) Camera position/framing
    6. (optional) The visual style or medium ("photo", "illustration", "painting", etc.)
    

    Do not use negation words like "no", "not", "without" in your prompt. Instead, use the
    negative_prompt parameter to specify what you don't want in the image.

    ## Example Colors

    - ["#FF5733", "#33FF57", "#3357FF"] - A vibrant color scheme with red, green, and blue
    - ["#000000", "#FFFFFF"] - A high contrast black and white scheme
    - ["#FFD700", "#B87333"] - A gold and bronze color scheme

    Returns:
        McpImageGenerationResponse: A response containing the generated image paths.
    """

    logger.info("MCP tool generate_image with colors called")
    logger.info(f"ctx: {ctx}")
    logger.info(f"prompt: {prompt}")
    logger.info(f"colors: {colors}")
    logger.info(f"negative_prompt: {negative_prompt}")
    logger.info(f"filename: {filename}")
    logger.info(f"width: {width}")
    logger.info(f"height: {height}")
    logger.info(f"quality: {quality}")
    logger.info(f"cfg_scale: {cfg_scale}")
    logger.info(f"seed: {seed}")
    logger.info(f"number_of_images: {number_of_images}")

    return await canvas.mcp_generate_image_with_colors(ctx, prompt, colors, negative_prompt, filename, width, height, quality, cfg_scale, seed, number_of_images)
    
######################################
# AWS Logs
######################################

if __name__ =="__main__":
    mcp.run(transport="stdio")


