import re
import math
import time
import json
import requests
import urllib.parse
import discord
from typing import Optional
from discord import app_commands
from discord.ext import tasks

REFRESH_TIME = 60 # seconds
SCORES_THRESHOLD = 4
EDIT_TIME = 900 # improvements within 15 minutes of each other result in an edited message instead of a new one, to reduce spam
GUILD_ID = 435308083036553217 # [435308083036553217, 410600026679541783, 1432186372222877871] # hardcoded guilds, used when syncing locally rather than globally
SYNC_GLOBALLY = False
SYNC_LOCALLY = False
LB_API_SERVER = "https://openhexagon.fun:8001"

def rreplace(s, old, new):
    return new.join(s.rsplit(old, 1))

def log(s : str):
    ms = time.time() - math.floor(time.time())
    ms_f = ("%.3f" % ms).lstrip('0')
    time_str = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"OH-Leaderboard-Bot ({time_str}{ms_f}): " + s)

class leaderboard_client(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def command_tree(self):
        tree = app_commands.CommandTree(self)

        # guild or None

        @tree.command(name="subscribe", description="Subscribes this channel to leaderboard updates")
        async def guild_subscribe(interaction: discord.Interaction):
            # i think there's a better way to do the permissions handling but this is quick and easy
            if interaction.permissions.manage_guild == True:
                await self.update_subscribed_channels(dict(channel_id=interaction.channel.id, guild_id=interaction.guild.id), False)
                await interaction.response.send_message("This channel has subscribed to leaderboard updates.")
            else:
                await interaction.response.send_message("You do not have permission to run this command.", ephemeral=True)

        @tree.command(name="unsubscribe", description="Unsubscribes this channel from leaderboard updates")
        async def guild_unsubscribe(interaction: discord.Interaction):
            if interaction.permissions.manage_guild == True:
                await self.update_subscribed_channels(dict(channel_id=interaction.channel.id, guild_id=interaction.guild.id), True)
                await interaction.response.send_message("This channel has unsubscribed from leaderboard updates.")
            else:
                await interaction.response.send_message("You do not have permission to run this command.", ephemeral=True)

        @tree.command(name="recent", description="Sends the most recent score.")
        async def guild_recent(interaction: discord.Interaction, player: Optional[str]):
            # choosing six hours as an arbitrary cutoff point, since i don't want to spam the api
            # is there an easier way to find the most recent score?
            log(f"Requesting the most recent score.")
            recent_scores = requests.get(f'{LB_API_SERVER}/get_newest_scores/21600')

            scores_json = recent_scores.json()
            log(f"{len(scores_json)} scores found.")
            saved_state = await self.get_saved_state()

            score_text = await self.send_recent_score(scores_json, saved_state, player)
            await interaction.response.send_message(score_text)

        # @tree.command(name="best", description="Sends the best score from a level.")
        # async def guild_best(interaction: discord.Interaction, pack: str, level: str, difficulty_mult: float):
        #     log(f"Requesting the best score for {pack} - {level} {difficulty_mult}x.")
        #     recent_scores = requests.get(f'{LB_API_SERVER}/get_newest_scores/21600')
        #
        #     saved_state = await self.get_saved_state()
        #
        #     score_text = await self.send_best_score(saved_state, pack, level, difficulty_mult)
        #     await interaction.response.send_message(score_text)

        # TODO: command that shows u the top score on a given level
        # this will require me to know how the leadboard api works... maybe ask baum?

        self.tree = tree

    async def get_saved_state(self):
        saved_state = {}
        try:
            with open("saved_state.json") as fp:
                saved_state = json.load(fp)
        except FileNotFoundError:
            pass  # just uses defaults
        saved_state["video_queue"] = saved_state.get("video_queue", [])
        saved_state["last_call_timestamp"] = saved_state.get("last_call_timestamp", 0)
        saved_state["recent_scores"] = saved_state.get("recent_scores", [])
        saved_state["subscribed_channels"] = saved_state.get("subscribed_channels", [])

        return saved_state

    async def update_subscribed_channels(self, new_entry, is_removing_entry):
        saved_state = await self.get_saved_state()

        if is_removing_entry:
            # find the right channel id and remove it
            for entry in saved_state["subscribed_channels"]:
                if entry["channel_id"] == new_entry["channel_id"]:
                    saved_state["subscribed_channels"].remove(entry)
        else:
            saved_state["subscribed_channels"].append({"channel_id": new_entry["channel_id"], "guild_id": new_entry["guild_id"]})

        with open("saved_state.json", "w") as fp:
            json.dump(saved_state, fp)
        log("Updated subscribed channels.")

    async def on_ready(self):
        assert isinstance(self.user, discord.ClientUser)
        log(f"Logged in as {self.user} (ID: {self.user.id})")

        # setup command tree
        await self.command_tree()
        if SYNC_GLOBALLY:
            await self.tree.sync()
            log(f"Synchronized commands globally.")
        if SYNC_LOCALLY:
            await self.tree.sync(guild=discord.Object(id=GUILD_ID))
            log(f"Synchronized commands with guild. (GUILD_ID: {GUILD_ID})")

    async def setup_hook(self) -> None:
        # setup pack and level lookup table
        self.create_lookup_table()

        # start the task to run in the background
        self.check_scores_task.start()
        log(f"Started background task for leaderboard checking.")

    @tasks.loop(seconds=REFRESH_TIME)  # task runs every REFRESH_TIME seconds
    async def check_scores_task(self):
        saved_state = {}
        try:
            with open("saved_state.json") as fp:
                saved_state = json.load(fp)
        except FileNotFoundError:
            pass  # just uses defaults
        saved_state["video_queue"] = saved_state.get("video_queue", [])
        saved_state["last_call_timestamp"] = saved_state.get("last_call_timestamp", 0)
        saved_state["recent_scores"] = saved_state.get("recent_scores", [])
        saved_state["subscribed_channels"] = saved_state.get("subscribed_channels", [])

        current_time = time.time()
        time_difference = math.ceil(current_time - saved_state["last_call_timestamp"])
        saved_state["last_call_timestamp"] = current_time

        log(f"Requesting scores from the past {time_difference} seconds.")
        recent_scores = requests.get(f'{LB_API_SERVER}/get_newest_scores/{time_difference}')

        scores_json = recent_scores.json()
        log(f"{len(scores_json)} scores found.")
        await self.send_wrs(scores_json, saved_state)
        await self.check_videos(saved_state["video_queue"], saved_state["subscribed_channels"])
        with open("saved_state.json", "w") as fp:
            json.dump(saved_state, fp)
        log("Done.")

    def get_score_text(self, score):
        pack_ID = score["pack"]
        level_ID = score["level"]
        try:
            pack_name = self.pack_lookup[pack_ID]["pack_name"]
            level_name = self.pack_lookup[pack_ID]["levels"][level_ID][0]
        except KeyError:
            # new levels were added to the server, must refresh cache
            self.create_lookup_table()

            pack_name = self.pack_lookup[pack_ID]["pack_name"]
            level_name = self.pack_lookup[pack_ID]["levels"][level_ID][0]

        num_diffs = self.pack_lookup[pack_ID]["levels"][level_ID][1]

        mult = f"{score['level_options']['difficulty_mult']:.6g}"

        diff_str = ""
        if num_diffs > 1:
            diff_str = f" [x{mult}]"
        # if level has only 1 difficulty, but score wasn't set on x1, something is wrong
        elif mult != "1":
            log(f"WARNING: Level {level_ID} may have added difficulty mults, refreshing cache.")
            self.create_lookup_table()
            diff_str = f" [x{mult}]"

        player = score["user_name"]
        run_length = round(score["value"], 3)
        rank = score["position"]

        if pack_name[0] == "#":
            pack_name = "\\" + pack_name

        return f"**{pack_name} - {level_name}{diff_str}** <:hexagon:1432891341297418322> **{player}** achieved **#{rank}** with a score of **{run_length}**"

    async def send_recent_score(self, scores_json, saved_state, player_check):
        # because we are just sending one score, we don't have to check for edits or update the saved state
        channels = self.get_output_channels(saved_state["subscribed_channels"])
        for i in range(len(scores_json)):
            score = scores_json[len(scores_json) - i - 1]
            player = score["user_name"]

            if player == player_check or player_check == None:
                score_text = self.get_score_text(score)
                return score_text
        return "No recent scores found. (within the last six hours)"

    async def send_best_score(self, saved_state, pack, level, difficulty_mult):
        channels = self.get_output_channels(saved_state["subscribed_channels"])

        # the order of operations for this is that we need to lookup the pack id, then find the best score, then run get_score_text

        for pack_id, pack_entry in self.pack_lookup.items():
            if pack_entry["pack_name"].lower() == pack.lower():
                for level_id, level_entry in pack_entry["levels"].items():
                    if level_entry[0].lower() == level.lower():
                        pack_ID = pack_id
                        level_ID = level_id

        # this is the "finding the best score" part
        pack_ID_str = urllib.parse.quote(pack_ID)
        level_ID_str = urllib.parse.quote(level_ID)
        # bad way of doing this!
        level_options_str = urllib.parse.quote(f"{{difficulty_mult: {difficulty_mult}}}")

        try:
            lb_scores = requests.get(f"{LB_API_SERVER}/get_leaderboard/{pack_ID_str}/{level_ID_str}/{level_options_str}").json()
        except:
            log(f"WARNING: Could not get leaderboard for {LB_API_SERVER}/get_leaderboard/{pack_ID_str}/{level_ID_str}/{level_options_str}.")
            return "Unable to fetch leaderboard. (did you type in the level correctly?)"

        for score in lb_scores:
            if score["position"] == 1:
                # running this function here is quite redundant
                score_text = self.get_score_text(score)
                return score_text
        return "This level has no scores."

    async def send_wrs(self, scores_json, saved_state):
        # note: the channels are only checked at the start of the loop, meaning that scores could be sent even after running the unsubscribe command
        channels = self.get_output_channels(saved_state["subscribed_channels"])
        for score in scores_json:
            rank = score["position"]

            if rank == 1:
                pack_ID = score["pack"]
                level_ID = score["level"]

                pack_ID_str = urllib.parse.quote(pack_ID)
                level_ID_str = urllib.parse.quote(level_ID)
                level_options_str = urllib.parse.quote(json.dumps(score["level_options"]))

                try:
                    lb_scores = requests.get(f"{LB_API_SERVER}/get_leaderboard/{pack_ID_str}/{level_ID_str}/{level_options_str}").json()
                    num_lb_scores = len(lb_scores)
                except:
                    log(f"WARNING: Could not get leaderboard for {LB_API_SERVER}/get_leaderboard/{pack_ID_str}/{level_ID_str}/{level_options_str}.")
                    num_lb_scores = SCORES_THRESHOLD # allow score

                if num_lb_scores >= SCORES_THRESHOLD:
                    score_text = self.get_score_text(score)

                    # remove old messages from the edit queue
                    for last_score in saved_state["recent_scores"]:
                        if score["timestamp"] - last_score["timestamp"] > EDIT_TIME:
                            saved_state["recent_scores"].remove(last_score)

                    messages = []
                    edited = False
                    # check if score could be edited into a previous message 
                    for last_score in saved_state["recent_scores"]:
                        if score["pack"] == last_score.get("pack", "") and \
                            score["level"] == last_score["level"] and \
                            score["level_options"] == last_score["level_options"]:
                            
                            # if two people are competing on the same level in the same 15 minutes, do not edit
                            if score["user_name"] != last_score["user_name"] and score["value"] > last_score["value"]:
                                saved_state["recent_scores"].remove(last_score)
                                break

                            for channel in channels:
                                for message in last_score["messages"]:
                                    if channel.id == message["channel_id"]:
                                        msg = await channel.fetch_message(message["message_id"])

                                        new_content = msg.content + "\n" + score_text

                                        log(f"Appending '{score_text}' to message {msg.id}")
                                        await msg.edit(content=new_content)

                                        messages.append({"channel_id": channel.id, "message_id": msg.id})
                                        edited = True
                                        break
                            break
                    
                    if not edited:
                        messages = []
                        # send new message
                        for channel in channels:
                            msg = await channel.send(score_text)
                            messages.append({"channel_id": channel.id, "message_id": msg.id})
                        saved_state["recent_scores"].append({**score, "messages": messages})
                    
                    if rank == 1:
                        saved_state["video_queue"].append({**score, "messages": messages})

    async def check_videos(self, queue, subscribed_channels):
        channels = self.get_output_channels(subscribed_channels)
        log(f"Checking {len(queue)} queued messages for video progress.")
        while len(queue) > 0:
            score = queue[0]
            has_better = False
            for i in range(1, len(queue)):
                later_score = queue[i]
                # python does not compare dicts by reference but by contents, so yes the level_options part is fine
                if score["pack"] == later_score["pack"] and \
                        score["level"] == later_score["level"] and \
                        score["level_options"] == later_score["level_options"] and \
                        score["position"] == 1 and later_score["position"] == 1:
                    # there is a newer #1 score on the same level
                    # so this one will not be receiving a video
                    queue.pop(0)
                    return
            # check if video exists
            replay_hash = score["replay_hash"]
            video_link = f"{LB_API_SERVER}/get_video/{replay_hash}"
            try:
                response_headers = requests.get(video_link, headers={"Range": "bytes=0-0"}).headers
            except Exception as e:
                log(f"Error trying to check if video exists: {e}.")
                return
            if response_headers["Content-Type"] == "video/mp4":
                # exists now, edit message to include link
                for channel in channels:
                    for message in score["messages"]:
                        if channel.id == message["channel_id"]:
                            msg = await channel.fetch_message(message["message_id"])
                            run_length = round(score["value"], 3)

                            # remove previous links
                            new_content = re.sub(r"\[(\d+(\.\d*)?)\]\(.+\)", r"\1", msg.content)
                            # add newest link
                            new_content = rreplace(new_content, f"**{run_length}**", f"**[{run_length}]({video_link}) **")

                            log(f"Editing '{msg.content}' to '{new_content}'")
                            await msg.edit(content=new_content)
                queue.pop(0)
                break
            else:
                return

    @check_scores_task.before_loop # type: ignore
    async def before_my_task(self):
        await self.wait_until_ready()  # wait until the bot logs in
    
    def get_output_channels(self, subscribed_channels):
        output_channels = []
        for entry in subscribed_channels:
            channel = self.get_channel(entry["channel_id"])
            if not channel:
                log(f"ERROR: Could not find channel <{entry["channel_id"]}>.")
                return
            assert isinstance(channel, discord.TextChannel), "You have set your output to a channel that isn't a text channel."
            output_channels.append(channel)
        return output_channels

    def create_lookup_table(self):
        all_packs = requests.get(f"{LB_API_SERVER}/get_packs/1/1000")

        # pack_lookup: dict of dicts
        # {
        #     pack_id: {
        #         "pack_name": str
        #         "levels": {
        #             level_id: (str, #difficulties)
        #         }
        #     }
        # }
        self.pack_lookup = {}
        for pack_dict in all_packs.json():
            self.pack_lookup[pack_dict["id"]] = {
                "pack_name": pack_dict["name"],
                "levels": {}
            }

            for level_dict in pack_dict["levels"]:
                num_diffs = len(level_dict["options"]["difficulty_mult"])
                self.pack_lookup[pack_dict["id"]]["levels"][level_dict["id"]] = (level_dict["name"], num_diffs)

if __name__ == "__main__":
    client = leaderboard_client(intents=discord.Intents.default())

    with open("token.txt", "r") as token_file:
        token = token_file.read()
    
    client.run(token)
