import sys
import os
import re
import pickle
import logging

class uuid:
    """Represents function calls as processes so its easier to track where/when they start/end"""
    id = 0

    @staticmethod
    def get():
        return id

    @staticmethod
    def get_and_increment():
        id += 1
        return id

# provide stream = None to not print to stdout/stderr
def setup_logger(name, logfile_name, *, stream=sys.stderr):
    # setup logs directory
    logs_dir = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)), "logs")
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    logger = logging.getLogger(name)
    LOGLEVEL = os.environ.get("LOGLEVEL", "INFO")
    logger.setLevel(LOGLEVEL)
    formatter = logging.Formatter("%(asctime)s %(levelno)s %(process)d %(message)s")
    fh = logging.FileHandler(os.path.join(logs_dir, logfile_name + ".log"))
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    if stream is not None:
        sh = logging.StreamHandler(stream)
        logger.addHandler(sh)
    return logger


def extract_mal_id_from_url(url) -> str:
    result = re.findall("https:\/\/myanimelist\.net\/anime\/(\d+)", "https://myanimelist.net/anime/1")
    if not result: # no regex matches
        return None
    else:
        return result[0]

def remove_discord_link_supression(link):
    link = link.strip()
    if link.startswith("<") and link.endswith(">"):
        link = link[1:-1]
    return link
