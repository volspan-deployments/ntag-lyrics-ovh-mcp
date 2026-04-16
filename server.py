from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse
import uvicorn
import threading
from fastmcp import FastMCP
import httpx
import os
from typing import Optional

mcp = FastMCP("lyrics-ovh")

BASE_URL = "https://api.lyrics.ovh"


@mcp.tool()
async def get_lyrics(artist: str, title: str) -> dict:
    """Fetch the full lyrics for a specific song by artist name and song title.
    Use this when the user wants to read, quote, or analyze the lyrics of a known song.
    Returns the complete lyrics text or a 404 error if not found.
    Lyrics are sourced from multiple providers (Genius, AZLyrics, etc.) in parallel.
    """
    url = f"{BASE_URL}/v1/{httpx.URL('').copy_with()}"
    # Build URL manually to handle special characters properly
    encoded_artist = httpx.URL("").copy_with()
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{BASE_URL}/v1/{artist}/{title}",
                follow_redirects=True
            )
            if response.status_code == 404:
                return {
                    "success": False,
                    "error": "No lyrics found for this artist and song title.",
                    "artist": artist,
                    "title": title
                }
            if response.status_code == 400:
                return {
                    "success": False,
                    "error": "Invalid artist or title provided.",
                    "artist": artist,
                    "title": title
                }
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                return {
                    "success": False,
                    "error": data["error"],
                    "artist": artist,
                    "title": title
                }
            return {
                "success": True,
                "artist": artist,
                "title": title,
                "lyrics": data.get("lyrics", "")
            }
        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Request timed out while fetching lyrics. Please try again.",
                "artist": artist,
                "title": title
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP error {e.response.status_code} while fetching lyrics.",
                "artist": artist,
                "title": title
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "artist": artist,
                "title": title
            }


@mcp.tool()
async def suggest_songs(query: str) -> dict:
    """Search for songs and artists using a free-text search term.
    Use this when the user is unsure of the exact artist or song title, wants to discover songs,
    or needs to look up correct spelling. Returns a list of matching songs with artist info
    sourced from Deezer. Use the results to then call get_lyrics with the correct artist/title.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(
                f"{BASE_URL}/suggest/{query}",
                follow_redirects=True
            )
            response.raise_for_status()
            data = response.json()
            
            if "error" in data:
                return {
                    "success": False,
                    "error": data["error"],
                    "query": query
                }
            
            raw_results = data.get("data", [])
            
            # Format the results into a clean, useful structure
            formatted_results = []
            for item in raw_results:
                artist_info = item.get("artist", {})
                album_info = item.get("album", {})
                formatted_results.append({
                    "title": item.get("title", ""),
                    "artist": artist_info.get("name", ""),
                    "album": album_info.get("title", ""),
                    "duration_seconds": item.get("duration", 0),
                    "preview_url": item.get("preview", ""),
                    "deezer_id": item.get("id", None)
                })
            
            return {
                "success": True,
                "query": query,
                "total": data.get("total", len(formatted_results)),
                "results": formatted_results
            }
        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Request timed out while fetching suggestions. Please try again.",
                "query": query
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP error {e.response.status_code} while fetching suggestions.",
                "query": query
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "query": query
            }




_SERVER_SLUG = "ntag-lyrics-ovh"

def _track(tool_name: str, ua: str = ""):
    try:
        import urllib.request, json as _json
        data = _json.dumps({"slug": _SERVER_SLUG, "event": "tool_call", "tool": tool_name, "user_agent": ua}).encode()
        req = urllib.request.Request("https://www.volspan.dev/api/analytics/event", data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass

async def health(request):
    return JSONResponse({"status": "ok", "server": mcp.name})

async def tools(request):
    registered = await mcp.list_tools()
    tool_list = [{"name": t.name, "description": t.description or ""} for t in registered]
    return JSONResponse({"tools": tool_list, "count": len(tool_list)})

sse_app = mcp.http_app(transport="sse")

app = Starlette(
    routes=[
        Route("/health", health),
        Route("/tools", tools),
        Mount("/", sse_app),
    ],
    lifespan=sse_app.lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
