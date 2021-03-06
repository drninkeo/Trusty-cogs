from .constants import HEADSHOT_URL, TEAMS
import asyncio
from typing import List
from datetime import datetime
import discord
from .helper import check_to_post, get_team
from redbot.core.i18n import Translator
from redbot.core import Config
import logging

try:
    from .oilers import Oilers
except ImportError:
    pass


_ = Translator("Hockey", __file__)

log = logging.getLogger("red.trusty-cogs.Hockey")


class Goal:
    def __init__(
        self,
        goal_id: str,
        team_name: str,
        scorer_id: int,
        jersey_no: str,
        description: str,
        period: int,
        period_ord: str,
        time_remaining: str,
        time: str,
        home_score: int,
        away_score: int,
        strength: str,
        empty_net: bool,
        event: str,
    ):
        super().__init__()
        self.goal_id = goal_id
        self.team_name = team_name
        self.scorer_id = scorer_id
        self.headshot = HEADSHOT_URL.format(scorer_id)
        self.jersey_no = jersey_no
        self.description = description
        self.period = period
        self.period_ord = period_ord
        self.time_remaining = time_remaining
        self.time = datetime.strptime(time, "%Y-%m-%dT%H:%M:%SZ")
        self.home_score = home_score
        self.away_score = away_score
        self.strength = strength
        self.empty_net = empty_net
        self.event = event
        self.tasks: List[asyncio.Task] = []

    def to_json(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "team_name": self.team_name,
            "scorer_id": self.scorer_id,
            "jersey_no": self.jersey_no,
            "description": self.description,
            "period": self.period,
            "period_ord": self.period_ord,
            "time_remaining": self.time_remaining,
            "time": self.time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "home_score": self.home_score,
            "away_score": self.away_score,
            "strength": self.strength,
            "empty_net": self.empty_net,
            "event": self.event,
        }

    @classmethod
    async def from_json(cls, data: dict, players: dict):
        scorer_id = []
        if "players" in data:
            scorer_id = [
                p["player"]["id"] for p in data["players"] if p["playerType"] in ["Scorer", "Shooter"]
            ]

        if "strength" in data["result"]:
            str_dat = data["result"]["strength"]["name"]
            strength = "Even Strength" if str_dat == "Even" else str_dat
            if data["about"]["ordinalNum"] == "SO":
                strength = "Shoot Out"
        else:
            strength = " "
        empty_net = data["result"]["emptyNet"] if "emptyNet" in data["result"] else False
        player_id = f"ID{scorer_id[0]}" if scorer_id != [] else None
        if player_id in players:
            jersey_no = players[player_id]["jerseyNumber"]
        else:
            jersey_no = ""
        # scorer = scorer_id[0]
        return cls(
            data["result"]["eventCode"],
            data["team"]["name"],
            scorer_id[0] if scorer_id != [] else None,
            jersey_no,
            data["result"]["description"],
            data["about"]["period"],
            data["about"]["ordinalNum"],
            data["about"]["periodTimeRemaining"],
            data["about"]["dateTime"],
            data["about"]["goals"]["home"],
            data["about"]["goals"]["away"],
            strength,
            empty_net,
            data["result"]["event"],
        )

    async def post_team_goal(self, bot, game_data):
        """
            Creates embed and sends message if a team has scored a goal
        """
        # scorer = self.headshots.format(goal["players"][0]["player"]["id"])
        post_state = ["all", game_data.home_team, game_data.away_team]
        msg_list = {}
        if "Edmonton Oilers" in self.team_name and "missed" not in self.event.lower():
            try:
                hue = Oilers(bot)
                self.tasks.append(hue.goal_lights())
            except Exception:
                pass
        goal_embed = await self.goal_post_embed(game_data)
        goal_text = await self.goal_post_text(game_data)
        tasks = []
        for channels in await bot.get_cog("Hockey").config.all_channels():
            channel = bot.get_channel(id=channels)
            if channel is None:
                await bot.get_cog("Hockey").config._clear_scope(Config.CHANNEL, str(channels))
                log.info("{} channel was removed because it no longer exists".format(channels))
                continue
            should_post = await check_to_post(bot, channel, post_state, "Goal")
            if should_post:
                tasks.append(self.actually_post_goal(bot, channel, goal_embed, goal_text))
        data = await asyncio.gather(*tasks)
        for channel in data:
            if channel is None:
                continue
            else:
                msg_list[str(channel[0])] = channel[1]
        return msg_list

    async def actually_post_goal(self, bot, channel, goal_embed, goal_text):
        try:
            guild = channel.guild
            if not channel.permissions_for(guild.me).send_messages:
                log.debug(_("No permission to send messages in {channel} ({id})").format(
                        channel=channel, id=channel.id
                    ))
                return
            config = bot.get_cog("Hockey").config
            game_day_channels = await config.guild(guild).gdc()
            # Don't want to ping people in the game day channels
            can_embed = channel.permissions_for(guild.me).embed_links
            can_manage_webhooks = (
                False
            )  # channel.permissions_for(guild.me).manage_webhooks
            role = None
            goal_notifications = await config.guild(guild).goal_notifications()
            if goal_notifications:
                log.debug(goal_notifications)
                for roles in guild.roles:
                    if roles.name == self.team_name + " GOAL":
                        role = roles
                        break
                if goal_notifications == "auto" and guild.me.guild_permissions.manage_roles:
                    if role and role < guild.me.top_role:
                        try:
                            await role.edit(mentionable=True)
                        except Exception:
                            pass

            if game_day_channels is not None:
                # We don't want to ping people in the game day channels twice
                if channel.id in game_day_channels:
                    role = None

            if not can_embed and can_manage_webhooks:
                # try to create a webhook with the teams info to bypass embed permissions
                # Waiting for d.py to return messages from webhook responses
                # After testing it doesn't look as nice as I would like
                # Will leave it off until at some point I can make it look better
                webhook = None
                for hook in await channel.webhooks():
                    if hook.name == guild.me.name:
                        webhook = hook
                if webhook is None:
                    webhook = await channel.create_webhook(name=guild.me.name)
                url = TEAMS[self.team_name]["logo"]
                await webhook.send(
                    username=self.team_name, avatar_url=url, embed=goal_embed
                )
                return

            if not can_embed and not can_manage_webhooks:
                # Create text only message if embed_links permission is not set
                if role is not None:
                    msg = await channel.send(f"{role}\n{goal_text}")
                else:
                    msg = await channel.send(goal_text)
                # msg_list[str(channel.id)] = msg.id
                return channel.id, msg.id

            if role is None or "missed" in self.event.lower():
                msg = await channel.send(embed=goal_embed)
                # msg_list[str(channel.id)] = msg.id
                return channel.id, msg.id
            else:
                msg = await channel.send(role.mention, embed=goal_embed)
                # msg_list[str(channel.id)] = msg.id
                if goal_notifications == "auto" and guild.me.guild_permissions.manage_roles:
                    if role and role < guild.me.top_role:
                        try:
                            await role.edit(mentionable=False)
                        except Exception:
                            pass
                return channel.id, msg.id
        except Exception:
            log.error(_("Could not post goal in "), exc_info=True)
            return

    @staticmethod
    async def remove_goal_post(bot, goal, team, data):
        """
            Attempt to delete a goal if it was pulled back
        """
        config = bot.get_cog("Hockey").config
        team_list = await config.teams()
        team_data = await get_team(bot, team)
        if goal not in [goal.goal_id for goal in data.goals]:
            try:
                old_msgs = team_data["goal_id"][goal]["messages"].items()
            except Exception:
                log.error("Error iterating saved goals", exc_info=True)
                return
            for channel_id, message_id in old_msgs:
                channel = bot.get_channel(id=int(channel_id))
                if channel and channel.permissions_for(channel.guild.me).read_message_history:
                    try:
                        try:
                            message = await channel.fetch_message(message_id)
                        except AttributeError:
                            message = await channel.get_message(message_id)
                        if message is not None:
                            await message.delete()
                    except Exception:
                        log.error(f"Cannot find message {str(team)} {str(goal)}", exc_info=True)
                        pass
                else:
                    log.debug(_("Channel does not have permission to read history"))
            try:
                team_list.remove(team_data)
                del team_data["goal_id"][goal]
                team_list.append(team_data)
                await config.teams.set(team_list)
            except Exception:
                log.error("Error removing team data", exc_info=True)
                return
        return

    async def edit_team_goal(self, bot, game_data, og_msg):
        """
            When a goal scorer has changed we want to edit the original post
        """
        # scorer = self.headshots.format(goal["players"][0]["player"]["id"])
        # post_state = ["all", game_data.home_team, game_data.away_team]
        em = await self.goal_post_embed(game_data)
        tasks = []
        for channel_id, message_id in og_msg.items():
            channel = bot.get_channel(id=int(channel_id))
            if channel is None:
                continue
            tasks.append(self.edit_goal(bot, channel, message_id, em))

        await asyncio.gather(*tasks)
        return

    async def edit_goal(self, bot, channel, message_id, em):
        try:
            if not channel.permissions_for(channel.guild.me).embed_links:
                return
            try:
                message = await channel.fetch_message(message_id)
            except AttributeError:
                message = await channel.get_message(message_id)
            guild = message.guild
            game_day_channels = await bot.get_cog("Hockey").config.guild(guild).gdc()
            role = None
            for roles in guild.roles:
                if roles.name == self.team_name + " GOAL":
                    role = roles
            if game_day_channels is not None:
                # We don't want to ping people in the game day channels twice
                if channel.id in game_day_channels:
                    role = None
            if role is None or "missed" in self.event.lower():
                await message.edit(embed=em)
            else:
                await message.edit(content=role.mention, embed=em)
        except Exception:
            log.error(_("Could not edit goal in "))

    async def get_shootout_display(self, game_goals):
        """
            Gets a string for the shootout display
        """
        msg = ""
        score = "☑\n"
        miss = "❌\n"
        for goal in game_goals:
            if goal.event in ["Shot", "Missed Shot"] and goal.period_ord == "SO":
                msg += miss
            if goal.event in ["Goal"] and goal.period_ord == "SO":
                msg += score
        return msg

    async def goal_post_embed(self, game):
        """
            Gets the embed for goal posts
        """
        # h_emoji = game.home_emoji
        # a_emoji = game.away_emoji
        shootout = False
        if game.period_ord == "SO":
            shootout = True
        colour = (
            int(TEAMS[self.team_name]["home"].replace("#", ""), 16)
            if self.team_name in TEAMS
            else None
        )
        title = "🚨 {} #{} {} {} 🚨".format(
            self.team_name, self.jersey_no, self.strength, self.event
        )
        url = TEAMS[self.team_name]["team_url"] if self.team_name in TEAMS else "https://nhl.com"
        logo = TEAMS[self.team_name]["logo"] if self.team_name in TEAMS else "https://nhl.com"
        if not shootout:

            em = discord.Embed(description=self.description)
            if colour is not None:
                em.colour = colour
            em.set_author(name=title, url=url, icon_url=logo)
            home_str = (
                _("Goals: **")
                + str(self.home_score)
                + _("** \nShots: **")
                + str(game.home_shots)
                + "**"
            )
            away_str = (
                _("Goals: **")
                + str(self.away_score)
                + _("** \nShots: **")
                + str(game.away_shots)
                + "**"
            )
            home_field = f"{game.home_emoji} {game.home_team} {game.home_emoji}"
            away_field = f"{game.away_emoji} {game.away_team} {game.away_emoji}"
            em.add_field(name=home_field, value=home_str, inline=True)
            em.add_field(name=away_field, value=away_str, inline=True)
            em.set_footer(
                text=str(self.time_remaining)
                + _(" left in the ")
                + str(self.period_ord)
                + _(" period"),
                icon_url=logo,
            )
            em.timestamp = self.time
        else:
            if "missed" in self.event.lower():
                em = discord.Embed(description=self.description, colour=colour)
                em.set_author(name=title.replace("🚨", ""), url=url, icon_url=logo)
            else:
                em = discord.Embed(description=self.description, colour=colour)
                em.set_author(name=title, url=url, icon_url=logo)
            home_msg = await self.get_shootout_display(game.home_goals)
            away_msg = await self.get_shootout_display(game.away_goals)
            em.add_field(name=game.home_team, value=home_msg)
            em.add_field(name=game.away_team, value=away_msg)
            em.set_footer(
                text=str(game.period_time_left)
                + _(" left in the ")
                + str(game.period_ord)
                + _(" period"),
                icon_url=logo,
            )
            em.timestamp = self.time
        return em

    async def goal_post_text(self, game):
        """
            Gets the text to send for goal posts
        """
        if game.period_ord != "SO":
            text = (
                f"{game.home_emoji} {game.home_team}: {game.home_score}\n"
                f"{game.away_emoji} {game.away_team}: {game.away_score}\n "
                f"({self.time_remaining}"
                + _(" left in the ")
                + f"{game.period_ord}"
                + _(" period")
                + ")"
            )
        else:
            home_msg = await self.get_shootout_display(game.home_goals)
            away_msg = await self.get_shootout_display(game.away_goals)
            text = (
                f"{game.home_emoji} {game.home_team}: {home_msg}\n"
                f"{game.away_emoji} {game.away_team}: {away_msg}\n "
                f"({self.time_remaining}"
                + _(" left in the ")
                + f"{game.period_ord}"
                + _(" period")
                + ")"
            )
        return text
