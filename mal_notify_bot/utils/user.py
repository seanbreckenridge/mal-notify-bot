import asyncio

import jikanpy
import requests
import backoff  # type: ignore[import]

from typing import Dict, Any, Iterator, AsyncGenerator

from . import fibo_long, log

j = jikanpy.AioJikan("http://localhost:8000/v3/")


@backoff.on_exception(
    fibo_long,  # fibonacci sequence backoff
    (jikanpy.exceptions.JikanException, jikanpy.exceptions.APIException),
    max_tries=3,
    on_backoff=lambda x: print("backing off"),
)
@log
async def get_page(username: str, page: int) -> Dict[str, Any]:
    await asyncio.sleep(10)
    return await j.user(username, "animelist", argument="all", page=page)


@log
async def download_users_list(username: str) -> AsyncGenerator[Dict[str, Any], None]:
    if (
        requests.get("https://myanimelist.net/profile/{}".format(username)).status_code
        == 404
    ):
        raise RuntimeError("Could not find a user with that username.")
    entry_count = 1
    page_number = 1
    while entry_count > 0:
        resp = await get_page(username, page_number)
        entry_count = len(resp["anime"])
        yield resp["anime"]
        page_number += 1
