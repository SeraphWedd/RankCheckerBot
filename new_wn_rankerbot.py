import os
import sys
import time
import json
import pickle
import string
import shutil
import random
import asyncio
import datetime
import requests

import discord
from discord import app_commands
from discord.ext import tasks

from dotenv import load_dotenv

load_dotenv()

#Constants to be used by the bot
rankNames = {
        "best_sellers":"Trending",
        "power_rank":"Power",
        "collection_rank":"Collect",
        "popular_rank":"Popular",
        "update_rank":"Update",
        "engagement_rank":"Active",
        "fandom_rank":"Fandom",
    }
category_list = ['power_rank', 'best_sellers', 'collection_rank', 'popular_rank', 'update_rank', 'engagement_rank', 'fandom_rank']
rank_id_list = {
    '5':'monthly',
    '4':'season',
    '3':'bi_annual',
    '2':'annual',
    '0':'all_time'
}

TR = {'5':'24h',
      '3':'weekly',
      '4':'monthly',
      '1':'overall'
      }
SC = {'0':'all',
      '1':'translate',
      '2':'original'
      }
SX = {'1':'male',
      '2':'female'
      }
SG = {'1':'Contracted',
      '0':'all'
      }

def build_key(category, time_type, time_range, content, contract, sex):
    #Used as key for update tracker and database
    return f"{category}-{time_type}-{time_range}-{content}-{contract}-{sex}"

#Global variables
DATABASE = {}
LAST_UPDATE = {} #key:val == build_key:timestamp of last update
TRACKING_LIST = [] #(timestamp, build_key, interval, [title, channel, name, avatar])
BIRTHDAY_LIST = {} #Birthdays grouped per guild, (mm, dd, yyyy, name, id, channel)
CSRFTOKEN = os.getenv("CSRFTOKEN")
UPDATE_DELAY = 1800
ALL_TITLES = set()

#Load saved data
try:
    with open('RANKING_DATA.json', 'r') as f:
        DATABASE = json.load(f)
except:
    with open('RANKING_DATA.json', 'w') as f:
        json.dump(DATABASE, f)

try:
    with open('tracking_list_backup.pkl', 'rb') as f:
        TRACKING_LIST = pickle.load(f)
        print(datetime.datetime.now(), "Loaded tracking list from backup!")
except:
    print(datetime.datetime.now(), "No tracking list backup!")

try:
    with open('last_update_times.pkl', 'rb') as f:
        LAST_UPDATE = pickle.load(f)
        print(datetime.datetime.now(), "Loaded last update times from backup!")
except:
    print(datetime.datetime.now(), "No last update times backup!")

try:
    with open('birthday_tracker.json', 'r') as f:
        BIRTHDAY_LIST = json.load(f)
        print(datetime.datetime.now(), "Loaded birthday list from backup!")
except:
    print(datetime.datetime.now(), "No birthday list backup!")


async def update_data_and_update_time():
    print("Updating both data and last update time...", end=' ')
    with open('RANKING_DATA.json', 'w') as f:
        json.dump(DATABASE, f)
        
    with open('last_update_times.pkl', 'wb') as f:
        pickle.dump(LAST_UPDATE, f)
    print("Done!")
    

async def refresh_names():
    #Try to initialize ALL_TITLES
    for k, v in DATABASE.items():
        for _, _, _, n, _ in v:
            ALL_TITLES.add(n)

#Initial Setup
TOKEN = os.getenv('TOKEN')
intents = discord.Intents.default()
intents.message_content = True
AI_ID = int(os.getenv("AI_ID"))
OWNER_ID = int(os.getenv("OWNER_ID"))
SERVER_ID = int(os.getenv("SERVER_ID"))

client=discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

#------------------------------------------------------------------------------
@client.event
async def on_ready():
    print(datetime.datetime.now(), "Connected to Discord!")
    check_update_queue.start()
    await asyncio.sleep(1)
    create_backup_data.start()
    await asyncio.sleep(1)
    check_birthdays.start()
    await asyncio.sleep(1)
    await refresh_names()


#------------------------------------------------------------------------------
@tasks.loop(seconds=3600)
async def create_backup_data():
    curr = datetime.datetime.now()
    h, m, s = map(int, curr.strftime("%H:%M:%S").split(':'))
    
    if (h == 23 or h == 0):
        print(datetime.datetime.now(), 'Creating backup...', end='')
        fn = str(curr).split()[0]
        shutil.copy('ranking_data.json', f'Backup/{fn}.json')
        print('done!')

        
