from mcp.server.mcpserver import Context, MCPServer
import logging
import os
import sys
import json
import traceback
from nova_canvas.models import McpImageGenerationResponse
from nova_canvas.novacanvas import (
    generate_image_with_colors,
    generate_image_with_text,
)

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("nova-canvas")

async def mcp_generate_image(ctx, prompt, negative_prompt, filename, width, height, quality, cfg_scale, seed, number_of_images):
    """Generate an image using Amazon Nova Canvas with text prompt."""
    
    logger.debug(
        f"MCP tool generate_image called with prompt: '{prompt[:30]}...', dims: {width}x{height}"
    )

    try:
        logger.info(
            f'Generating image with text prompt, quality: {quality}, cfg_scale: {cfg_scale}'
        )
        response = await generate_image_with_text(
            prompt=prompt,
            negative_prompt=negative_prompt,
            filename=filename,
            width=width,
            height=height,
            quality=quality,
            cfg_scale=cfg_scale,
            seed=seed,
            number_of_images=number_of_images
        )

        logger.info(f'response of mcp_generate_image: {response}')

        if response.status == 'success':
            return {
                "path": [f'{path}' for path in response.paths]
            } 
        else:
            logger.error(f'Image generation returned error status: {response.message}')
            await ctx.error(f'Failed to generate image: {response.message}')  # type: ignore
            # Return empty image or raise exception based on requirements
            raise Exception(f'Failed to generate image: {response.message}')
    except Exception as e:
        logger.error(f'Error in mcp_generate_image: {str(e)}')
        await ctx.error(f'Error generating image: {str(e)}')  # type: ignore
        raise


async def mcp_generate_image_with_colors(ctx, prompt, colors, negative_prompt, filename, width, height, quality, cfg_scale, seed, number_of_images) -> McpImageGenerationResponse:
    """Generate an image using Amazon Nova Canvas with color guidance. """

    logger.debug(
        f"MCP tool generate_image_with_colors called with prompt: '{prompt[:30]}...', {len(colors)} colors"
    )
    
    try:
        color_hex_list = ', '.join(colors[:3]) + (', ...' if len(colors) > 3 else '')
        logger.info(
            f'Generating color-guided image with colors: [{color_hex_list}], quality: {quality}'
        )

        response = await generate_image_with_colors(
            prompt=prompt,
            colors=colors,
            negative_prompt=negative_prompt,
            filename=filename,
            width=width,
            height=height,
            quality=quality,
            cfg_scale=cfg_scale,
            seed=seed,
            number_of_images=number_of_images
        )

        if response.status == 'success':
            return {"path": [f'{path}' for path in response.paths]} 
        else:
            logger.error(f'Color-guided image generation returned error status: {response.message}')
            return {"path": []}
            
    except Exception as e:
        logger.error(f'Error in mcp_generate_image_with_colors: {str(e)}')
        return {"path": []}