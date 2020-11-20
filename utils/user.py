import time

import jikanpy
import requests
import backoff

from . import fibo_long

j = jikanpy.Jikan("http://localhost:8000/v3/")


@backoff.on_exception(
    fibo_long,  # fibonacci sequence backoff
    (jikanpy.exceptions.JikanException, jikanpy.exceptions.APIException),
    max_tries=3,
    on_backoff=lambda x: print("backing off"),
)
def get_page(username, page):
    time.sleep(10)
    return j.user(username, "animelist", argument="all", page=page)


def download_users_list(username):
    if (
        requests.get("https://myanimelist.net/profile/{}".format(username)).status_code
        == 404
    ):
        raise RuntimeError("Could not find a user with that username.")
    entry_count = 1
    page_number = 1
    all_ids = []
    while entry_count > 0:
        resp = get_page(username, page_number)
        entry_count = len(resp["anime"])
        yield resp["anime"]
        page_number += 1


if __name__ == "__main__":
    import sys

    username = sys.argv[1]
    for entries in download_users_list(username):
        print(entries)
