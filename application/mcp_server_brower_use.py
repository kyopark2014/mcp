"""
Browser-Use MCP Server

Exposes browser-use CLI for web browsing, search, form filling, screenshots,
and data extraction via MCP tools.
Requires: browser-use CLI installed (pip install browser-use)
Verify: browser-use doctor
See: https://github.com/browser-use/browser-use
"""

import logging
import os
import shlex
import subprocess
import sys
import json
import base64
import tempfile
from typing import Optional, Literal

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(filename)s:%(lineno)d | %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("mcp-server-browser-use")

try:
    mcp = FastMCP(
        name="browser_use",
        instructions=(
            "You are a browser automation assistant using the browser-use CLI. "
            "You can navigate websites, interact with web pages, fill forms, "
            "take screenshots, extract data, and perform web searches. "
            "Always run browser_state first to see available elements and their indices "
            "before clicking or typing. The browser persists across commands."
        ),
    )
    logger.info("MCP server (browser-use) initialized successfully")
except Exception as e:
    logger.error(f"MCP server init error: {e}")

COMMAND_TIMEOUT = 60
SEARCH_TIMEOUT = 120
DEFAULT_PROFILE = "Default"

RECAPTCHA_INDICATORS = [
    "recaptcha", "captcha", "unusual traffic", "automated queries",
    "not a robot", "verify you're human", "bot detection",
    "sorry/index", "ipv4.google.com/sorry",
]


def _ensure_path():
    """Prepend pip user script dir so browser-use CLI resolves in subprocess."""
    import site
    import sysconfig

    extra = []
    user_base = getattr(site, "USER_BASE", None)
    if user_base:
        user_bin = os.path.join(user_base, "bin")
        if os.path.isdir(user_bin):
            extra.append(user_bin)
    try:
        scripts = sysconfig.get_path("scripts")
        if scripts and os.path.isdir(scripts):
            extra.append(scripts)
    except Exception:
        pass

    path = os.environ.get("PATH", "")
    parts = [p for p in path.split(os.pathsep) if p]
    for d in reversed(extra):
        if d and d not in parts:
            parts.insert(0, d)
    os.environ["PATH"] = os.pathsep.join(parts)


_ensure_path()


def _run_browser_use(
    command: str,
    timeout: int = COMMAND_TIMEOUT,
    headed: bool = False,
    profile: Optional[str] = None,
    json_output: bool = False,
) -> dict:
    """
    Execute a browser-use CLI command.

    Returns:
        dict with status, stdout, stderr
    """
    cmd_str = command.strip()
    if cmd_str.lower().startswith("browser-use "):
        cmd_str = cmd_str[12:].strip()

    try:
        args = ["browser-use"]
        if headed:
            args.append("--headed")
        if profile:
            args.extend(["--profile", profile])
        if json_output:
            args.append("--json")
        args.extend(shlex.split(cmd_str))
    except ValueError as e:
        return {
            "status": "error",
            "stdout": "",
            "stderr": str(e),
            "message": "Invalid command syntax (check quoting)",
        }

    logger.info(f"Running: {' '.join(args)}")
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "status": "success" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "stdout": "",
            "stderr": f"Command timed out ({timeout}s)",
            "message": "browser-use command timed out",
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "stdout": "",
            "stderr": "browser-use not found. Install: pip install browser-use",
            "message": "browser-use CLI not installed",
        }
    except Exception as e:
        return {
            "status": "error",
            "stdout": "",
            "stderr": str(e),
            "message": f"browser-use execution failed: {e}",
        }


def _format_output(out: dict) -> str:
    if out["status"] == "success":
        text = out["stdout"].strip() or "(no output)"
        if out["stderr"]:
            text += f"\n[stderr: {out['stderr'].strip()}]"
        return text
    err = out.get("stderr", "") or out.get("message", "Unknown error")
    return f"Error: {err}"


# ═══════════════════════════════════════════════════════════════════
#  Navigation Tools
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def browser_open(
    url: str,
    headed: bool = False,
    profile: Optional[str] = None,
) -> str:
    """
    Navigate to a URL. Starts the browser daemon if not running.

    Args:
        url: URL to navigate to (e.g. "https://google.com")
        headed: Show browser window for debugging (default: False, headless)
        profile: Chrome profile name to use existing logins/cookies (e.g. "Default", "Profile 1")

    Returns:
        Navigation result
    """
    out = _run_browser_use(f"open {shlex.quote(url)}", headed=headed, profile=profile)
    return _format_output(out)