#------------------------------------------------------------------------------
@tasks.loop(seconds=60)
async def check_update_queue():
    global TRACKING_LIST
    print(datetime.datetime.now(),
          "Timed task running!",
          "No. of tasks:", len(TRACKING_LIST),
          "    | No. of guilds:", len(client.guilds)
    )
    queue = sorted(TRACKING_LIST)
    checked = []
    current = time.time()
    #Iterate over the list
    for timestamp, key, delay, values in queue:
        #Check if item is past its next update time
        category, time_type, time_range, source, contract, sex = key.split('-')
        title, channel, name, avatar = values
        channel = await client.fetch_channel(channel)
        if timestamp <= current:
            #check if last update time is within the past n-seconds
            #check if LAST_UPDATE[key] exists
            if not LAST_UPDATE.get(key, None):
                LAST_UPDATE[key] = 0
                
            if current - LAST_UPDATE[key] > UPDATE_DELAY:
                #If the last update is outdated, gather new data
                data = get_data(
                    category, time_type, time_range, source, contract, sex, CSRFTOKEN
                )
                if data is not None:
                    DATABASE[key] = data

                await refresh_names()

                #update LAST_UPDATE
                LAST_UPDATE[key] = current
                
                await update_data_and_update_time()

            #build the embed
            rank, cover_link, n_title = await iterate_over_database(
                category, title, key
            )
            if n_title is not None:
                title = n_title
            
            try:
                emb, st = build_rank_embed(
                    category, title, rank, cover_link, name, avatar
                )
                if st:
                    await channel.send(embed=emb)
                else:
                    await channel.send(embed=emb, delete_after=3600)
                
            except Exception as e:
                print("Cannot send to channel!")
                print("Error!", e)

            #update timestamp until it's over the current time
            while timestamp < current:
                timestamp += delay

            checked.append((timestamp, key, delay, values))
            
        else:
            checked.append((timestamp, key, delay, values))

        TRACKING_LIST = checked.copy()

        with open('tracking_list_backup.pkl', 'wb') as f:
            pickle.dump(TRACKING_LIST, f)


#------------------------------------------------------------------------------
async def title_autocomplete(
    interaction: discord.Interaction,
    current: str,
):
    titles = sorted(ALL_TITLES)
    return [
        discord.app_commands.Choice(name=t, value=t)
        for t in titles if current.lower() in t.lower()
    ]


#------------------------------------------------------------------------------
@tree.command(
    name='resync',
    description='Owner Only',
)
async def resync(interaction: discord.Interaction):
    if interaction.user.id == OWNER_ID:
        #tree.copy_global_to(guild=interaction.guild)
        #cnt = await tree.sync(guild=interaction.guild)
        cnt = await tree.sync()
        print(datetime.datetime.now(), f"Command tree synced {len(cnt)} commands!")
        await interaction.response.send_message(
            f"Command tree synced {len(cnt)} commands!",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            'You must be the owner to use this command!',
            ephemeral=True,
        )

        
#------------------------------------------------------------------------------
@tree.command(
    name='get_all_guilds',
    description='Owner Only',
)
async def get_all_guilds(interaction: discord.Interaction):
    if interaction.user.id == OWNER_ID:
        msg = []
        for guild in client.guilds:
            msg.append(f'id_"{guild.id}" :name_"{guild.name}"')
        msg = '\n'.join(msg)
        await interaction.response.send_message(
            msg, ephemeral=True,
            )
    else:
        await interaction.response.send_message(
            'You must be the owner to use this command!',
            ephemeral=True,
        )


#------------------------------------------------------------------------------
@tree.command(
    name='ghost_ping_all_channels',
    description='Owner Only',
)
async def ghost_ping_all_channels(interaction: discord.Interaction):
    if interaction.user.id == OWNER_ID:
        ch = []
        guild = await client.get_guild(interaction.guild_id)
        for channel in guild.channels:
            if str(channel.type) == 'text':
                ch.append(channel.id)
        
        await interaction.response.send_message(
            "Ghost pinging {len(ch)} channels!", ephemeral=True,
            )

        for c in ch:
            channel = await client.fetch_channel(c)
            allowed_mentions = discord.AllowedMentions(everyone=True)
            await channel.send(
                "@silent Keeping the channel alive!",
                allowed_mentions=allowed_mentions,
                delete_after=10.0
            )
            await asyncio.sleep(2)
    else:
        await interaction.response.send_message(
            'You must be the owner to use this command!'
        )


