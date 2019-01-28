Download audo and video files with an XMPP interface.

This bot has two main modes of operation:
1. Send the bot an Youtube link, it downloads the video to a pre-set directory on your server. Add videos to your collection on the go.
2. Send the bot an Youtube link, it extracts audio and sends you an MP3 file via XMPP (HTTP upload). Fetch MP3 files to your mobile even when Newpipe fails you.

# Installing

1. Install: xmpppy, requests and youtube-dl.

        sudo apt install python-xmpp python-requests python-pip
        sudo pip install youtube-dl

2. Create an XMPP account for your bot. Use a server which supports XEP-0363 HTTP Upload. Consult https://compliance.conversations.im/

3. Copy `settings.py-example` to `settings.py` and edit the file.

4. Run the script

       python bot.py

5. Set up a cron job to update youtube-dl

       43 7 * * * pip install --upgrade youtube-dl

6. Optionally: make it run on startup. Systemd file is attached, for other process supervisor systems: PRs welcome.

# Usage

Log into your XMPP bot's account and add your main account to the roster. Only people from the roster are allowed to use the bot.

Send the bot a link from your XMPP client. The bot supports an impressive number of video hosting websites via youtube-dl: https://rg3.github.io/youtube-dl/supportedsites.html

# Known issues

It's single threaded. Downloading more than one video at once will cause unpredictable effects. 

# Author

[website](https://gdr.geekhood.net/gdrwpl/) [twitter](https://twitter.com/therealgdr)