@mcp.tool()
def browser_back() -> str:
    """
    Go back in browser history.

    Returns:
        Navigation result
    """
    return _format_output(_run_browser_use("back"))


@mcp.tool()
def browser_scroll(
    direction: Literal["up", "down"] = "down",
    amount: Optional[int] = None,
) -> str:
    """
    Scroll the page up or down.

    Args:
        direction: Scroll direction - "up" or "down" (default: "down")
        amount: Pixels to scroll (optional, uses default if not specified)

    Returns:
        Scroll result
    """
    cmd = f"scroll {direction}"
    if amount:
        cmd += f" --amount {amount}"
    return _format_output(_run_browser_use(cmd))


@mcp.tool()
def browser_switch_tab(tab_index: int) -> str:
    """
    Switch to a browser tab by index.

    Args:
        tab_index: Tab index to switch to

    Returns:
        Tab switch result
    """
    return _format_output(_run_browser_use(f"switch {tab_index}"))


# ═══════════════════════════════════════════════════════════════════
#  Page State & Screenshots
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def browser_state() -> str:
    """
    Get the current page state: URL, title, and clickable elements with their indices.
    ALWAYS run this first to discover element indices before clicking or typing.

    Returns:
        Page state with element indices
    """
    return _format_output(_run_browser_use("state"))


@mcp.tool()
def browser_screenshot(
    filepath: Optional[str] = None,
    full_page: bool = False,
) -> str:
    """
    Take a screenshot of the current page.

    Args:
        filepath: Path to save the screenshot (optional, returns base64 if not specified)
        full_page: Capture the full scrollable page (default: False)

    Returns:
        Screenshot file path or base64-encoded image data
    """
    cmd = "screenshot"
    if filepath:
        cmd += f" {shlex.quote(filepath)}"
    if full_page:
        cmd += " --full"
    return _format_output(_run_browser_use(cmd))


# ═══════════════════════════════════════════════════════════════════
#  Interactions
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def browser_click(
    index: Optional[int] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
) -> str:
    """
    Click an element by index (from browser_state) or at pixel coordinates.

    Args:
        index: Element index from browser_state output
        x: X pixel coordinate (use with y for coordinate-based clicking)
        y: Y pixel coordinate (use with x for coordinate-based clicking)

    Returns:
        Click result
    """
    if index is not None:
        cmd = f"click {index}"
    elif x is not None and y is not None:
        cmd = f"click {x} {y}"
    else:
        return "Error: Provide either index or both x and y coordinates"
    return _format_output(_run_browser_use(cmd))


@mcp.tool()
def browser_input(index: int, text: str) -> str:
    """
    Click an element by index and type text into it.
    Equivalent to clicking the element first, then typing.

    Args:
        index: Element index from browser_state output
        text: Text to type into the element

    Returns:
        Input result
    """
    return _format_output(_run_browser_use(f"input {index} {shlex.quote(text)}"))


@mcp.tool()
def browser_type(text: str) -> str:
    """
    Type text into the currently focused element.

    Args:
        text: Text to type

    Returns:
        Type result
    """
    return _format_output(_run_browser_use(f"type {shlex.quote(text)}"))


@mcp.tool()
def browser_keys(keys: str) -> str:
    """
    Send keyboard keys (e.g. "Enter", "Control+a", "Tab", "Escape").

    Args:
        keys: Key combination to send (e.g. "Enter", "Control+a", "Shift+Tab")

    Returns:
        Keys result
    """
    return _format_output(_run_browser_use(f"keys {shlex.quote(keys)}"))


@mcp.tool()
def browser_select(index: int, option: str) -> str:
    """
    Select a dropdown option by element index.

    Args:
        index: Element index of the dropdown from browser_state
        option: Option value or text to select

    Returns:
        Select result
    """
    return _format_output(_run_browser_use(f"select {index} {shlex.quote(option)}"))


@mcp.tool()
def browser_hover(index: int) -> str:
    """
    Hover over an element by index.

    Args:
        index: Element index from browser_state output

    Returns:
        Hover result
    """
    return _format_output(_run_browser_use(f"hover {index}"))


