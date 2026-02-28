#!/usr/bin/env python3
"""
Tavily Search API wrapper
Requires: pip install tavily-python
"""
import os
import sys
import json
import argparse


def search(query: str, max_results: int = 5, search_depth: str = "basic", include_answer: bool = True, include_raw_content: bool = False):
    """
    Search the web using Tavily API

    Args:
        query: Search query
        max_results: Maximum number of results (1-10)
        search_depth: 'basic' or 'advanced'
        include_answer: Include AI-generated answer
        include_raw_content: Include raw page content

    Returns:
        JSON response from Tavily API
    """
    try:
        from tavily import TavilyClient
    except ImportError:
        return {
            "error": "tavily-python not installed",
            "message": "Install with: pip install tavily-python",
            "query": query
        }

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return {
            "error": "missing_api_key",
            "message": "Set TAVILY_API_KEY environment variable. Get your key at https://tavily.com",
            "query": query
        }

    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer=include_answer,
            include_raw_content=include_raw_content
        )
        return response
    except Exception as e:
        return {
            "error": "api_error",
            "message": str(e),
            "query": query
        }


def main():
    parser = argparse.ArgumentParser(description="Search the web using Tavily API")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--max-results", type=int, default=5, help="Maximum results (1-10)")
    parser.add_argument("--depth", choices=["basic", "advanced"], default="basic", help="Search depth")
    parser.add_argument("--no-answer", action="store_true", help="Exclude AI answer")
    parser.add_argument("--raw-content", action="store_true", help="Include raw page content")
    parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format")

    args = parser.parse_args()

    result = search(
        query=args.query,
        max_results=args.max_results,
        search_depth=args.depth,
        include_answer=not args.no_answer,
        include_raw_content=args.raw_content
    )

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # Text format
        if "error" in result:
            print(f"Error: {result['message']}", file=sys.stderr)
            sys.exit(1)

        if result.get("answer"):
            print(f"## Answer\n{result['answer']}\n")

        print("## Results")
        for i, r in enumerate(result.get("results", []), 1):
            print(f"\n{i}. **{r.get('title', 'No title')}**")
            print(f"   URL: {r.get('url', 'N/A')}")
            if r.get("content"):
                print(f"   {r['content'][:200]}...")


if __name__ == "__main__":
    main()