#------------------------------------------------------------------------------
@tree.command(
    name='help',
    description='Show all commands and their functions.',
)
async def help(interaction: discord.Interaction):
    help_str = '''
This is a [Webnovel](https://www.webnovel.com/) Ranking Getter/Tracker Bot.

This bot is created and run by [SeraphWedd](https://www.webnovel.com/profile/4300026489).
The current version is being run in a local computer, so it's far from being set for wide range implementation. **Please don't spread the bot to just anyone!**

If you want to give support, then I need someone who can teach me how to fetch data from rankings faster than my method (my implementation takes 30 mins to gleam data from all ranking boards). Or maybe support my novels.

Below are this bot's commands:

**get_rank(category, book_title)**
**optional_parameters(time_range, content, contract)**
Fetches the category ranking of a given book title. Using it without filling the optional parameters would return the book's ranking across all boards it could be seen on. I suggest using this first before adding the book to the tracker. ML or FL will automatically be detected.

**track_book(category, book_title, interval_hrs)**
**optional_parameters(time_range, content, contract)**
Adds the book under tracking and would repost the updated rank after every interval_hrs time elapsed. After adding it, the tracker would show run get_rank to check if the book's details were correct. For details of the optional_parameters, if you aren't sure, then just leave it to default.

**remove_from_tracker(category, book_title)**
Removes a book from the tracker. You must use the command on the same channel that the current tracker is posting at, otherwise, it wouldn't be able to remove your book from tracker.

'''
    emb = discord.Embed(
        title=f'WN Ranking Bot Help',
        description=help_str,
        colour=discord.Color.greyple(),
        timestamp=datetime.datetime.now(),
    )
    emb.set_author(
        name=interaction.user.display_name,
        icon_url=interaction.user.display_avatar.url
    )
    await interaction.response.send_message(embed=emb)


