---
name: tavily-search
description: Web search using Tavily AI-powered search API. Returns AI-synthesized answers with citations and structured search results. Use when the user explicitly requests Tavily search, or when high-quality AI-synthesized answers with citations are needed for research, fact-checking, or comprehensive information gathering. Requires TAVILY_API_KEY.
---

# Tavily Search

AI-powered web search that returns synthesized answers with citations and structured results.

## When to Use

- User explicitly requests "use Tavily" or "search with Tavily"
- Research tasks requiring comprehensive, cited answers
- Fact-checking with source verification
- Alternative to Brave/Perplexity when specifically requested

## Requirements

- Python 3.6+
- `tavily-python` package: `pip install tavily-python`
- `TAVILY_API_KEY` environment variable

Get your API key at: https://tavily.com

## Script Location

The search script is located at `skills/tavily-search/scripts/search.py` relative to the application working directory.
**IMPORTANT**: Always use the FULL path `skills/tavily-search/scripts/search.py` — do NOT shorten to `scripts/search.py`.

## Quick Start

### Basic search

```bash
python skills/tavily-search/scripts/search.py "latest AI developments"
```

### Advanced search with more results

```bash
python skills/tavily-search/scripts/search.py "quantum computing breakthroughs" --max-results 10 --depth advanced
```

### Text format output

```bash
python skills/tavily-search/scripts/search.py "climate change news" --format text
```

## Usage

### Command-line options

- `query` (required): Search query
- `--max-results N`: Maximum results (1-10, default: 5)
- `--depth [basic|advanced]`: Search depth (default: basic)
  - `basic`: Fast, general search
  - `advanced`: Deep, comprehensive search (slower, costs more)
- `--no-answer`: Exclude AI-generated answer
- `--raw-content`: Include full page content
- `--format [json|text]`: Output format (default: json)

### Response format

Tavily returns:

- `answer`: AI-synthesized answer to the query
- `results`: Array of search results with:
  - `title`: Page title
  - `url`: Source URL
  - `content`: Relevant excerpt
  - `score`: Relevance score
- `query`: Original query
- `response_time`: API response time

## Examples

### Research query

```bash
python skills/tavily-search/scripts/search.py "What are the latest developments in quantum computing?" --depth advanced
```

Returns comprehensive answer with 5-10 cited sources.

### Quick fact check

```bash
python skills/tavily-search/scripts/search.py "When was the Eiffel Tower built?" --max-results 3
```

Fast answer with minimal sources.

### News search

```bash
python skills/tavily-search/scripts/search.py "breaking news today" --format text
```

Human-readable format with headlines and summaries.

## Integration in OpenClaw

When called by the agent, run the script and parse the JSON output.
**IMPORTANT**: The script path MUST be `skills/tavily-search/scripts/search.py` (full path from the application working directory).

```python
import subprocess
import json

SEARCH_SCRIPT = "skills/tavily-search/scripts/search.py"

result = subprocess.run(
    ["python", SEARCH_SCRIPT, query, "--max-results", "5"],
    capture_output=True,
    text=True
)
response = json.loads(result.stdout)
```

## Notes

- **API key**: Set `TAVILY_API_KEY` in environment or `~/.openclaw/.env`
- **Rate limits**: Check Tavily pricing page for your plan's limits
- **Search depth**: Use `basic` for most queries; `advanced` for research
- **Cost**: Advanced search costs more credits per query

## Troubleshooting

### Module not found

```bash
pip install tavily-python
```

### Missing API key

```bash
export TAVILY_API_KEY="tvly-xxx"
```

### Permission denied

```bash
chmod +x skills/tavily-search/scripts/search.py
```