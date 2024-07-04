# RankCheckerBot
Code of my Discord Bot for checking Webnovel.com ranking data
To be able to use this, you'd need the following variables in a `.env` file:
```python
CSRFTOKEN = *SOME VALUE*
TOKEN = *SOME VALUE*
AI_ID = *SOME VALUE*
OWNER_ID = *SOME VALUE*
SERVER_ID = *SOME VALUE*
```

Just replace the `*SOME VALUE*` part with the details that can be gathered as instructed below.

 - `CSRFTOKEN` : You can get it by visiting Webnovel.com while pressing F12 (turning on Developer Tools on Chrome), and check the `Fetch/XHR` tab. You should see it there.

 - `TOKEN` : This is the Discord Bot Token. If you don't know how to get one, follow the instructions on creating a bot (https://discordpy.readthedocs.io/en/stable/discord.html).

 - `AI_ID` : Same with above, this is unique to your AI. You can get it after inviting your bot to a server and have `Developer Mode` activated (Under the Advanced Tab of your settings). Just right click over the bot and select `Copy User ID`.

 - `OWNER_ID` : Again, this can be found on Discord, after activating developer mode. Right click your name and select `Copy User ID`.

 - `SERVER_ID` : This can be gathered with the same steps above, but instead by right-clicking on your server and selecting `Copy Server ID`.

As soon as you made the file, you should be able to run your bot copy... unless there's an error (haven't checked yet).