#------------------------------------------------------------------------------ 
@tree.command(
    name='track_book',
    description='Tracks the ranking of a book across all boards.',
)
@discord.app_commands.describe(
    category="Select under what ranking category you'll get:",
    book_title='Enter the title of the book. Please be as accurate as possible.',
    interval_hrs='The amount of time before the bot will repost' +\
    ' your current rankings again.',
)
@discord.app_commands.choices(
    category=[
        discord.app_commands.Choice(name='Powerstone', value='power_rank'),
        discord.app_commands.Choice(name='Trending', value='best_sellers'),
        discord.app_commands.Choice(name='Collections', value='collection_rank'),
        discord.app_commands.Choice(name='Popular', value='popular_rank'),
        discord.app_commands.Choice(name='Update', value='update_rank'),
        discord.app_commands.Choice(name='Active', value='engagement_rank'),
        discord.app_commands.Choice(name='Fandom', value='fandom_rank'),
    ],
    time_type=[
        discord.app_commands.Choice(name='Monthly', value='5'),
        discord.app_commands.Choice(name='Season', value='4'),
        discord.app_commands.Choice(name='Bi-Annual', value='3'),
        discord.app_commands.Choice(name='Annual', value='2'),
        discord.app_commands.Choice(name='All Time', value='0'),
    ],
    time_range=[
        discord.app_commands.Choice(name='24h', value='5'),
        discord.app_commands.Choice(name='weekly', value='3'),
        discord.app_commands.Choice(name='monthly', value='4'),
        discord.app_commands.Choice(name='all_time', value='1'),
    ],
    content=[
        discord.app_commands.Choice(name='translated', value='1'),
        discord.app_commands.Choice(name='original', value='2'),
        discord.app_commands.Choice(name='all', value='0'),
    ],
    contract=[
        discord.app_commands.Choice(name='contracted', value='1'),
        discord.app_commands.Choice(name='all', value='0'),
    ],
    sex=[
        discord.app_commands.Choice(name='ML', value='1'),
        discord.app_commands.Choice(name='FL', value='2'),
    ],
)
@discord.app_commands.autocomplete(
    book_title=title_autocomplete
)
async def track_book(
    interaction: discord.Interaction,
    category: str,
    book_title: str,
    interval_hrs: str,
    time_type: str,
    time_range: str,
    content: str,
    contract: str,
    sex: str,
):
    global TRACKING_LIST
    await interaction.response.defer() #wait for bot  to reply without timeout
    
    try: #overall try case
        resp = ''
        #Filter erroneous ranges of values
        try:
            interval_hrs = float(interval_hrs)
            if interval_hrs < 1.0:
                resp += "Minimum time allowed is 1.0 hours, you entered"+\
                        f" {interval_hrs:.1f}! "
                interval_hrs = 1.0
        except:
            resp += "You entered an invalid interval! Defaulting to 1.0 hours! "
            interval_hrs = 1.0

        time_range, time_type = filter_values(category, time_range, time_type)
            

        #Check if not duplicate:
        rem = False
        remo_i = None
        own_key = build_key(category, time_type, time_range, content, contract, sex)
        
        for n, i in enumerate(TRACKING_LIST):
            timestamp, key, delay, values = i
            title, channel, name, avatar = values
            if (category.lower() == key.split('-')[0].lower()) and (
                title.lower() == book_title.lower()) and (
                    interaction.channel.id == channel):
                rem = True
                remo_i = int(n)
                break
        if rem:
            print("Popping!!")
            TRACKING_LIST.pop(remo_i) #Remove old and renew
            
        delay = int(3600*interval_hrs)

        book_title = string.capwords(book_title)
        try:
            await interaction.followup.send(
                resp + f'Tracking the book **"{book_title}"** '+\
                f'under **{category.replace("_", " ").title()}** tab ' +\
                f'every {interval_hrs:.1f} hours!',
            )
            
            TRACKING_LIST.append(
                (time.time(),
                 own_key,
                 delay,
                 [book_title, interaction.channel.id,
                  interaction.user.display_name,
                  interaction.user.display_avatar.url],
                 )
            )
            #check if it's already on the LAST_UPDATE dictionary
            if not LAST_UPDATE.get(own_key, None):
                LAST_UPDATE[own_key] = 0            
                with open('last_update_times.pkl', 'wb') as f:
                    pickle.dump(LAST_UPDATE, f)

            with open('tracking_list_backup.pkl', 'wb') as f:
                pickle.dump(TRACKING_LIST, f)
                
        except:
            print("Cannot track the book! No permission to send message!")
        await check_update_queue() #call upon addition of new task
        
    except Exception as e:
        await interaction.followup.send(
                'Sorry, some error occurred!\n'+str(e)
            )
        
    
#------------------------------------------------------------------------------
@tree.command(
    name='remove_from_tracker',
    description='Removes a book from the ranking tracker.',
)
@discord.app_commands.describe(
    category="Select under what ranking category you'll get:",
    book_title='Enter the title of the book. Please be as accurate as possible.',
)
@discord.app_commands.choices(
    category=[
        discord.app_commands.Choice(name='Powerstone', value='power_rank'),
        discord.app_commands.Choice(name='Trending', value='best_sellers'),
        discord.app_commands.Choice(name='Collections', value='collection_rank'),
        discord.app_commands.Choice(name='Popular', value='popular_rank'),
        discord.app_commands.Choice(name='Update', value='update_rank'),
        discord.app_commands.Choice(name='Active', value='engagement_rank'),
        discord.app_commands.Choice(name='Fandom', value='fandom_rank'),
    ],
)
@discord.app_commands.autocomplete(
    book_title=title_autocomplete
)
async def remove_from_tracker(
    interaction: discord.Interaction,
    category: str,
    book_title: str,
):
    global TRACKING_LIST
    new_tracker = []
    cnt = 0

    for timestamp, key, delay, values in TRACKING_LIST:
        title, channel, name, avatar = values
        cat = key.split('-')[0]
        if (category == cat) and (book_title.lower() == title.lower()) and (interaction.channel.id == channel):
            cnt += 1
        else:
            new_tracker.append((timestamp, key, delay, values))
            
    TRACKING_LIST = new_tracker.copy()
    
    with open('tracking_list_backup.pkl', 'wb') as f:
        pickle.dump(TRACKING_LIST, f)
    
    if cnt:
        msg = f'Successfully removed **{string.capwords(book_title)}** from **{category.capitalize()}** tracker!'
    else:
        msg = f"Book is not being tracked under **{category}**! Please check "+\
              f"the spelling, just in case: **{string.capwords(book_title)}**"

    await interaction.response.send_message(msg)
    
    await check_update_queue() #call upon addition of new task