# ═══════════════════════════════════════════════════════════════════
#  Data Extraction
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def browser_get_text(index: int) -> str:
    """
    Get the text content of an element by index.

    Args:
        index: Element index from browser_state output

    Returns:
        Element text content
    """
    return _format_output(_run_browser_use(f"get text {index}"))


@mcp.tool()
def browser_get_html(selector: Optional[str] = None) -> str:
    """
    Get the page HTML, optionally scoped to a CSS selector.

    Args:
        selector: CSS selector to scope HTML extraction (optional, returns full page if not specified)

    Returns:
        HTML content
    """
    cmd = "get html"
    if selector:
        cmd += f' --selector {shlex.quote(selector)}'
    return _format_output(_run_browser_use(cmd))


@mcp.tool()
def browser_get_title() -> str:
    """
    Get the current page title.

    Returns:
        Page title
    """
    return _format_output(_run_browser_use("get title"))


@mcp.tool()
def browser_eval(js_code: str) -> str:
    """
    Execute JavaScript code in the browser and return the result.

    Args:
        js_code: JavaScript code to execute

    Returns:
        JavaScript execution result
    """
    return _format_output(_run_browser_use(f"eval {shlex.quote(js_code)}"))


@mcp.tool()
def browser_get_value(index: int) -> str:
    """
    Get the value of an input/textarea element by index.

    Args:
        index: Element index from browser_state output

    Returns:
        Element value
    """
    return _format_output(_run_browser_use(f"get value {index}"))


@mcp.tool()
def browser_get_attributes(index: int) -> str:
    """
    Get all attributes of an element by index.

    Args:
        index: Element index from browser_state output

    Returns:
        Element attributes
    """
    return _format_output(_run_browser_use(f"get attributes {index}"))


