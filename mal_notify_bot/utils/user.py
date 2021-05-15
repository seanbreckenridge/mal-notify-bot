import time
import asyncio

import jikanpy
import requests
import backoff  # type: ignore[import]

from typing import Dict, Any, Iterator, List

from . import fibo_long, log

j = jikanpy.Jikan("http://localhost:8000/v3/")


@backoff.on_exception(
    fibo_long,  # fibonacci sequence backoff
    (jikanpy.exceptions.JikanException, jikanpy.exceptions.APIException),
    max_tries=3,
    on_backoff=lambda x: print("backing off"),
)
def get_page(username: str, page: int) -> Dict[str, Any]:
    # this does block the main thread for 10 seconds at a time, but
    # thats probably okay, not a ton of requests get sent to this
    # bot that arent background tasks
    # the above iterator in main.py that iterates over the results
    # of download_users_list does an await asyncio.sleep to allow
    # other tasks to run if they exist
    time.sleep(10)
    return j.user(username, "animelist", argument="all", page=page)


def download_users_list(username: str) -> Iterator[List[Dict[str, Any]]]:
    if (
        requests.get("https://myanimelist.net/profile/{}".format(username)).status_code
        == 404
    ):
        raise RuntimeError("Could not find a user with that username.")
    entry_count = 1
    page_number = 1
    while entry_count > 0:
        resp = get_page(username, page_number)
        entry_count = len(resp["anime"])
        yield resp["anime"]
        page_number += 1
