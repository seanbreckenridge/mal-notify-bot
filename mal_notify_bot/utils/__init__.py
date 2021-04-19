import re
import inspect

from functools import wraps

from typing import Optional, Iterator, Any

from logzero import logger  # type: ignore[import]
import backoff  # type: ignore[import]


class uuid:
    """Represents function calls as processes so its easier to track where/when they start/end"""

    _id: int = 0

    @staticmethod
    def get() -> int:
        return uuid._id

    @staticmethod
    def get_and_increment() -> int:
        uuid._id += 1
        return uuid._id


def extract_mal_id_from_url(url: str) -> Optional[str]:
    """
    >>> extract_mal_id_from_url("https://myanimelist.net/anime/5")
    '5'
    """
    result = re.findall("https:\/\/myanimelist\.net\/anime\/(\d+)", url)
    if not result:  # no regex matches
        return None
    else:
        return str(result[0])


def remove_discord_link_supression(link: str) -> str:
    link = link.strip()
    if link.startswith("<") and link.endswith(">"):
        link = link[1:-1]
    return link


def fibo_long() -> Iterator[int]:
    f = backoff.fibo()
    for _ in range(4):
        next(f)
    yield from f


def truncate(obj: Any, limit: int) -> str:
    """Truncates the length of args/kwargs for the @log decorator so that we can read logs easier"""
    if len(repr(obj)) < limit:
        return repr(obj)
    else:
        return repr(obj)[:limit] + "... (truncated)"


def log(func):
    """Decorator for functions, to log start/end times"""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        _id = uuid.get_and_increment()
        args_text = truncate(args, 2000)
        kwargs_text = truncate(kwargs, 2000)
        logger.debug(f"{func.__name__} ({_id}) called with {args_text} {kwargs_text}")
        if inspect.iscoroutinefunction(func):
            result = await func(*args, **kwargs)
        else:
            result = func(*args, **kwargs)
        logger.debug(f"{func.__name__} ({_id}) finished")
        return result

    return wrapper
