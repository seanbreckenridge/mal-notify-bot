# mal-notify-bot

A discord bot that checks the [Just Added](https://myanimelist.net/anime.php?o=9&c%5B0%5D=a&c%5B1%5D=d&cv=2&w=1) page on [MAL](https://myanimelist.net/), reporting any newly approved entries.

<img src="https://i.imgur.com/pEVk0iw.png" alt="" width=400>

#### Join:

You can join the discord server this is run on [here](https://goo.gl/ciydwZ). If that link doesn't work, scroll down to the bottom of your servers, hit "Add a Server" > "Join a server" and type in `ajABjeN`.

#### Install:

The code is generally up here as reference, I don't see a major reason why one would want to host their own instance of this bot. You can just join the public server above, I maintain the bot there.

Nevertheless, to create your own instance of the bot, create a server which has two channels named `feed` and `nsfw-feed`, [add the bot to it](https://github.com/reactiflux/discord-irc/wiki/Creating-a-discord-bot-&-getting-a-token), and then:

```
git clone https://github.com/seanbreckenridge/mal-notify-bot
cd mal-notify-bot
python3 -m pip install pipenv  # if you don't have pipenv already
pipenv install
pipenv shell
git clone https://github.com/seanbreckenridge/mal-id-cache
touch token.yaml
```

This uses a file in this directory called `old` which caches the already printed entries; if one was to start this on a new server, it would send every entry since it hasn't sent any yet (it doesn't know which ones are 'new'). You can use my [`mal-id-cache`](https://github.com/seanbreckenridge/mal-id-cache) repository as a base, by reading in the SFW/NSFW IDs for anime, and saving those to a file named `old`. The format is just a text file, with one entry per line.

Could create the initial 'old' file by running:

`curl -s 'https://raw.githubusercontent.com/seanbreckenridge/mal-id-cache/master/cache/anime_cache.json' | jq -r '.sfw + .nsfw | .[]' >'old'`

put your bots token in `token.yaml` with contents like:

`token: !!str EU*#3eiSzEr7i4L36FaTlrV0*RtuGOBVNrcteyrtt$GPAwNtkJKQg*dweSLy`

#### Run:

`python3 bot.py`

This is run on `python 3.10.2`. You can use [pyenv](https://github.com/pyenv/pyenv) to install another version of python if needed.
