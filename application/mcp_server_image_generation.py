import base64
import json
import logging
import os
import random
import sys
from typing import Optional

import boto3
from botocore.config import Config
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

logging.basicConfig(
    level=logging.INFO,
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("sd35l-server")

MODEL_ID = "stability.sd3-5-large-v1:0"
AWS_REGION = "us-west-2"

VALID_ASPECT_RATIOS = [
    "1:1", "16:9", "9:16", "4:3", "3:4",
    "2:3", "3:2", "21:9", "9:21"
]

try:
    if aws_profile := os.environ.get('AWS_PROFILE'):
        bedrock_client = boto3.Session(
            profile_name=aws_profile, region_name=AWS_REGION
        ).client('bedrock-runtime', config=Config(read_timeout=120, retries={"max_attempts": 2}))
    else:
        bedrock_client = boto3.Session(region_name=AWS_REGION).client(
            'bedrock-runtime', config=Config(read_timeout=120, retries={"max_attempts": 2})
        )
except Exception as e:
    logger.error(f'Failed to create bedrock client: {e}')
    raise


def _upload_to_s3(image_bytes: bytes, filename: str) -> Optional[str]:
    """Upload image bytes to S3 via chat.upload_to_s3 if available."""
    try:
        import chat
        url = chat.upload_to_s3(image_bytes, filename)
        if url:
            logger.info(f"Uploaded to S3: {url}")
            return url
    except ImportError:
        logger.warning("chat module not available, skipping S3 upload")
    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
    return None


def _invoke_sd35(request_body: dict) -> dict:
    response = bedrock_client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(request_body),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())


def _save_and_upload(result: dict, prefix: str = "sd35l") -> dict:
    """Process API result: check filtering, save/upload images, return structured response."""
    finish_reasons = result.get("finish_reasons", [])
    if finish_reasons and finish_reasons[0] == "CONTENT_FILTERED":
        return {
            "status": "error",
            "error": "Content was filtered by the safety system. Please revise your prompt.",
            "path": [],
        }

    images = result.get("images", [])
    seeds = result.get("seeds", [])
    if not images:
        return {
            "status": "error",
            "error": "No images returned from the model.",
            "path": [],
        }

    paths = []
    for i, img_b64 in enumerate(images):
        image_bytes = base64.b64decode(img_b64)
        rand_id = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))
        filename = f"{prefix}_{rand_id}.png"

        url = _upload_to_s3(image_bytes, filename)
        if url:
            paths.append(url)
        else:
            local_dir = "/tmp/sd35l_output"
            os.makedirs(local_dir, exist_ok=True)
            local_path = os.path.join(local_dir, filename)
            with open(local_path, "wb") as f:
                f.write(image_bytes)
            paths.append(local_path)
            logger.info(f"Saved locally: {local_path}")

    return {
        "status": "success",
        "path": paths,
        "seed": seeds[0] if seeds else None,
    }


try:
    mcp = FastMCP(
        name="image_generation",
        instructions=(
            "You are a helpful assistant that generates images using Stable Diffusion 3.5 Large. "
            "You support text-to-image and image-to-image generation."
        )
    )
    logger.info("MCP server initialized successfully")
except Exception as e:
    logger.error(f"MCP server init failed: {e}")
    raise


