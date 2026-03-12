import logging
import sys
import os
from urllib import parse

import boto3
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from mcp.server.fastmcp import FastMCP

import utils

logging.basicConfig(
    level=logging.INFO,
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("pdf-generator-server")

config = utils.load_config()
bedrock_region = config.get("region", "us-west-2")
s3_bucket = config.get("s3_bucket", None)
sharing_url = config.get("sharing_url", None)
s3_prefix = "docs"

try:
    mcp = FastMCP(
        name = "pdf-generator",
        instructions=(
            "You are a helpful assistant. "
            "You generate PDF reports from provided content."
        ),
    )
    logger.info("MCP server initialized successfully")
except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.info(f"{err_msg}")


def _upload_pdf_to_s3(filepath: str, filename: str) -> str:
    """Upload the generated PDF to the S3 docs folder and return the sharing URL."""
    s3_client = boto3.client(
        service_name='s3',
        region_name=bedrock_region,
    )

    s3_key = f"{s3_prefix}/{filename}.pdf"

    with open(filepath, 'rb') as f:
        pdf_bytes = f.read()

    response = s3_client.put_object(
        Bucket=s3_bucket,
        Key=s3_key,
        ContentType='application/pdf',
        Body=pdf_bytes
    )
    logger.info(f"S3 upload response: {response}")

    url = f"{sharing_url}/{s3_prefix}/{parse.quote(filename + '.pdf')}"
    return url


######################################
# PDF Generation
######################################
@mcp.tool()
async def generate_pdf(report_content: str, filename: str) -> str:
    """
    Generate a PDF report from the provided content, upload it to S3, and return the download link.
    The content can include Markdown-style headings (# , ## , ### ) which will be styled accordingly.

    report_content: the text content to convert into a PDF report. Supports Markdown headings.
    filename: the base name for the generated PDF file (without .pdf extension)
    return: the download URL of the generated PDF
    """
    logger.info(f"generate_pdf --> filename: {filename}")

    try:
        os.makedirs("artifacts", exist_ok=True)

        filepath = f"artifacts/{filename}.pdf"
        logger.info(f"filepath: {filepath}")
        doc = SimpleDocTemplate(filepath, pagesize=letter)

        font_path = "assets/NanumGothic-Regular.ttf"
        pdfmetrics.registerFont(TTFont('NanumGothic', font_path))

        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='Normal_KO',
                                fontName='NanumGothic',
                                fontSize=10,
                                spaceAfter=12))
        styles.add(ParagraphStyle(name='Heading1_KO',
                                fontName='NanumGothic',
                                fontSize=16,
                                spaceAfter=20,
                                textColor=colors.HexColor('#0000FF')))
        styles.add(ParagraphStyle(name='Heading2_KO',
                                fontName='NanumGothic',
                                fontSize=14,
                                spaceAfter=16,
                                textColor=colors.HexColor('#0000FF')))
        styles.add(ParagraphStyle(name='Heading3_KO',
                                fontName='NanumGothic',
                                fontSize=12,
                                spaceAfter=14,
                                textColor=colors.HexColor('#0000FF')))

        elements = []
        lines = report_content.split('\n')
        for line in lines:
            if line.startswith('# '):
                elements.append(Paragraph(line[2:], styles['Heading1_KO']))
            elif line.startswith('## '):
                elements.append(Paragraph(line[3:], styles['Heading2_KO']))
            elif line.startswith('### '):
                elements.append(Paragraph(line[4:], styles['Heading3_KO']))
            elif line.strip():
                elements.append(Paragraph(line, styles['Normal_KO']))

        doc.build(elements)
        logger.info(f"PDF generated: {filepath}")

        if s3_bucket and sharing_url:
            url = _upload_pdf_to_s3(filepath, filename)
            logger.info(f"PDF uploaded to S3: {url}")
            return f"PDF report generated and uploaded successfully. Download link: {url}"
        else:
            logger.warning("S3 bucket or sharing_url not configured. Skipping upload.")
            return f"PDF report generated locally: {filepath} (S3 upload skipped: s3_bucket or sharing_url not configured)"

    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        try:
            text_filepath = f"artifacts/{filename}.txt"
            with open(text_filepath, 'w', encoding='utf-8') as f:
                f.write(report_content)
            return f"PDF generation failed. Saved as text file instead: {text_filepath}"
        except Exception as text_error:
            return f"Error generating report: {str(e)}. Text fallback also failed: {str(text_error)}"

if __name__ =="__main__":
    mcp.run(transport="stdio")
