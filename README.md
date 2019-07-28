# mal-notify-bot

A discord bot that checks the [Just Added](https://myanimelist.net/anime.php?o=9&c%5B0%5D=a&c%5B1%5D=d&cv=2&w=1) page on [MAL](https://myanimelist.net/), reporting any newly approved entries.

<img src="https://i.imgur.com/pEVk0iw.png" alt="" width=400>

You can join the discord server this is run on [here](https://goo.gl/ciydwZ). If that link doesn't work, scroll down to the bottom of your servers, hit "Add a Server" > "Join a server" and type in `ajABjeN`.

Install:

```
https://github.com/seanbreckenridge/mal-notify-bot
cd mal-notify-bot
pipenv install
git clone https://github.com/seanbreckenridge/mal-id-cache
```

put your bots token in a file named `token.yaml` in `mal-notify-bot` with contents like:

`token: !!str EU*#3eiSzEr7i4L36FaTlrV0*RtuGOBVNrcteyrtt$GPAwNtkJKQg*dweSLy`

This uses a local [jikan](https://github.com/jikan-me/jikan-rest) instance hosted on port 8000.

`python3 bot.py` to start

This is run on `python 3.6`. You can use [pyenv](https://github.com/pyenv/pyenv) to install another version of python if needed.

Note: the names of the channels where `bot.py` posts new links are hard coded, as `feed` and `nsfw-feed`, you can change those in `on_ready` in `bot.py`
