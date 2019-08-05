# mal-notify-bot

A discord bot that checks the [Just Added](https://myanimelist.net/anime.php?o=9&c%5B0%5D=a&c%5B1%5D=d&cv=2&w=1) page on [MAL](https://myanimelist.net/), reporting any newly approved entries.

<img src="https://i.imgur.com/pEVk0iw.png" alt="" width=400>

#### Join:

You can join the discord server this is run on [here](https://goo.gl/ciydwZ). If that link doesn't work, scroll down to the bottom of your servers, hit "Add a Server" > "Join a server" and type in `ajABjeN`.

#### Install:

To create your own instance of the bot, create a server which has two channels named `feed` and `nsfw_feed`, [add the bot to it](https://github.com/reactiflux/discord-irc/wiki/Creating-a-discord-bot-&-getting-a-token), and then:

```
git clone https://github.com/seanbreckenridge/mal-notify-bot
cd mal-notify-bot
python3 -m pip install pipenv  # if you don't have pipenv already
pipenv install
pipenv shell
git clone https://github.com/seanbreckenridge/mal-id-cache
touch token.yaml
```

put your bots token in `token.yaml` with contents like:

`token: !!str EU*#3eiSzEr7i4L36FaTlrV0*RtuGOBVNrcteyrtt$GPAwNtkJKQg*dweSLy`

This uses a local [jikan-rest](https://github.com/jikan-me/jikan-rest) instance hosted on port 8000, see [here](https://github.com/jikan-me/jikan-rest#01-prerequisites) for installation instructions

#### Run:

`python3 bot.py`. Theres also a [wrapper script](./run) that restarts incase of network failure/exceptions, but the [`reconnect` flag on client.run](https://github.com/seanbreckenridge/mal-notify-bot/blob/22de12168c7970bb0dc6ca2aaf17db4a80cb6b3c/bot.py#L449) should handle that.

This is run on `python 3.6`. You can use [pyenv](https://github.com/pyenv/pyenv) to install another version of python if needed.
