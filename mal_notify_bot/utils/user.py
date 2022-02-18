import os

from typing import Dict, Any, Iterator, List

from malexport.exporter.account import Account
from malexport.exporter.mal_session import MalSession
from malexport.exporter.api_list import BASE_URL

acc = Account.from_username(os.environ.get("MAL_USERNAME", "purplepinapples"))
acc.mal_api_authenticate()
session = acc.mal_session


def first_page(username: str) -> str:
    return BASE_URL.format(list_type="anime", username=username)


def download_users_list(username: str) -> Iterator[Dict[str, Any]]:
    for resp in session.paginate_all_data(first_page(username)):
        for entry in resp:
            yield entry["node"]
