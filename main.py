import math
import time
import json
import requests
import urllib.parse
import discord
from discord.ext import tasks

REFRESH_TIME = 60 # seconds
LB_CHANNEL_ID = 913896034579673138

def log(str):
    ms = time.time() - math.floor(time.time())
    ms = ("%.3f" % ms).lstrip('0')
    print(f"OH-Leaderboard-Bot ({time.strftime("%Y-%m-%d %H:%M:%S")}{ms}): " + str)

class leaderboard_client(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def on_ready(self):
        log(f"Logged in as {self.user} (ID: {self.user.id})")

    async def setup_hook(self) -> None:
        # setup pack and level lookup table
        self.create_lookup_table()

        # start the task to run in the background
        self.check_recent_scores_task.start()
        log(f"Started background task for leaderboard checking.")

    @tasks.loop(seconds=REFRESH_TIME)  # task runs every REFRESH_TIME seconds
    async def check_recent_scores_task(self):
        current_time = time.time()

        try:
            with open("last_call_timestamp.txt", "r") as timestamp_file:
                previous_time = float(timestamp_file.read())
                time_difference = round(current_time - previous_time) 
        except:
            log("WARNING: No timestamp file detected -- scores are likely missed.")
            time_difference = 60

        log(f"Requesting scores from the past {time_difference} seconds.")
        recent_scores = requests.get(f'https://openhexagon.fun:8001/get_newest_scores/{time_difference}')

        scores_json = recent_scores.json()
        log(f"{len(scores_json)} scores found.")
        await self.send_wrs(scores_json)
        
        with open("last_call_timestamp.txt", "w") as timestamp_file:
            timestamp_file.write(str(current_time))
        
    @check_recent_scores_task.before_loop
    async def before_my_task(self):
        await self.wait_until_ready()  # wait until the bot logs in

    async def send_wrs(self, scores_json):
        for score in scores_json:
            rank = score["position"]

            if rank == 1:
                pack_ID = score["pack"]
                level_ID = score["level"]

                pack_ID_str = urllib.parse.quote(pack_ID)
                level_ID_str = urllib.parse.quote(level_ID)
                level_options_str = urllib.parse.quote(json.dumps(score["level_options"]))

                try:
                    lb_scores = requests.get(f"https://openhexagon.fun:8001/get_leaderboard/{pack_ID_str}/{level_ID_str}/{level_options_str}").json()
                    num_lb_scores = len(lb_scores)
                except:
                    log(f"WARNING: Could not get leaderboard for https://openhexagon.fun:8001/get_leaderboard/{pack_ID_str}/{level_ID_str}/{level_options_str}.")
                    num_lb_scores = 5 # arbitrary number greater than 3

                if num_lb_scores >= 3:
                    pack_name = self.pack_lookup[pack_ID]["pack_name"]
                    level_name = self.pack_lookup[pack_ID]["levels"][level_ID][0]
                    num_diffs = self.pack_lookup[pack_ID]["levels"][level_ID][1]

                    mult = round(score["level_options"]["difficulty_mult"], 5)
                    diff_str = ""
                    if num_diffs > 1:
                        diff_str = f" [x{mult}]"

                    player = score["user_name"]
                    run_length = round(score["value"], 3)
            
                    video_link = f"https://openhexagon.fun:8001/get_video/{score["replay_hash"]}"
                    
                    channel = self.get_channel(LB_CHANNEL_ID)
                    await channel.send(f"**{pack_name} - {level_name}{diff_str}** <:hexagon:1388672832094867486> **{player}** achieved **#{rank}** with a score of **[{run_length}]({video_link}) **")

    def create_lookup_table(self):
        all_packs = requests.get("https://openhexagon.fun:8001/get_packs/1/1000")

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