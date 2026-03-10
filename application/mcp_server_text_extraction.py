"""
MCP server for extracting text from images using LLM (AWS Bedrock).
Based on chat.py summarize_image and extract_text logic.
"""
import base64
import logging
import os
import sys
import traceback
from io import BytesIO
from typing import Optional

import boto3
from botocore.config import Config
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage
from mcp.server.fastmcp import FastMCP
from PIL import Image

import info
import utils

logging.basicConfig(
    level=logging.INFO,
    format="%(filename)s:%(lineno)d | %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("text-extraction-mcp")

config = utils.load_config()
bedrock_region = config.get("region", "us-west-2")
model_name = "Claude 4.6 Sonnet"
models = info.get_model_info(model_name)
profile = models[0]
model_id = profile["model_id"]
model_type = profile["model_type"]

try:
    mcp = FastMCP(
        name="text_extraction",
        instructions=(
            "Extract text from images using an LLM. "
            "Use extract_text_from_image when the user provides an image (base64 or file path) and wants to extract text from it."
        ),
    )
    logger.info("Text extraction MCP server initialized successfully")
except Exception as e:
    logger.error(f"Error initializing MCP: {str(e)}")
    raise


def _get_chat():
    """Create ChatBedrock instance for text extraction."""
    stop_sequence = "\n\nHuman:" if model_type == "claude" else ""
    max_tokens = 16384 if "claude-4" in model_id else 8192

    boto3_bedrock = boto3.client(
        service_name="bedrock-runtime",
        region_name=bedrock_region,
        config=Config(retries={"max_attempts": 30}),
    )

    parameters = {
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "top_k": 250,
        "stop_sequences": [stop_sequence],
    }

    return ChatBedrock(
        model_id=model_id,
        client=boto3_bedrock,
        model_kwargs=parameters,
        region_name=bedrock_region,
    )


def _prepare_image_base64(
    image_content: bytes,
    max_size: int = 5 * 1024 * 1024,
    max_pixels: int = 2000000,
) -> str:
    """Resize image if needed and return base64 string."""
    img = Image.open(BytesIO(image_content))
    width, height = img.size
    logger.info(f"Image size: {width}x{height}, pixels: {width * height}")

    is_resized = False
    while width * height > max_pixels:
        width = int(width / 2)
        height = int(height / 2)
        is_resized = True
        logger.info(f"Resized to {width}x{height}")

    if is_resized:
        img = img.resize((width, height))

    max_attempts = 5
    base64_size = 0
    for attempt in range(max_attempts):
        buffer = BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        img_bytes = buffer.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")
        base64_size = len(img_base64.encode("utf-8"))
        logger.info(f"Attempt {attempt + 1}: base64_size = {base64_size} bytes")

        if base64_size <= max_size:
            return img_base64

        width = int(width * 0.8)
        height = int(height * 0.8)
        img = img.resize((width, height))
        logger.info(f"Resizing to {width}x{height} due to size limit")

    raise ValueError("이미지 크기가 너무 큽니다. 5MB 이하의 이미지를 사용해주세요.")


def _extract_text_with_llm(img_base64: str, prompt: Optional[str] = None) -> str:
    """Extract text from image using LLM."""
    query = prompt or "텍스트를 추출해서 markdown 포맷으로 변환하세요. <result> tag를 붙여주세요."

    multimodal = _get_chat()
    messages = [
        HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                },
                {"type": "text", "text": query},
            ]
        )
    ]

    extracted_text = ""
    for attempt in range(5):
        logger.info(f"LLM attempt: {attempt}")
        try:
            result = multimodal.invoke(messages)
            extracted_text = result.content
            break
        except Exception:
            err_msg = traceback.format_exc()
            logger.warning(f"LLM error: {err_msg}")

    if len(extracted_text) < 10:
        extracted_text = "텍스트를 추출하지 못하였습니다."

    return extracted_text


def _parse_result(text: str) -> str:
    """Extract content from <result> tag if present."""
    if text.find("<result>") != -1:
        return text[text.find("<result>") + 8 : text.find("</result>")]
    return text


@mcp.tool()
def extract_text_from_image(
    image_base64: Optional[str] = None,
    image_path: Optional[str] = None,
    prompt: Optional[str] = None,
) -> str:
    """Extract text from an image using an LLM (AWS Bedrock).

    Provide either image_base64 or image_path. The image is resized automatically
    if it exceeds size limits (5MB, ~2M pixels).

    Args:
        image_base64: Base64-encoded image string (without data URL prefix)
        image_path: Path to image file (jpg, png, etc.)
        prompt: Optional custom prompt for extraction. Default asks for markdown format with <result> tag.

    Returns:
        Extracted text from the image in markdown format.
    """
    logger.info(f"extract_text_from_image called: path={image_path}, prompt={'custom' if prompt else 'default'}")

    if not image_base64 and not image_path:
        return "Error: image_base64 또는 image_path 중 하나를 제공해주세요."

    if image_base64 and image_path:
        return "Error: image_base64와 image_path 중 하나만 제공해주세요."

    try:
        if image_path:
            if not os.path.isfile(image_path):
                return f"Error: 파일을 찾을 수 없습니다: {image_path}"
            with open(image_path, "rb") as f:
                image_content = f.read()
        else:
            try:
                image_content = base64.b64decode(image_base64)
            except Exception as e:
                return f"Error: Base64 디코딩 실패: {str(e)}"

        img_base64 = _prepare_image_base64(image_content)
        text = _extract_text_with_llm(img_base64, prompt)
        extracted_text = _parse_result(text)
        logger.info(f"Extracted text length: {len(extracted_text)}")
        return extracted_text

    except ValueError as e:
        logger.warning(str(e))
        return str(e)
    except Exception as e:
        err_msg = traceback.format_exc()
        logger.error(err_msg)
        return f"Error: 이미지 텍스트 추출 중 오류 발생: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