#------------------------------------------------------------------------------
@tree.command(
    name='admin_check_tracked',
    description='Owner Only',
)
async def admin_check_tracked(
    interaction: discord.Interaction,
):
    global TRACKING_LIST
    msg = 'ID: CATEGORY, TITLE, CHANNEL_ID\n'
    if interaction.user.id == OWNER_ID:
        items = []
        for n, i in enumerate(TRACKING_LIST):
            timestamp, key, delay, values = i
            title, channel, name, avatar = values
            items.append((n, key.split('-')[0], title, channel))
        msg += '\n'.join([f'**Item {n}**: {i} ({j} {k})' for n, i, j, k in items])
        await interaction.response.send_message(msg, ephemeral=True)
    else:
        await interaction.response.send_message(
            'You must be the owner to use this command!',
            ephemeral=True,
        )


#------------------------------------------------------------------------------
@tree.command(
    name='admin_remove_tracked',
    description='Owner Only',
)
async def admin_remove_tracked(
    interaction: discord.Interaction,
    d: str
):
    global TRACKING_LIST
    
    if interaction.user.id == OWNER_ID:
        d = int(d)
        name = TRACKING_LIST[d][3][2]
        category = TRACKING_LIST[d][1].split('-')[0]
        
        new_tracker = [i for n, i in enumerate(TRACKING_LIST) if n != d]
        TRACKING_LIST = new_tracker.copy()
        
        msg = f'Successfully removed **{string.capwords(name)}** from **{category.capitalize()}** tracker!'
        await interaction.response.send_message(msg, ephemeral=True)
        
        await check_update_queue() #call upon addition of new task
    else:
        await interaction.response.send_message(
            'You must be the owner to use this command!',
            ephemeral=True,
        )


#------------------------------------------------------------------------------
@tree.command(
    name='get_rank',
    description='Get the ranking of a book under the given category.',
)
@discord.app_commands.describe(
    category="Select under what ranking category you'll get:",
    book_title='Enter the title of the book. Please be as accurate as possible.',
)
@discord.app_commands.choices(
    category=[
        discord.app_commands.Choice(name='Powerstone', value='power_rank'),
        discord.app_commands.Choice(name='Trending', value='best_sellers'),
        discord.app_commands.Choice(name='Collections', value='collection_rank'),
        discord.app_commands.Choice(name='Popular', value='popular_rank'),
        discord.app_commands.Choice(name='Update', value='update_rank'),
        discord.app_commands.Choice(name='Active', value='engagement_rank'),
        discord.app_commands.Choice(name='Fandom', value='fandom_rank'),
    ],
    time_type=[
        discord.app_commands.Choice(name='Monthly', value='5'),
        discord.app_commands.Choice(name='Season', value='4'),
        discord.app_commands.Choice(name='Bi-Annual', value='3'),
        discord.app_commands.Choice(name='Annual', value='2'),
        discord.app_commands.Choice(name='All Time', value='0'),
    ],
    time_range=[
        discord.app_commands.Choice(name='24h', value='5'),
        discord.app_commands.Choice(name='weekly', value='3'),
        discord.app_commands.Choice(name='monthly', value='4'),
        discord.app_commands.Choice(name='all_time', value='1'),
    ],
    content=[
        discord.app_commands.Choice(name='translated', value='1'),
        discord.app_commands.Choice(name='original', value='2'),
        discord.app_commands.Choice(name='all', value='0'),
    ],
    contract=[
        discord.app_commands.Choice(name='contracted', value='1'),
        discord.app_commands.Choice(name='all', value='0'),
    ],
    sex=[
        discord.app_commands.Choice(name='ML', value='1'),
        discord.app_commands.Choice(name='FL', value='2'),
    ],
)
@discord.app_commands.autocomplete(
    book_title=title_autocomplete
)
async def get_rank(
    interaction: discord.Interaction,
    category: str,
    book_title: str,
    time_type: str,
    time_range: str,
    content: str,
    contract: str,
    sex: str,
):
    await interaction.response.defer()
    try:
        time_range, time_type = filter_values(category, time_range, time_type)
                
        key = build_key(category, time_type, time_range, content, contract, sex)
        rank, cover_link, n_title = await iterate_over_database(
                    category, book_title, key
                )
        
        if n_title is not None:
            book_title = n_title
        
        emb, st = build_rank_embed(
            category,
            book_title,
            rank,
            cover_link,
            interaction.user.display_name,
            interaction.user.display_avatar.url
        )

        await interaction.followup.send(embed=emb)
        
    except Exception as e:
        await interaction.followup.send(
                'Sorry, some error occurred!\n'+str(e),
            )

    
