from mcp.server.mcpserver import MCPServer 

mcp =MCPServer("Math") 

@mcp.tool()
def add(a: int, b: int) -> int:
    return a + b

@mcp.tool()
def multiply(a: int, b: int) -> int:
    return a * b

if __name__ =="__main__":
    print(f"###### main ######")
    mcp.run(transport="stdio")