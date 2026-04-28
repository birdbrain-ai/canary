import asyncio
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("canary-compiler-tools")

@mcp.tool()
async def clang_compile() -> str:
    '''
    compile with the clang compiler
    '''
    await asyncio.sleep(1)
    return "some arbitrary remark emitted by clang"


@mcp.tool()
async def icx_compile() -> str:
    '''
    compile with the icx compiler
    '''
    await asyncio.sleep(1)
    return "some arbitrary remark emitted by icx"


if __name__ == "__main__":
    mcp.run(transport='streamable-http')
