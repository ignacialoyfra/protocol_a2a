# gitlab_sidecar.py
import os, urllib.parse
import httpx
from typing import Optional
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gitlab-extra")

def _base_url() -> str:
    
    return os.environ.get("GITLAB_API_URL", "https://gitlab.com/api/v4").rstrip("/")

def _auth_headers() -> dict:
    token = os.environ.get("GITLAB_PERSONAL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("Falta GITLAB_PERSONAL_ACCESS_TOKEN")
    
    return {"PRIVATE-TOKEN": token}

@mcp.tool()
async def list_issues(
    project_id: str,
    state: str = "opened",               # opened | closed | all
    labels: Optional[str] = None,        # "bug,urgent"
    search: Optional[str] = None,        # texto en título/descripción
    page: int = 1,
    per_page: int = 20
) -> str:
    """
    Lista issues de un proyecto de GitLab (ID numérico o path url-encoded).
    Devuelve ID interno (iid), título, estado, autor y URL.
    """
    base = _base_url()
    pid = urllib.parse.quote_plus(project_id)
    url = f"{base}/projects/{pid}/issues"

    params = {"state": state, "page": page, "per_page": per_page}
    if labels:
        params["labels"] = labels
    if search:
        params["search"] = search

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=_auth_headers(), params=params)
        r.raise_for_status()
        issues = r.json()

    if not issues:
        return "No se encontraron issues con esos criterios."

    lines = []
    for it in issues:
        iid = it.get("iid")
        title = it.get("title")
        st = it.get("state")
        author = (it.get("author") or {}).get("username")
        web = it.get("web_url")
        lines.append(f"#{iid} [{st}] {title} — @{author} — {web}")
    return "\n".join(lines)

if __name__ == "__main__":
    # Ejecuta por STDIO (¡no uses print en stdout! usa logging a stderr si necesitas logs)
    mcp.run(transport="stdio")
