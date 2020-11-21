import time
import re

from typing import List

import requests
import jikanpy
import backoff

from bs4 import BeautifulSoup

from . import fibo_long


j = jikanpy.Jikan("http://localhost:8000/v3/")


@backoff.on_exception(
    fibo_long,  # fibonacci sequence backoff
    (jikanpy.exceptions.JikanException, jikanpy.exceptions.APIException),
    max_tries=3,
    on_backoff=lambda x: print("backing off"),
)
def get_forum_resp(mal_id: int):
    time.sleep(5)
    return j.anime(mal_id, extension="forum")


# match any forum posts whose link contains 'substring'
async def get_forum_links(mal_id: int, substring: str, ctx=None):
    if ctx:
        await ctx.channel.send("Requesting MAL forum pages...")
    urls: List[str] = [blob["url"] for blob in get_forum_resp(mal_id)["topics"]]
    if len(urls) == 0:
        raise RuntimeError("Could not find any forum links for that MAL page...")
    for url in urls:
        if ctx:
            await ctx.channel.send("Searching <{}> for '{}'...".format(url, substring))
        time.sleep(5)
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
