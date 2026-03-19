"""
MCP server for book search using Kyobo Bookstore (교보문고).
"""
import logging
import sys
import requests

from mcp.server.fastmcp import FastMCP
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-server-books")

try:
    mcp = FastMCP(
        name="books",
        instructions=(
            "You are a helpful assistant that searches for books. "
            "You can search books by keyword using Kyobo Bookstore (교보문고). "
            "Returns up to 5 recommended books with titles and purchase links."
        ),
    )
    logger.info("Books MCP server initialized successfully")
except Exception as e:
    logger.error(f"Error: {e}")


def get_book_list(keyword: str) -> str:
    """
    Search book list by keyword and then return book list
    keyword: search keyword
    return: book list
    """
    
    keyword = keyword.replace('\'','')

    answer = ""
    url = f"https://search.kyobobook.co.kr/search?keyword={keyword}&gbCode=TOT&target=total"
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")
        prod_info = soup.find_all("a", attrs={"class": "prod_info"})
        
        if len(prod_info):
            answer = "추천 도서는 아래와 같습니다.\n"
            
        for prod in prod_info[:5]:
            title = prod.text.strip().replace("\n", "")       
            link = prod.get("href")
            answer = answer + f"{title}, URL: {link}\n\n"
    
    return answer

@mcp.tool()
def search_books(keyword: str) -> str:
    """
    Search book list by keyword and return recommended books.
    keyword: search keyword (e.g., book title, author name, topic)
    return: list of up to 5 recommended books with titles and URLs
    """
    logger.info(f"search_books --> keyword: {keyword}")
    return get_book_list(keyword)


if __name__ == "__main__":
    mcp.run(transport="stdio")
