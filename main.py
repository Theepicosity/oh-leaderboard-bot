import math
import time
import json
import requests
import urllib.parse
import discord
from discord.ext import tasks

REFRESH_TIME = 60 # seconds
LB_CHANNEL_ID = 913896034579673138
LB_API_SERVER = "https://openhexagon.fun:8001"

def log(s : str):
    ms = time.time() - math.floor(time.time())
    ms_f = ("%.3f" % ms).lstrip('0')
    time_str = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"OH-Leaderboard-Bot ({time_str}{ms_f}): " + s)

class leaderboard_client(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def on_ready(self):
        log(f"Logged in as {self.user} (ID: {self.user.id})")

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

        current_time = time.time()
        time_difference = math.ceil(current_time - saved_state["last_call_timestamp"])
        saved_state["last_call_timestamp"] = current_time

        log(f"Requesting scores from the past {time_difference} seconds.")
        recent_scores = requests.get(f'{LB_API_SERVER}/get_newest_scores/{time_difference}')

        scores_json = recent_scores.json()
        log(f"{len(scores_json)} scores found.")
        await self.send_wrs(scores_json, saved_state)
        await self.check_videos(saved_state["video_queue"])
        with open("saved_state.json", "w") as fp:
            json.dump(saved_state, fp)
        log("Done.")

    async def send_wrs(self, scores_json, saved_state):
        channel = self.get_channel(LB_CHANNEL_ID)
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

                    if pack_name[0] == "#":
                        pack_name = "\\" + pack_name

                    msg = await channel.send(f"**{pack_name} - {level_name}{diff_str}** <:hexagon:1388672832094867486> **{player}** achieved **#{rank}** with a score of **{run_length}**")
                    saved_state["video_queue"].append({**score, "message_id": msg.id})

    async def check_videos(self, queue):
        channel = self.get_channel(LB_CHANNEL_ID)
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
                    # there is a newer #1 score on the same level by the same player
                    # so this one will not be receiving a video
                    queue.pop(0)
                    return
            # check if video exists
            video_link = f"{LB_API_SERVER}/get_video/{score["replay_hash"]}"
            try:
                response_headers = requests.get(video_link, headers={"Range": "bytes=0-0"}).headers
            except:
                log("Error trying to check if video exists.")
                return
            if response_headers["Content-Type"] == "video/mp4":
                # exists now, edit message to include link
                message = await channel.fetch_message(score["message_id"])
                run_length = round(score["value"], 3)
                new_content = message.content.replace(f"**{run_length}**", f"**[{run_length}]({video_link}) **")
                log(f"Editing '{message.content}' to '{new_content}'")
                await message.edit(content=new_content)
                queue.pop(0)

    @check_scores_task.before_loop
    async def before_my_task(self):
        await self.wait_until_ready()  # wait until the bot logs in

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
