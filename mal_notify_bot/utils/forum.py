import re
import asyncio

from typing import List, Optional, Dict, Any

import requests
import jikanpy
from jikanpy.exceptions import JikanException, APIException
import backoff  # type: ignore[import]
from discord.ext.commands import Context  # type: ignore[import]

from bs4 import BeautifulSoup  # type: ignore[import]

from . import fibo_long, log


j = jikanpy.Jikan("http://localhost:8000/v3/")


@backoff.on_exception(
    fibo_long,  # fibonacci sequence backoff
    (JikanException, APIException),
    max_tries=3,
    on_backoff=lambda _: print("backing off"),
)
@log
async def get_forum_resp(mal_id: int) -> Dict[str, Any]:
    await asyncio.sleep(4)
    resp: Dict[str, Any] = j.anime(mal_id, extension="forum")
    return resp


# match any forum posts whose link contains 'substring'
@log
async def get_forum_links(
    mal_id: int, substring: str, ctx: Optional[Context] = None
) -> str:
    if ctx:
        await ctx.channel.send("Requesting MAL forum pages...")
    resp = await get_forum_resp(mal_id)
    urls: List[str] = [blob["url"] for blob in resp["topics"]]
    if len(urls) == 0:
        raise RuntimeError("Could not find any forum links for that MAL page...")
    for url in urls:
        if ctx:
            await ctx.channel.send("Searching <{}> for '{}'...".format(url, substring))
        await asyncio.sleep(4)
        resp = requests.get(url)
        if resp.status_code != 200:
            raise RuntimeError(
                "Error requesting <{}>, try again in a few moments".format(url)
            )
        soup = BeautifulSoup(resp.text, "html.parser")
        for (selector, attr) in (("iframe", "src"), ("a", "href")):
            for link in soup.find_all(selector):
                if attr in link.attrs:
                    if bool(re.search(substring, link.attrs[attr])):
                        return link.attrs[attr]
    raise RuntimeError("Could not find any links that match '{}'".format(substring))
