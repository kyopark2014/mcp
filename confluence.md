# Confluence MCP

### MCP Docker

```text
docker run --rm -i \
  -p 8080:8080 \
  -v "${HOME}/.mcp-atlassian:/home/app/.mcp-atlassian" \
  ghcr.io/sooperset/mcp-atlassian:latest --oauth-setup -v
```

[MCP Atlassian](https://github.com/sooperset/mcp-atlassian)

[Atlassian API Token](https://id.atlassian.com/manage-profile/security/api-tokens)
