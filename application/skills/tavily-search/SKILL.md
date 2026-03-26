---
name: tavily-search
description: "Web search using Tavily AI-powered search API. Returns AI-synthesized answers with citations and structured search results. Use when the user explicitly requests Tavily search, or when high-quality AI-synthesized answers with citations are needed for research, fact-checking, or comprehensive information gathering. Requires TAVILY_API_KEY."
---

# Tavily Search

AI-powered web search that returns synthesized answers with citations and structured results.

## Requirements

- `pip install tavily-python`
- `TAVILY_API_KEY` environment variable (get key at https://tavily.com)

## Script Location

**IMPORTANT**: Always use the FULL path `skills/tavily-search/scripts/search.py` — do NOT shorten to `scripts/search.py`.

## Quick Start

```bash
# Basic search
python skills/tavily-search/scripts/search.py "latest AI developments"

# Advanced search with more results
python skills/tavily-search/scripts/search.py "quantum computing breakthroughs" --max-results 10 --depth advanced

# Text format output
python skills/tavily-search/scripts/search.py "climate change news" --format text
```

## Command-Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `query` (required) | — | Search query |
| `--max-results N` | 5 | Maximum results (1-10) |
| `--depth [basic\|advanced]` | basic | `basic`: fast; `advanced`: deep, comprehensive (slower, costs more) |
| `--no-answer` | — | Exclude AI-generated answer |
| `--raw-content` | — | Include full page content |
| `--format [json\|text]` | json | Output format |

## Response Format

- `answer`: AI-synthesized answer to the query
- `results[]`: `title`, `url`, `content` (excerpt), `score` (relevance)
- `query`: Original query
- `response_time`: API response time

## Agent Integration

```python
import subprocess, json

result = subprocess.run(
    ["python", "skills/tavily-search/scripts/search.py", query, "--max-results", "5"],
    capture_output=True, text=True
)
response = json.loads(result.stdout)
```

## Notes

- **API key**: Set `TAVILY_API_KEY` in environment or `~/.openclaw/.env`
- **Search depth**: Use `basic` for most queries; `advanced` for research
- **Rate limits**: Check Tavily pricing page for your plan's limits