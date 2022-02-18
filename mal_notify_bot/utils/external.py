import asyncio
from typing import Optional, Dict, Any

import backoff
import jikanpy
from jikanpy.exceptions import JikanException, APIException

from . import fibo_long, log


j = jikanpy.Jikan("http://localhost:8000/v3/")


@backoff.on_exception(
    fibo_long,  # fibonacci sequence backoff
    (JikanException, APIException),
    max_tries=3,
    on_backoff=lambda _: print("backing off"),
)
@log
async def get_official_link(mal_id: int) -> Optional[str]:
    await asyncio.sleep(4)
    resp: Dict[str, Any] = j.anime(mal_id)
    if "external_links" in resp:
        for blob in resp["external_links"]:
            if blob["name"] == "Official Site":
                return blob["url"]
    return None