#------------------------------------------------------------------------------
def build_rank_embed(category, book_title, rankings, cover_link, name, url):
    try:
        book_lnk = 'https://www.webnovel.com/book/'+cover_link.split('?')[0].split('/')[-1]
    except:
        book_lnk = 'https://www.webnovel.com/search?keywords=' + "+".join(book_title.lower().split())
    color = {
        'power_rank':discord.Color.red(),
        'best_sellers':discord.Color.blue(),
        'collection_rank':discord.Color.green(),
        'popular_rank':discord.Color.magenta(),
        'update_rank':discord.Color.purple(),
        'engagement_rank':discord.Color.gold(),
        'fandom_rank':discord.Color.orange(),
    }
    emb = discord.Embed(
        title=f"{category.replace('_rank', '').replace('_', ' ').title()} Ranking",
        description=f'**Title: [{book_title}]({book_lnk})**\n' +
        'Below is the ranking of the book:\n',
        colour=color.get(category.lower(), discord.Color.greyple()),
        timestamp=datetime.datetime.now(),
    )
    emb.set_author(
        name=name,
        icon_url=url
    )
    status = False #If the rank is successfully added or not

    if rankings is not None:
        rank, key, value = rankings
        category, time_type, time_range, source, contract, sex = key.split('-')
        time_type = rank_id_list[time_type]
        time_range = TR[time_range]
        source = SC[source]
        contract = SG[contract]
        sex = SX[sex]

        value_str = f'```Rank: {rank}'
        if category == 'best_sellers':
            value_str += '```'
        else:
            value_str += f' | Value: {value}```'
        
        emb.add_field(
            name=f'| Release: {time_type.replace("_", " ").title()} |' +\
            f'Range: {time_range.replace("_", " ").title()} |' +\
            f'Sex: {sex.title()} | ' +\
            f'Content: {source.title()} | ' +\
            f'Status: {contract.title()} |',
            value=value_str,
            inline=False,
        )
        status = True
            
    else:
        emb.add_field(
            name="Book not in any of the rankings!",
            value='Please check the spelling of the book ' +\
            f'title and try again: **{book_title.title()}**' +\
            '\nNote: The title is **not** case sensitive.' +\
            '\nIf title is correct, that means the book is ' +\
            'not in this ranking board currently.',
            inline=False,
        )

    if cover_link:
        emb.set_image(url=cover_link)
        emb.set_thumbnail(url=cover_link)

    return emb, status


#------------------------------------------------------------------------------
async def iterate_over_database(category, title, key):
    if not DATABASE.get(key, None):
        print("Fetching Data for category:", category)
        rankId, listType, timeType, sourceType, signStatus, sex = key.split('-')
        data = get_data(rankId, listType, timeType, sourceType, signStatus, sex)
        if data is not None: DATABASE[key] = data
        await refresh_names()
        LAST_UPDATE[key] = time.time()
        #update Database file
        await update_data_and_update_time()
        
    for rankNo, bookId, updateId, bookName, amount in DATABASE[key]:
        if bookName.lower() == title.lower():
            return (rankNo, key, amount), f'https://book-pic.webnovel.com/bookcover/{bookId}?imageMogr2/thumbnail/150&imageId={updateId}', bookName
    return None, None, None