# ═══════════════════════════════════════════════════════════════════
#  Wait
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def browser_wait_selector(
    css_selector: str,
    state: Literal["visible", "hidden", "attached", "detached"] = "visible",
    timeout_ms: int = 30000,
) -> str:
    """
    Wait for an element matching a CSS selector.

    Args:
        css_selector: CSS selector to wait for
        state: Element state to wait for - "visible", "hidden", "attached", "detached" (default: "visible")
        timeout_ms: Maximum wait time in milliseconds (default: 30000)

    Returns:
        Wait result
    """
    cmd = f"wait selector {shlex.quote(css_selector)} --state {state} --timeout {timeout_ms}"
    return _format_output(_run_browser_use(cmd, timeout=max(COMMAND_TIMEOUT, timeout_ms // 1000 + 10)))


@mcp.tool()
def browser_wait_text(text: str) -> str:
    """
    Wait for specific text to appear on the page.

    Args:
        text: Text to wait for

    Returns:
        Wait result
    """
    return _format_output(_run_browser_use(f"wait text {shlex.quote(text)}"))


# ═══════════════════════════════════════════════════════════════════
#  High-Level Search
# ═══════════════════════════════════════════════════════════════════

def _build_search_url(query: str, engine: str) -> str:
    """Build a direct search URL with query parameter."""
    from urllib.parse import quote_plus
    q = quote_plus(query)
    if engine == "google":
        return f"https://www.google.com/search?q={q}"
    elif engine == "bing":
        return f"https://www.bing.com/search?q={q}"
    elif engine == "naver":
        return f"https://search.naver.com/search.naver?query={q}"
    return f"https://www.google.com/search?q={q}"


def _build_js_extractor(engine: str, max_results: int) -> str:
    """Build a JS snippet to extract search results from the given engine."""
    if engine == "google":
        return (
            "(function(){"
            "var r=[],seen={},NL=String.fromCharCode(10),AR=String.fromCharCode(8250);"
            "var h3s=document.querySelectorAll('h3');"
            "for(var i=0;i<h3s.length;i++){"
            "var h=h3s[i],a=h.closest('a');"
            "if(!a||!a.href||a.href.startsWith('javascript'))continue;"
            "if(seen[a.href])continue;seen[a.href]=1;"
            "var block=a.parentElement;"
            "for(var p=0;p<6;p++){if(!block.parentElement)break;block=block.parentElement;if(block.offsetHeight>100)break;}"
            "var snip='';"
            "var lines=(block.innerText||'').split(NL);"
            "for(var j=0;j<lines.length;j++){var ln=lines[j].trim();"
            "if(ln.length>40&&ln!==h.innerText&&ln.indexOf('http')===-1&&ln.indexOf(AR)===-1){snip=ln;break;}}"
            "r.push({title:h.innerText,url:a.href,snippet:snip});"
            f"if(r.length>={max_results})break;"
            "}"
            "return JSON.stringify(r);"
            "})()"
        )
    elif engine == "bing":
        return f"""
(function() {{
    var results = [];
    var max = {max_results};
    var seen = {{}};

    var selectors = [
        'li.b_algo',
        '#b_results > li.b_algo',
        '#b_results li[class*="algo"]',
        '.b_algo'
    ];
    var items = [];
    for (var s = 0; s < selectors.length; s++) {{
        items = document.querySelectorAll(selectors[s]);
        if (items.length > 0) break;
    }}

    for (var i = 0; i < Math.min(items.length, max); i++) {{
        var item = items[i];
        var titleEl = item.querySelector('h2 a') || item.querySelector('h2 > a') || item.querySelector('a h2');
        var snippetEl = item.querySelector('.b_caption p') || item.querySelector('p') || item.querySelector('.b_caption');
        var aEl = titleEl || item.querySelector('a[href^="http"]');
        if (aEl) {{
            var url = aEl.href || aEl.closest('a')?.href || '';
            if (url && !seen[url]) {{
                seen[url] = 1;
                var title = '';
                var h2 = item.querySelector('h2');
                if (h2) title = h2.innerText || '';
                else if (aEl.innerText) title = aEl.innerText;
                results.push({{
                    title: title,
                    url: url,
                    snippet: snippetEl ? snippetEl.innerText : ''
                }});
            }}
        }}
    }}

    if (results.length === 0) {{
        var container = document.querySelector('#b_results') || document.querySelector('main') || document.body;
        var allLinks = container.querySelectorAll('a[href^="http"]');
        for (var j = 0; j < allLinks.length && results.length < max; j++) {{
            var link = allLinks[j];
            var href = link.href;
            if (!href || seen[href]) continue;
            if (href.indexOf('bing.com') !== -1 || href.indexOf('microsoft.com') !== -1) continue;
            if (href.indexOf('go.microsoft.com') !== -1) continue;
            seen[href] = 1;
            var txt = link.innerText.trim();
            if (txt.length < 5) continue;
            results.push({{
                title: txt,
                url: href,
                snippet: ''
            }});
        }}
    }}

    return JSON.stringify(results);
}})()
"""
    else:  # naver
        return f"""
(function() {{
    var results = [];
    var items = document.querySelectorAll('div.total_wrap, li.bx');
    var max = {max_results};
    for (var i = 0; i < Math.min(items.length, max); i++) {{
        var item = items[i];
        var titleEl = item.querySelector('a.link_tit, a.total_tit, a.api_txt_lines');
        var snippetEl = item.querySelector('div.total_dsc, div.api_txt_lines, div.dsc_wrap');
        if (titleEl) {{
            results.push({{
                title: titleEl.innerText || '',
                url: titleEl.href || '',
                snippet: snippetEl ? snippetEl.innerText : ''
            }});
        }}
    }}
    return JSON.stringify(results);
}})()
"""


def _detect_captcha(page_text: str) -> bool:
    """Check if page content contains reCAPTCHA / bot-detection indicators."""
    lower = page_text.lower()
    return any(indicator in lower for indicator in RECAPTCHA_INDICATORS)


def _extract_search_results(raw: str) -> list | None:
    """Try to parse JSON search results from eval output.

    browser-use eval may prefix output with 'result: ' or similar labels.
    """
    text = raw.strip()

    prefix_patterns = ["result: ", "result:", "output: ", "output:"]
    for prefix in prefix_patterns:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
            break

    for candidate in (text, raw.strip()):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        if candidate.startswith('"') and candidate.endswith('"'):
            try:
                inner = json.loads(candidate)
                parsed = json.loads(inner)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass

    logger.warning(f"Could not parse search results from eval output: {raw[:200]}")
    return None


def _do_search(
    query: str,
    search_engine: str,
    max_results: int,
    headed: bool,
    profile: Optional[str],
) -> tuple[list | None, str]:
    """
    Core search logic: open search URL, wait, extract results.
    Returns (results_list_or_None, raw_output_for_debugging).
    """
    import time

    search_url = _build_search_url(query, search_engine)

    open_out = _run_browser_use(
        f"open {shlex.quote(search_url)}", headed=headed, profile=profile,
    )
    if open_out["status"] == "error":
        err_text = open_out.get("stderr", "") + open_out.get("stdout", "")
        if "already running with different config" in err_text:
            logger.info("Session conflict detected, closing and retrying...")
            _run_browser_use("close")
            open_out = _run_browser_use(
                f"open {shlex.quote(search_url)}", headed=headed, profile=profile,
            )
        if open_out["status"] == "error":
            return None, _format_output(open_out)

    time.sleep(3)

    state_out = _run_browser_use("state")
    state_text = state_out.get("stdout", "")

    if _detect_captcha(state_text):
        return None, "__CAPTCHA__"

    js_code = _build_js_extractor(search_engine, max_results)
    eval_out = _run_browser_use(f"eval {shlex.quote(js_code)}", timeout=SEARCH_TIMEOUT)
    if eval_out["status"] == "error":
        return None, _format_output(eval_out)

    raw = eval_out["stdout"].strip()
    logger.info(f"Eval raw output ({len(raw)} chars): {raw[:300]}")

    if _detect_captcha(raw):
        return None, "__CAPTCHA__"

    results = _extract_search_results(raw)
    logger.info(f"Parsed results: {type(results).__name__}, count={len(results) if results is not None else 'None'}")
    return results, raw


def _extract_results_from_page_text(query: str, max_results: int) -> list | None:
    """Fallback: extract links from page state when JS selectors fail."""
    import re

    state_out = _run_browser_use("state")
    state_text = state_out.get("stdout", "")
    if not state_text:
        return None

    link_pattern = re.compile(
        r'\[(\d+)\]\s*<a[^>]*>\s*(.*?)\s*</a>|'
        r'(?:^|\n)\s*\[(\d+)\]\s*(.+?)\s*\n\s*(?:https?://\S+)',
        re.IGNORECASE,
    )
    url_pattern = re.compile(r'(https?://[^\s<>"\']+)')

    results = []
    lines = state_text.split('\n')
    i = 0
    while i < len(lines) and len(results) < max_results:
        line = lines[i].strip()
        urls_in_line = url_pattern.findall(line)
        if urls_in_line:
            url = urls_in_line[0]
            if any(skip in url for skip in ['google.com/search', 'bing.com/search', 'bing.com/aclick']):
                i += 1
                continue
            title = re.sub(r'https?://\S+', '', line).strip()
            title = re.sub(r'^\[\d+\]\s*(<\w+[^>]*>)?\s*', '', title).strip()
            if not title and i > 0:
                title = lines[i - 1].strip()
            snippet = ""
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and not url_pattern.match(next_line):
                    snippet = next_line
            if title and url:
                results.append({"title": title, "url": url, "snippet": snippet})
        i += 1

    logger.info(f"Text extraction fallback found {len(results)} results")
    return results if results else None


def _format_search_results(query: str, results: list) -> str:
    output_lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        output_lines.append(f"{i}. {r.get('title', 'No title')}")
        output_lines.append(f"   URL: {r.get('url', '')}")
        snippet = r.get("snippet", "")
        if snippet:
            output_lines.append(f"   {snippet}")
        output_lines.append("")
    return "\n".join(output_lines)


@mcp.tool()
def browser_web_search(
    query: str,
    search_engine: Literal["google", "bing", "naver"] = "google",
    max_results: int = 5,
    headed: bool = False,
    profile: Optional[str] = None,
) -> str:
    """
    Perform a web search using a real browser and extract results.

    Uses a direct search URL (not form input) for reliability.
    For Google, automatically uses a Chrome profile to avoid reCAPTCHA bot detection.
    If reCAPTCHA is still detected, retries with Chrome profile mode automatically.

    Args:
        query: Search query string
        search_engine: Search engine to use - "google", "bing", or "naver" (default: "google")
        max_results: Maximum number of results to extract (default: 5)
        headed: Show browser window (default: False)
        profile: Chrome profile name (default: auto-selected; "Default" for Google to avoid reCAPTCHA)

    Returns:
        Formatted search results with titles, URLs, and snippets
    """
    use_profile = profile
    if use_profile is None and search_engine == "google":
        use_profile = DEFAULT_PROFILE

    results, raw = _do_search(query, search_engine, max_results, headed, use_profile)

    if raw == "__CAPTCHA__" and use_profile is None:
        logger.info("CAPTCHA detected, retrying with Chrome profile...")
        _run_browser_use("close")
        results, raw = _do_search(query, search_engine, max_results, headed, DEFAULT_PROFILE)

    if raw == "__CAPTCHA__":
        logger.info("CAPTCHA detected even with profile, falling back to Bing...")
        _run_browser_use("close")
        fallback_engine = "bing" if search_engine != "bing" else "naver"
        results, raw = _do_search(query, fallback_engine, max_results, headed, use_profile)

        if raw == "__CAPTCHA__":
            return (
                f"Error: Search blocked by CAPTCHA on both {search_engine} and {fallback_engine}. "
                "Try using a Chrome profile with existing login sessions: "
                'browser_web_search(query="...", profile="Default")'
            )

        if results is not None and len(results) > 0:
            return (
                f"[Note: {search_engine} blocked by CAPTCHA, used {fallback_engine} instead]\n\n"
                + _format_search_results(query, results)
            )

        if results is not None and len(results) == 0:
            logger.warning(f"Fallback {fallback_engine} returned 0 results, attempting text extraction")
            text_results = _extract_results_from_page_text(query, max_results)
            if text_results:
                return (
                    f"[Note: {search_engine} blocked by CAPTCHA, used {fallback_engine} text extraction]\n\n"
                    + _format_search_results(query, text_results)
                )
            return f"Search on {fallback_engine} returned no results for: {query}"

    if results is not None and len(results) > 0:
        return _format_search_results(query, results)

    if results is not None and len(results) == 0:
        logger.warning("JS extractor returned empty array, attempting text extraction fallback")
        text_results = _extract_results_from_page_text(query, max_results)
        if text_results:
            return _format_search_results(query, text_results)
        return f"Search returned no results for: {query}"

    return f"Search completed but could not parse results. Raw output:\n{raw}"


# ═══════════════════════════════════════════════════════════════════
#  Session Management
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def browser_close(close_all: bool = False) -> str:
    """
    Close the browser session. Call when browsing tasks are done.

    Args:
        close_all: Close all browser sessions (default: False, closes current only)

    Returns:
        Close result
    """
    cmd = "close"
    if close_all:
        cmd += " --all"
    return _format_output(_run_browser_use(cmd))


@mcp.tool()
def browser_sessions() -> str:
    """
    List active browser sessions.

    Returns:
        List of active sessions
    """
    return _format_output(_run_browser_use("sessions"))


# ═══════════════════════════════════════════════════════════════════
#  Cookies
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def browser_cookies_get(url: Optional[str] = None) -> str:
    """
    Get browser cookies, optionally filtered by URL.

    Args:
        url: URL to filter cookies (optional)

    Returns:
        Cookie data
    """
    cmd = "cookies get"
    if url:
        cmd += f" --url {shlex.quote(url)}"
    return _format_output(_run_browser_use(cmd))


@mcp.tool()
def browser_cookies_clear(url: Optional[str] = None) -> str:
    """
    Clear browser cookies, optionally for a specific URL.

    Args:
        url: URL to clear cookies for (optional, clears all if not specified)

    Returns:
        Clear result
    """
    cmd = "cookies clear"
    if url:
        cmd += f" --url {shlex.quote(url)}"
    return _format_output(_run_browser_use(cmd))


# ═══════════════════════════════════════════════════════════════════
#  Generic Command Runner
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
def browser_run(
    command: str,
    headed: bool = False,
    profile: Optional[str] = None,
    timeout: int = COMMAND_TIMEOUT,
) -> str:
    """
    Run an arbitrary browser-use CLI command. Use this for advanced operations
    not covered by the specialized tools above.

    Examples:
        - "dblclick 5" (double-click element 5)
        - "rightclick 3" (right-click element 3)
        - "upload 7 /path/to/file.pdf" (upload file)
        - "close-tab" (close current tab)
        - "get bbox 4" (get bounding box of element 4)
        - "python \\"print(browser.url)\\"" (run Python with browser access)

    Args:
        command: browser-use subcommand and arguments
        headed: Show browser window (default: False)
        profile: Chrome profile name (optional)
        timeout: Command timeout in seconds (default: 60)

    Returns:
        Command output
    """
    return _format_output(
        _run_browser_use(command, timeout=timeout, headed=headed, profile=profile)
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
