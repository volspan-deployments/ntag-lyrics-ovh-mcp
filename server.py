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
    Use this when the user wants to read, display, or analyze the lyrics of a known song.
    Returns the complete lyrics text or an error if not found.
    Lyrics are sourced from multiple providers (Genius, AZLyrics, etc.) in parallel.
    """
    url = f"{BASE_URL}/v1/{httpx.URL(artist).path}/{httpx.URL(title).path}"
    # Build URL manually with proper encoding
    encoded_artist = httpx.URL("").copy_with(path=artist)
    encoded_title = httpx.URL("").copy_with(path=title)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{BASE_URL}/v1/{artist}/{title}",
                follow_redirects=True
            )
            if response.status_code == 404:
                return {
                    "success": False,
                    "error": "No lyrics found for this song.",
                    "artist": artist,
                    "title": title
                }
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"API returned status {response.status_code}",
                    "artist": artist,
                    "title": title
                }
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
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Request failed: {str(e)}",
                "artist": artist,
                "title": title
            }


@mcp.tool()
async def suggest_songs(query: str, limit: int = 5) -> dict:
    """Search for songs and artists matching a free-text search term using the Deezer search backend.
    Use this when the user wants to discover songs, find the correct spelling of an artist or title,
    or browse results before fetching specific lyrics.
    Returns a list of matching tracks with artist and title information.
    """
    if limit < 1:
        limit = 1
    if limit > 25:
        limit = 25

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{BASE_URL}/suggest/{query}",
                follow_redirects=True
            )
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"API returned status {response.status_code}",
                    "query": query,
                    "results": []
                }
            data = response.json()
            if "error" in data:
                return {
                    "success": False,
                    "error": data["error"],
                    "query": query,
                    "results": []
                }

            raw_results = data.get("data", [])
            seen = set()
            results = []
            for item in raw_results:
                if len(results) >= limit:
                    break
                artist_name = item.get("artist", {}).get("name", "Unknown")
                song_title = item.get("title", "Unknown")
                key = f"{song_title} - {artist_name}"
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "artist": artist_name,
                    "title": song_title,
                    "album": item.get("album", {}).get("title", ""),
                    "duration_seconds": item.get("duration", 0),
                    "preview_url": item.get("preview", "")
                })

            return {
                "success": True,
                "query": query,
                "total_found": data.get("total", len(raw_results)),
                "returned": len(results),
                "results": results
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Request failed: {str(e)}",
                "query": query,
                "results": []
            }


@mcp.tool()
async def search_and_get_lyrics(query: str) -> dict:
    """Convenience tool that combines suggest_songs and get_lyrics in a single step.
    Use this when the user gives a vague or partial song reference and you need to first
    resolve the correct artist/title before fetching lyrics.
    Searches for the best matching song then immediately retrieves its lyrics.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Search for suggestions
        try:
            suggest_response = await client.get(
                f"{BASE_URL}/suggest/{query}",
                follow_redirects=True
            )
            if suggest_response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Suggestion API returned status {suggest_response.status_code}",
                    "query": query
                }
            suggest_data = suggest_response.json()
            raw_results = suggest_data.get("data", [])
            if not raw_results:
                return {
                    "success": False,
                    "error": "No songs found matching your query.",
                    "query": query
                }

            # Pick the first (best) result
            best = raw_results[0]
            artist_name = best.get("artist", {}).get("name", "")
            song_title = best.get("title", "")

            if not artist_name or not song_title:
                return {
                    "success": False,
                    "error": "Could not extract artist/title from search results.",
                    "query": query
                }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Suggestion request failed: {str(e)}",
                "query": query
            }

        # Step 2: Fetch lyrics for the best match
        try:
            lyrics_response = await client.get(
                f"{BASE_URL}/v1/{artist_name}/{song_title}",
                follow_redirects=True
            )
            if lyrics_response.status_code == 404:
                return {
                    "success": False,
                    "error": "Song was found in search but lyrics are not available.",
                    "query": query,
                    "artist": artist_name,
                    "title": song_title
                }
            if lyrics_response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Lyrics API returned status {lyrics_response.status_code}",
                    "query": query,
                    "artist": artist_name,
                    "title": song_title
                }
            lyrics_data = lyrics_response.json()
            if "error" in lyrics_data:
                return {
                    "success": False,
                    "error": lyrics_data["error"],
                    "query": query,
                    "artist": artist_name,
                    "title": song_title
                }
            return {
                "success": True,
                "query": query,
                "artist": artist_name,
                "title": song_title,
                "album": best.get("album", {}).get("title", ""),
                "lyrics": lyrics_data.get("lyrics", "")
            }
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Lyrics request failed: {str(e)}",
                "query": query,
                "artist": artist_name,
                "title": song_title
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