@mcp.tool(name='generate_image')
async def generate_image(
    ctx: Context,
    prompt: str = Field(
        description='Text description of the image to generate. Use descriptive English captions with details about subject, environment, lighting, camera angle, and style.'
    ),
    negative_prompt: Optional[str] = Field(
        default=None,
        description='Elements to exclude from the image (e.g., "blurry, low quality, distorted, bad anatomy")',
    ),
    aspect_ratio: str = Field(
        default="1:1",
        description='Output aspect ratio. Options: 1:1, 16:9, 9:16, 4:3, 3:4, 2:3, 3:2, 21:9, 9:21',
    ),
    seed: Optional[int] = Field(
        default=None,
        description='Seed for reproducibility (0-4294967294). Random if not specified.',
    ),
) -> dict:
    """Generate an image from text using Stable Diffusion 3.5 Large on Amazon Bedrock.

    SD3.5 Large delivers strong prompt adherence, photorealistic quality, and improved text rendering.

    ## Prompt Best Practices
    Structure prompts with: Subject, Environment, Pose/Action, Lighting, Camera angle, Style.
    Use descriptive captions rather than commands. Front-load important elements.
    Move negation words (no, not, without) to negative_prompt instead.

    ## Examples
    - "realistic editorial photo of female teacher standing at a blackboard, warm smile, soft natural lighting"
    - "drone view of a dark river winding through Iceland landscape, cinematic quality, dramatic clouds"
    - "watercolor illustration of a cozy cafe interior, warm tones, afternoon sunlight through windows"

    Returns:
        dict with status, paths (list of image URLs or local paths), and seed used.
    """
    if aspect_ratio not in VALID_ASPECT_RATIOS:
        return {"status": "error", "error": f"Invalid aspect_ratio '{aspect_ratio}'. Valid: {VALID_ASPECT_RATIOS}", "path": []}

    actual_seed = seed if seed is not None else random.randint(0, 4294967294)

    request_body = {
        "prompt": prompt,
        "mode": "text-to-image",
        "aspect_ratio": aspect_ratio,
        "seed": actual_seed,
        "output_format": "png",
    }
    if negative_prompt:
        request_body["negative_prompt"] = negative_prompt

    logger.info(f"generate_image: prompt='{prompt[:60]}...', aspect_ratio={aspect_ratio}, seed={actual_seed}")

    try:
        result = _invoke_sd35(request_body)
        return _save_and_upload(result)
    except Exception as e:
        error_msg = f"Image generation failed: {e}"
        logger.error(error_msg)
        return {"status": "error", "error": error_msg, "path": []}


@mcp.tool(name='generate_image_from_image')
async def generate_image_from_image(
    ctx: Context,
    prompt: str = Field(
        default="",
        description='Text description of the desired output image. (Required)',
    ),
    image_base64: str = Field(
        default="",
        description='Base64-encoded source image for style transfer or variation. (Required)',
    ),
    strength: float = Field(
        default=0.7,
        description='How much to transform the source image. 0.0=no change, 1.0=completely new. Recommended: 0.3 subtle, 0.5 moderate, 0.7 major, 1.0 full.',
    ),
    negative_prompt: Optional[str] = Field(
        default=None,
        description='Elements to exclude from the image.',
    ),
    seed: Optional[int] = Field(
        default=None,
        description='Seed for reproducibility (0-4294967294).',
    ),
) -> dict:
    """Transform an existing image using Stable Diffusion 3.5 Large (image-to-image).

    Use this for style transfer, variations, or guided modifications of an existing image.
    The strength parameter controls how much the output differs from the input.

    Returns:
        dict with status, paths (list of image URLs or local paths), and seed used.
    """
    if not prompt:
        return {"status": "error", "error": "prompt is required.", "path": []}
    if not image_base64:
        return {"status": "error", "error": "image_base64 is required.", "path": []}

    strength = max(0.0, min(1.0, strength))
    actual_seed = seed if seed is not None else random.randint(0, 4294967294)

    request_body = {
        "prompt": prompt,
        "mode": "image-to-image",
        "image": image_base64,
        "strength": strength,
        "seed": actual_seed,
        "output_format": "png",
    }
    if negative_prompt:
        request_body["negative_prompt"] = negative_prompt

    logger.info(f"generate_image_from_image: prompt='{prompt[:60]}...', strength={strength}, seed={actual_seed}")

    try:
        result = _invoke_sd35(request_body)
        return _save_and_upload(result, prefix="sd35l_i2i")
    except Exception as e:
        error_msg = f"Image-to-image generation failed: {e}"
        logger.error(error_msg)
        return {"status": "error", "error": error_msg, "path": []}


if __name__ == "__main__":
    mcp.run(transport="stdio")
