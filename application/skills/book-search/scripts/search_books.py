#!/usr/bin/env python3
"""
Book search script using Kyobo Book Centre API
"""

import requests
from bs4 import BeautifulSoup
import sys
import urllib.parse

def get_book_list(keyword: str) -> str:
    """
    Search book list by keyword and then return book list
    keyword: search keyword
    return: book list
    """
    
    # URL encode the keyword to handle special characters
    keyword = urllib.parse.quote(keyword.replace(" ", "+"))

    answer = ""
    url = f"https://search.kyobobook.co.kr/search?keyword={keyword}&gbCode=TOT&target=total"
    
    try:
        response = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            prod_info = soup.find_all('a', attrs={'class': 'prod_info'})
            
            if len(prod_info):
                answer = "추천 도서는 아래와 같습니다.\n\n"
                
            for prod in prod_info[:5]:
                title = prod.text.strip().replace('\n', ' ')       
                link = prod.get('href')
                if link and not link.startswith('http'):
                    link = 'https://www.kyobobook.co.kr' + link
                answer = answer + f"{title}, URL: {link}\n\n"
        else:
            answer = f"검색 중 오류가 발생했습니다. (상태 코드: {response.status_code})"
            
    except Exception as e:
        answer = f"검색 중 오류가 발생했습니다: {str(e)}"
    
    return answer

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python search_books.py <keyword>")
        sys.exit(1)
    
    keyword = sys.argv[1]
    result = get_book_list(keyword)
    print(result)