#------------------------------------------------------------------------------
def get_link(
    csrfToken=CSRFTOKEN, #token used, probably refreshes after certain time passes
    pageIndex=1, #Page index from 1 to 10
    rankId='best_sellers', #Rank ID, specific to rankings
    listType=0, #
    noType=1, #Novel=1, Fanfic=4, or Comic=2
    rankName='Trending', #Rank Name, specific to each RankId
    timeType=3, #24hr=5, weekly=3, monthly=4, all-time=1
    sourceType=2, #all=0, translated=1, original=2
    sex=1, #male=1, female=2
    signStatus=1, #Contracted or not
    ):
    items = [f'pageIndex={pageIndex}', f'rankId={rankId}', f'listType={listType}', f'type={noType}', f'rankName={rankName}',
             f'timeType={timeType}', f'sourceType={sourceType}', f'sex={sex}']
    
    if rankName == 'Power':
        items += [f'signStatus={signStatus}',]
        
    random.shuffle(items)
    base_url = 'https://www.webnovel.com'
    path = f"/go/pcm/category/getRankList?_csrfToken={csrfToken}&" + '&'.join(items)
    url = base_url + path
    headers = get_headers(path)
    return url, headers


#------------------------------------------------------------------------------
def get_headers(path):
    headers = {'authority': 'www.webnovel.com', 'method': 'GET', 'scheme': 'https', 'Accept': 'application/json, text/javascript, */*; q=0.01', 'Accept-Encoding': 'gzip, deflate, br, zstd', 'Accept-Language': 'en-US,en;q=0.9',
               'Cookie': f'webnovel-language=en; webnovel-content-language=en; bookCitysex=1; show_gift_tip=1; para-comment-tip-show=1; show_lib_tip=1; QDReport_utm=utm_source%3DnoahActivity; __zlcmid=1LImeDfz2451vVV; NEXT_LOCALE=en; wn_show_first_charge_modal=; charge_selected_payments=paypal; _csrfToken={CSRFTOKEN}; uid=4300026489; ukey=uXnz1f67uhq; webnovel_uuid=1719526890_1946123745; _fsae=1719580024477; checkInTip=1; e2=%7B%22pid%22%3A%22bookstore%22%2C%22l1%22%3A%2299%22%7D; e1=%7B%22pid%22%3A%22bookstore%22%2C%22l1%22%3A%221%22%2C%22eid%22%3A%22qi_A_home_rankingshoverclick%22%7D',
               'Priority': 'u=1, i', 'Referer': 'https://www.webnovel.com/ranking/novel/all_time/best_sellers', 'Sec-Ch-Ua': '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"', 'Sec-Ch-Ua-Mobile': '?0', 'Sec-Ch-Ua-Platform': '"Windows"', 'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Site': 'same-origin', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36', 'X-Requested-With': 'XMLHttpRequest'}
    headers['path'] = path
    
    return headers


#------------------------------------------------------------------------------
def get_data(rankId, listType, timeType, sourceType, signStatus, sex, csrfToken=CSRFTOKEN, error_count=0):
    print(datetime.datetime.now(), "Getting new data!", rankId, listType,timeType, sourceType, sex, signStatus, "retries:", error_count)
    keep_data = ['rankNo', 'bookId', 'coverUpdateTime', 'bookName', 'amount']
    rankName = rankNames[rankId]
    rank_data = []
    for n in range(1, 11):
        url, headers = get_link(
            csrfToken=csrfToken,
            listType=listType,
            pageIndex=n,
            rankId=rankId,
            rankName=rankName,
            timeType=timeType,
            sourceType=sourceType,
            sex=sex,
            signStatus=signStatus,
        )
        session = requests.Session()
        response = session.get(url, headers=headers)

        if response.status_code == 200:
            try:
                data = response.json()
                #if data is blank, that means ranking list is complete, break immediately
                if not len(data['data']['bookItems']):
                    break
                
                keep = [[i[j] for j in keep_data] for i in data['data']['bookItems']]
                rank_data += keep
            except requests.exceptions.JSONDecodeError as e:
                print("ERROR! Need Verification Captcha!", response)
                raise ValueError("Crawler raised a requests.exceptions.JSONDecodeError with status_code 200 response! Need verification!")
            
        else:
            print(f"Failed to fetch data. Status code: {response.status_code}")
            #retry just in case
            return get_data(rankId, listType, timeType, sourceType,
                            signStatus, sex, csrfToken=csrfToken,
                            error_count=error_count+1)
    return rank_data

def filter_values(category, tr, ty):
    time_range, time_type = tr, ty
    if category == 'best_sellers':
        #should always be contracted
        contract = '1'
        
    elif category == 'power_rank':
        if time_range == '5':
            time_range = '3'
    else:
        time_type='0'
        
        #Only Trending has the Daily ranking range
        if time_range == '5' or ((time_range == '0') and (category in ['update_rank', 'engagement_rank'])):
            time_range = '3'
    return time_range, time_type


#------------------------------------------------------------------------------
@tree.command(
    name='add_birthday',
    description="Tracks member's birthday.",
)
@discord.app_commands.choices(
    month=[
        discord.app_commands.Choice(name='January', value=1),
        discord.app_commands.Choice(name='February', value=2),
        discord.app_commands.Choice(name='March', value=3),
        discord.app_commands.Choice(name='April', value=4),
        discord.app_commands.Choice(name='May', value=5),
        discord.app_commands.Choice(name='June', value=6),
        discord.app_commands.Choice(name='July', value=7),
        discord.app_commands.Choice(name='August', value=8),
        discord.app_commands.Choice(name='September', value=9),
        discord.app_commands.Choice(name='October', value=10),
        discord.app_commands.Choice(name='November', value=11),
        discord.app_commands.Choice(name='December', value=12),

    ],
)
async def add_birthday(
    interaction: discord.Interaction,
    month: int,
    day: int,
    year: int,
    member: discord.Member
):
    try:
        #check if birthday is valid
        bd = datetime.datetime(month=month, day=day, year=year)
    except ValueError as e:
        await interaction.response.send_message(
            "Sorry, you've entered an invalid date! Please double check!" +\
            f"\nmm/dd/yyyy={month}/{day}/{year}",
            ephemeral=True
        )
        return

    guild_id = str(interaction.guild_id)
    #Check if guild already has a list
    if not BIRTHDAY_LIST.get(guild_id, None):
        BIRTHDAY_LIST[guild_id] = []

    #check if name is already in list, if yes, overwrite the id
    exists = False
    q = 0
    for q, (m,d,y,n,i,c) in enumerate(BIRTHDAY_LIST[guild_id]):
        if i==member.id:
            exists = True
            break
        
    if not exists:
        BIRTHDAY_LIST[guild_id].append((
            month, day, year,
            member.name, member.id,
            interaction.channel.id
        ))
    else:
        BIRTHDAY_LIST[guild_id][q] = (
            month, day, year,
            member.name, member.id,
            interaction.channel.id
        )
            
    with open('birthday_tracker.json', 'w') as f:
        json.dump(BIRTHDAY_LIST, f)

    await interaction.response.send_message(
        "Successfully added birthday!" +\
        f"<@{member.id}>'s birthday is set as: **{month}-{day}-{year}**"
    )
    

#------------------------------------------------------------------------------
@tree.command(
    name='view_birthday',
    description="View guild member's birthday.",
)
async def view_birthday(
    interaction: discord.Interaction,
):
    members = BIRTHDAY_LIST.get(str(interaction.guild_id), None)
    
    if members is None:
        await interaction.response.send_message(
            "There's no registered birthdays yet!" +\
            "\nUse `/add_birthday` to add member birthdays!",
            ephemeral=True
        )
        return
    msg = []
    for i, (m, d, y, name, mid, cid) in enumerate(members):
        msg.append(
            f"{i+1}. **{name}**: {m}-{d}-{y}"
        )
    msg = '\n'.join(msg)
    emb = discord.Embed(
        title=f'Registered birthdays for this Server:',
        description=msg
    )
    await interaction.response.send_message(
        embed=emb
    )

    
#------------------------------------------------------------------------------
@tasks.loop(seconds=3600)
async def check_birthdays():
    global BIRTHDAY_LIST
    date = datetime.datetime.now()
    mm, dd, yy, hh = date.month, date.day, date.year, date.hour
    if (hh != 6):
        return
    
    print("Checking birthdays...", end=' ')
    
    for key in BIRTHDAY_LIST.keys():
        for m, d, y, name, mid, cid in BIRTHDAY_LIST[key]:
            channel = await client.fetch_channel(cid)
            if (mm == int(m)) and (dd == int(d)) and (yy == int(y)):
                #Birthday matches
                try:
                    allowed_mentions = discord.AllowedMentions(everyone=True)
                    
                    await channel.send(
                        f"# @everyone wish <@{mid}> a verry happy birthday today!",
                        allowed_mentions=allowed_mentions
                    )
                    
                except Exception as e:
                    print("Cannot send to channel!")
                    print("Error!", e)
    print("Complete!")

                    
#------------------------------------------------------------------------------
if __name__ == "__main__":
    client.run(TOKEN)
    pass
