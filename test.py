import time
import json
import os
import cloudscraper
import logging
import asyncio

import discord
from discord.ext import tasks

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("blog_monitor_debug.log"),
        logging.StreamHandler()
    ]
)

BOT_TOKEN = ""
TARGET_CHANNEL_ID = 
PING_USER_ID  =   

COMPETITIVE_API = "https://www.fortnite.com/competitive/api/blog/getPosts?offset=0&category=&locale=en&rootPageSlug=news&postsPerPage=0"
NORMAL_API      = "https://www.fortnite.com/api/blog/getPosts?category=&locale=en&offset=0&postsPerPage=0&rootPageSlug=blog&sessionInvalidated=true"
CREATIVE_API    = "https://create.fortnite.com/api/cms/v1/articles/"  

DATA_FILE = "old_data.json"

# Seconds
MESSAGE_DELAY = 2

def load_old_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                logging.debug("Loaded old data from %s", DATA_FILE)
                return data
        except Exception as e:
            logging.error("Error loading old data: %s", e)
    logging.debug("No old data found. Starting fresh.")
    return {}

def save_old_data(data):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f)
        logging.debug("Saved old data to %s", DATA_FILE)
    except Exception as e:
        logging.error("Error saving old data: %s", e)

def fetch_posts(url):
    scraper = cloudscraper.create_scraper()
    try:
        logging.debug("Fetching posts from %s", url)
        response = scraper.get(url)
        response.raise_for_status()
        posts = response.json().get("blogList", [])
        # For the Creative API, the structure is the same, so "blogList" still applies.
        logging.debug("Fetched %d posts from %s", len(posts), url)
        return posts
    except Exception as e:
        logging.error("Error fetching %s: %s", url, e)
        return []

def get_post_id(post):
    post_id = post.get("_id") or post.get("link") or post.get("slug")
    logging.debug("Determined post id: %s", post_id)
    return post_id

def extract_description(meta_tags):
    search_key = 'meta name="description"'
    if search_key in meta_tags:
        try:
            start = meta_tags.find('content="', meta_tags.find(search_key)) + len('content="')
            end = meta_tags.find('"', start)
            description = meta_tags[start:end]
            return description
        except Exception as e:
            logging.error("Error extracting description: %s", e)
            return None
    return None

def build_embed(post, category=""):
    title = post.get("title") or post.get("gridTitle") or "No Title"
    title = title.replace("the competitive Fortnite team", "").strip()
    
    # Description extraction from _metaTags
    meta_tags = post.get("_metaTags", "")
    description = extract_description(meta_tags)
    if not description:
        description = post.get("content") or None
        if description and len(description) > 1000:
            description = description[:997] + "..."
    
    if description and "<p style=" in description:
        description = None

    if post.get("link") and post.get("link").startswith("http"):
        link = post.get("link")
    else:
        slug = post.get("slug")
        if slug:
            link = f"https://www.fortnite.com/blog/{slug}"
        else:
            link = "https://www.fortnite.com/"
    
    embed = discord.Embed(title=title, color=0)
    
    if description:
        embed.description = description

    author = post.get("author") or "Unknown"
    embed.add_field(name="Author", value=author, inline=False)
    
    image_url = post.get("image")
    if image_url and "576x576" in image_url:
        embed.set_thumbnail(url=image_url)
    
    trending_image = post.get("trendingImage")
    if trending_image:
        embed.set_image(url=trending_image)
    
    embed.add_field(name="Read More", value=f"[Visit Blog Post]({link})", inline=False)
    
    logging.debug("Built embed for post id %s with title '%s' (Category: %s)", get_post_id(post), title, category)
    return embed

class BlogMonitorBot(discord.Client):
    def __init__(self, *, intents: discord.Intents, **kwargs):
        super().__init__(intents=intents, **kwargs)
        self.old_data = load_old_data()
        self.channel = None

    async def on_ready(self):
        logging.info("Bot is ready and logged in as %s", self.user)
        self.channel = self.get_channel(TARGET_CHANNEL_ID)
        if self.channel is None:
            logging.error("Channel with ID %s not found.", TARGET_CHANNEL_ID)
        else:
            logging.info("Found target channel: %s", self.channel.name)
        self.blog_monitor_loop.start()

    @tasks.loop(seconds=60)
    async def blog_monitor_loop(self):
        logging.debug("Polling APIs for new posts.")
        new_embeds = []

        loop = asyncio.get_running_loop()
        competitive_posts = await loop.run_in_executor(None, fetch_posts, COMPETITIVE_API)
        normal_posts      = await loop.run_in_executor(None, fetch_posts, NORMAL_API)
        creative_posts    = await loop.run_in_executor(None, fetch_posts, CREATIVE_API)  

        for post in competitive_posts:
            post_id = get_post_id(post)
            if post_id:
                trending = post.get("trending", False)
                if post_id not in self.old_data or self.old_data[post_id].get("trending") != trending:
                    logging.debug("New or updated competitive post detected: %s", post_id)
                    new_embeds.append((build_embed(post, category="Competitive"), MESSAGE_DELAY))
                    self.old_data[post_id] = {"trending": trending}
                else:
                    logging.debug("Competitive post %s already processed.", post_id)

        for post in normal_posts:
            post_id = get_post_id(post)
            if post_id:
                trending = post.get("trending", False)
                if post_id not in self.old_data or self.old_data[post_id].get("trending") != trending:
                    logging.debug("New or updated normal post detected: %s", post_id)
                    new_embeds.append((build_embed(post, category="Normal"), MESSAGE_DELAY))
                    self.old_data[post_id] = {"trending": trending}
                else:
                    logging.debug("Normal post %s already processed.", post_id)

        for post in creative_posts:
            post_id = get_post_id(post)
            if post_id:
                trending = post.get("trending", False)
                if post_id not in self.old_data or self.old_data[post_id].get("trending") != trending:
                    logging.debug("New or updated creative post detected: %s", post_id)
                    new_embeds.append((build_embed(post, category="Creative"), MESSAGE_DELAY))
                    self.old_data[post_id] = {"trending": trending}
                else:
                    logging.debug("Creative post %s already processed.", post_id)

        if new_embeds:
            logging.info("Found %d new posts. Sending messages to channel.", len(new_embeds))
            for embed, delay in new_embeds:
                try:
                    await self.channel.send(content=f"<@&{PING_USER_ID}>", embed=embed)
                    logging.info("Sent a new blog post update.")
                    await asyncio.sleep(delay)
                except Exception as e:
                    logging.error("Error sending message: %s", e)
            save_old_data(self.old_data)
        else:
            logging.info("No new posts found.")

    @blog_monitor_loop.before_loop
    async def before_blog_monitor_loop(self):
        await self.wait_until_ready()

intents = discord.Intents.default()
intents.message_content = True

bot = BlogMonitorBot(intents=intents)
bot.run(BOT_TOKEN)