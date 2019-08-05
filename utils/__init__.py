import sys
import os
import re
import pickle
import logging

class uuid:
    """Represents function calls as processes so its easier to track where/when they start/end"""
    _id = 0

    @staticmethod
    def get():
        return uuid._id

    @staticmethod
    def get_and_increment():
        uuid._id += 1
        return uuid._id

# provide stream = None to not print to stdout/stderr
def setup_logger(name, logfile_name, supress_stream_output=False):
    # setup logs directory
    logs_dir = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)), "logs")
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    logger = logging.getLogger(name)
    LOGLEVEL = os.environ.get("LOGLEVEL", "DEBUG")
    logger.setLevel(LOGLEVEL)
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s/%(filename)s %(funcName)s - %(message)s')
    fh = logging.FileHandler(os.path.join(logs_dir, logfile_name + ".log"))
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    if not supress_stream_output:
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        logger.addHandler(sh)
    return logger


def extract_mal_id_from_url(url) -> str:
    """
    >>> extract_mal_id_from_url("https://myanimelist.net/anime/5")
    '5'
    """
    result = re.findall("https:\/\/myanimelist\.net\/anime\/(\d+)", url)
    if not result: # no regex matches
        return None
    else:
        return result[0]


def remove_discord_link_supression(link):
    link = link.strip()
    if link.startswith("<") and link.endswith(">"):
        link = link[1:-1]
    return link
