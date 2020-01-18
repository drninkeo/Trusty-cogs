# https://github.com/NotSoSuper/NotSoBot

import asyncio
import aiohttp
import discord
import os
import sys
import glob
import re
import random
import wand
import wand.color
import wand.drawing
import PIL
import PIL.Image
import PIL.ImageFont
import PIL.ImageOps
import PIL.ImageDraw
from PIL import ImageSequence
import numpy as np
import jpglitch
from .vw import macintoshplus
from io import BytesIO
from redbot.core import commands
from pyfiglet import figlet_format
from urllib.parse import quote
import uuid
from typing import Optional, Union
import logging

from redbot.core.data_manager import bundled_data_path, cog_data_path

from .converter import ImageFinder

log = logging.getLogger("red.trusty-cogs.NotSoBot")

try:
    import aalib

    AALIB_INSTALLED = True
except Exception:
    AALIB_INSTALLED = False

code = "```py\n{0}\n```"


def posnum(num):
    if num < 0:
        return -(num)
    else:
        return num


def find_coeffs(pa, pb):
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0] * p1[0], -p2[0] * p1[1]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1] * p1[0], -p2[1] * p1[1]])
    A = np.matrix(matrix, dtype=np.float)
    B = np.array(pb).reshape(8)
    res = np.dot(np.linalg.inv(A.T * A) * A.T, B)
    return np.array(res).reshape(8)


class DataProtocol(asyncio.SubprocessProtocol):
    def __init__(self, exit_future):
        self.exit_future = exit_future
        self.output = bytearray()

    def pipe_data_received(self, fd, data):
        self.output.extend(data)

    def process_exited(self):
        try:
            self.exit_future.set_result(True)
        except Exception:
            pass

    def pipe_connection_lost(self, fd, exc):
        try:
            self.exit_future.set_result(True)
        except Exception:
            pass

    def connection_made(self, transport):
        self.transport = transport

    def connection_lost(self, exc):
        try:
            self.exit_future.set_result(True)
        except Exception:
            pass


class NotSoBot(commands.Cog):
    """
        Rewrite of many NotSoBot commands to work on RedBot V3
    """

    def __init__(self, bot):
        self.bot = bot
        self.image_cache = {}
        self.search_cache = {}
        self.youtube_cache = {}
        self.twitch_cache = []
        self.api_count = 0
        self.emoji_map = {
            "a": "",
            "b": "",
            "c": "©",
            "d": "↩",
            "e": "",
            "f": "",
            "g": "⛽",
            "h": "♓",
            "i": "ℹ",
            "j": "" or "",
            "k": "",
            "l": "",
            "m": "Ⓜ",
            "n": "♑",
            "o": "⭕" or "",
            "p": "",
            "q": "",
            "r": "®",
            "s": "" or "⚡",
            "t": "",
            "u": "⛎",
            "v": "" or "♈",
            "w": "〰" or "",
            "x": "❌" or "⚔",
            "y": "✌",
            "z": "Ⓩ",
            "1": "1⃣",
            "2": "2⃣",
            "3": "3⃣",
            "4": "4⃣",
            "5": "5⃣",
            "6": "6⃣",
            "7": "7⃣",
            "8": "8⃣",
            "9": "9⃣",
            "0": "0⃣",
            "$": "",
            "!": "❗",
            "?": "❓",
            " ": "　",
        }
        self.retro_regex = re.compile(
            r"((https)(\:\/\/|)?u2\.photofunia\.com\/.\/results\/.\/.\/.*(\.jpg\?download))"
        )
        self.session = aiohttp.ClientSession(loop=self.bot.loop)
        self.image_mimes = ["image/png", "image/pjpeg", "image/jpeg", "image/x-icon"]
        self.gif_mimes = ["image/gif"]

    def random(self, image=False, ext: str = "png"):
        h = str(uuid.uuid4().hex)
        if image:
            return "{0}.{1}".format(h, ext)
        return h

    async def get_text(self, url: str):
        try:
            async with self.session.get(url) as resp:
                try:
                    text = await resp.text()
                    return text
                except Exception:
                    return False
        except asyncio.TimeoutError:
            return False

    async def truncate(self, channel, msg):
        if len(msg) == 0:
            return
        split = [msg[i: i + 1999] for i in range(0, len(msg), 1999)]
        try:
            for s in split:
                await channel.send(s)
                await asyncio.sleep(0.21)
        except Exception as e:
            await channel.send(e)

    async def safe_send(self, ctx, text, file, file_size):
        if not ctx.channel.permissions_for(ctx.me).send_messages:
            return
        if not ctx.channel.permissions_for(ctx.me).attach_files:
            await ctx.send("I don't have permission to attach files.")
            return
        BASE_FILESIZE_LIMIT = 8388608
        if ctx.guild and file_size < ctx.guild.filesize_limit:
            await ctx.send(content=text, file=file)
        elif not ctx.guild and file_size < BASE_FILESIZE_LIMIT:
            await ctx.send(content=text, file=file)
        else:
            await ctx.send("The contents of this command is too large to upload!")

    async def download(self, url: str, path: str):
        try:
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(path, "wb") as f:
                        f.write(data)
                    return resp.headers.get("Content-type", "").lower()
        except asyncio.TimeoutError:
            return False

    async def bytes_download(self, url: str):
        try:
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    mime = resp.headers.get("Content-type", "").lower()
                    b = BytesIO(data)
                    b.seek(0)
                    return b, mime
                else:
                    return False, False
        except asyncio.TimeoutError:
            return False, False
        except Exception:
            log.error("Error downloading to bytes", exc_info=True)
            return False, False

    async def run_process(self, code, response=False):
        try:
            transport = None
            loop = self.bot.loop
            exit_future = asyncio.Future(loop=loop)
            create = loop.subprocess_exec(
                lambda: DataProtocol(exit_future), *code, stdin=None, stderr=None
            )
            transport, protocol = await asyncio.wait_for(create, timeout=30)
            await exit_future
            if response:
                data = bytes(protocol.output)
                return True, data.decode("ascii").rstrip()
            return True, None
        except asyncio.TimeoutError:
            return False, None
        except Exception:
            log.error("Error running process", exc_info=True)
            return False, None
        finally:
            if transport:
                transport.close()

    async def gist(self, ctx, idk, content: str):
        payload = {
            "name": "NotSoBot - By: {0}.".format(ctx.message.author),
            "title": 'ASCII for text: "{0}"'.format(idk),
            "text": content,
            "private": "1",
            "lang": "python",
            "expire": "0",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post("https://spit.mixtape.moe/api/create", data=payload) as r:
                url = await r.text()
                await ctx.send("Uploaded to paste, URL: <https://spit.mixtape.moe{0}>".format(url))

    def do_magik(self, scale, img):
        try:
            list_imgs = []
            exif = {}
            exif_msg = ""
            count = 0
            i = wand.image.Image(file=img)
            i.format = "png"
            i.alpha_channel = True
            if scale < 1:
                return ":warning: `Invalid scale entered. Must be a scale between 1 and 10`", None, 0
            if scale > 10:
                return ":warning: `Invalid scale entered. Must be a scale between 1 and 10`", None, 0
            if i.size >= (3000, 3000):
                return ":warning: `Image exceeds maximum resolution >= (3000, 3000).`", None, 0
            exif.update(
                {count: (k[5:], v) for k, v in i.metadata.items() if k.startswith("exif:")}
            )
            count += 1
            i.transform(resize="800x800>")
            i.liquid_rescale(
                width=int(i.width * 0.5),
                height=int(i.height * 0.5),
                delta_x=int(0.5 * scale) if scale else 1,
                rigidity=0,
            )
            i.liquid_rescale(
                width=int(i.width * 1.5),
                height=int(i.height * 1.5),
                delta_x=scale if scale else 2,
                rigidity=0,
            )
            magikd = BytesIO()
            i.save(file=magikd)
            file_size = magikd.tell()
            magikd.seek(0)
            list_imgs.append(magikd)
            for x in exif:
                if len(exif[x]) >= 2000:
                    continue
                exif_msg += "**Exif data for image #{0}**\n".format(str(x + 1)) + code.format(
                    exif[x]
                )
            else:
                if len(exif_msg) == 0:
                    exif_msg = None
            return list_imgs[0], exif_msg, file_size
        except Exception:
            log.error("Error processing magik", exc_info=True)

    @commands.command(aliases=["imagemagic", "imagemagick", "magic", "magick", "cas", "liquid"])
    @commands.cooldown(30, 60, commands.BucketType.user)
    async def magik(self, ctx, urls: ImageFinder = None, scale: int = 2, scale_msg: str = ""):
        """Apply magik to Image(s)\n .magik image_url or .magik image_url image_url_2"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        msg = await ctx.message.channel.send("ok, processing")
        async with ctx.typing():
            b, mime = await self.bytes_download(urls[0])
            final, content_msg, file_size = await self.bot.loop.run_in_executor(
                None, self.do_magik, scale, b
            )
            if type(final) == str:
                await ctx.send(final)
                return
            if content_msg is None:
                content_msg = scale_msg
            else:
                content_msg = scale_msg + content_msg
            await msg.delete()
            file = discord.File(final, filename="magik.png")
            await self.safe_send(ctx, content_msg, file, file_size)

    def do_gmagik(self, is_owner, gif, gif_dir, rand, is_gif):
        try:
            try:
                frame = PIL.Image.open(gif)
            except Exception:
                return ":warning: Invalid Gif."
            if frame.size >= (3000, 3000):
                os.remove(gif)
                return ":warning: `GIF resolution exceeds maximum >= (3000, 3000).`"
            if is_gif:
                nframes = 0
                while frame:
                    frame.save("{0}/{1}_{2}.png".format(gif_dir, nframes, rand), "GIF")
                    nframes += 1
                    try:
                        frame.seek(nframes)
                    except EOFError:
                        break
                imgs = glob.glob(gif_dir + "*_{0}.png".format(rand))
                if (len(imgs) > 150) and not is_owner:
                    for image in imgs:
                        os.remove(image)
                    os.remove(gif)
                    return ":warning: `GIF has too many frames (>= 150 Frames).`"
                for image in imgs:
                    try:
                        im = wand.image.Image(filename=image)
                    except Exception:
                        log.error("Error running gmagik", exc_info=True)
                        continue
                    i = im.clone()
                    i.transform(resize="800x800>")
                    i.liquid_rescale(
                        width=int(i.width * 0.5), height=int(i.height * 0.5), delta_x=1, rigidity=0
                    )
                    i.liquid_rescale(
                        width=int(i.width * 1.5), height=int(i.height * 1.5), delta_x=2, rigidity=0
                    )
                    i.resize(i.width, i.height)
                    i.save(filename=image)
                return True
            else:
                frame.save("{0}/{1}_{2}.png".format(gif_dir, 0, rand), "GIF")
                for x in range(0, 30):
                    try:
                        im = wand.image.Image(filename="{0}/{1}_{2}.png".format(gif_dir, x, rand))
                    except Exception:
                        log.error("Error running gmagik", exc_info=True)
                        continue
                    i = im.clone()
                    i.transform(resize="800x800>")
                    i.liquid_rescale(
                        width=int(i.width * 0.75),
                        height=int(i.height * 0.75),
                        delta_x=1,
                        rigidity=0,
                    )
                    i.liquid_rescale(
                        width=int(i.width * 1.25),
                        height=int(i.height * 1.25),
                        delta_x=2,
                        rigidity=0,
                    )
                    i.resize(i.width, i.height)
                    i.save(filename="{0}/{1}_{2}.png".format(gif_dir, x + 1, rand))
                return True
        except Exception:
            log.error("Error processing gmagik", exc_info=True)

    @commands.command()
    @commands.cooldown(1, 20, commands.BucketType.guild)
    @commands.bot_has_permissions(attach_files=True)
    async def gmagik(self, ctx, urls: ImageFinder = None, framerate: int = None):
        """Attempt to do magik on a gif"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        gif_dir = str(bundled_data_path(self)) + "/gif/"
        if not os.path.exists(gif_dir):
            os.makedirs(gif_dir)
        x = await ctx.message.channel.send(
            "ok, processing (this might take a while for big gifs)"
        )
        rand = self.random()
        gifin = gif_dir + "1_{0}.gif".format(rand)
        gifout = gif_dir + "2_{0}.gif".format(rand)
        async with ctx.typing():
            mime = await self.download(url, gifin)
            check = mime in self.gif_mimes
            is_owner = await ctx.bot.is_owner(ctx.author)
            try:
                result = await self.bot.loop.run_in_executor(
                    None, self.do_gmagik, is_owner, gifin, gif_dir, rand, check
                )
            except Exception:
                log.error("Error running gmagik", exc_info=True)
                await ctx.send(":warning: Gmagik failed...")
                return
            if type(result) == str:
                await ctx.send(result)
                return
            if framerate:
                if framerate > 60:
                    framerate = 60
                elif framerate < 0:
                    framerate = 20
                else:
                    framerate = framerate
                args = [
                    "ffmpeg",
                    "-y",
                    "-nostats",
                    "-loglevel",
                    "0",
                    "-i",
                    gif_dir + "%d_{0}.png".format(rand),
                    "-r",
                    framerate,
                    gifout,
                ]
            else:
                args = [
                    "ffmpeg",
                    "-y",
                    "-nostats",
                    "-loglevel",
                    "0",
                    "-i",
                    gif_dir + "%d_{0}.png".format(rand),
                    gifout,
                ]
            worked, response = await self.run_process(args, True)
            if not worked:
                return await ctx.send(
                    "`Error in command 'gmagik'. Check your console or logs for details.`"
                )
            file_size = os.path.getsize(gifout)
            file = discord.File(gifout, filename="gmagik.gif")
            await self.safe_send(ctx, None, file, file_size)
            # await ctx.send(file=file)
            for image in glob.glob(gif_dir + "*_{0}.png".format(rand)):
                os.remove(image)
            os.remove(gifin)
            os.remove(gifout)
            await x.delete()

    @commands.command()
    @commands.bot_has_permissions(attach_files=True)
    async def caption(
        self,
        ctx,
        urls: Optional[ImageFinder] = None,
        text: str = "Caption",
        color: str = "white",
        size: int = 40,
        x: int = 0,
        y: int = 0,
    ):
        """
            Add caption to an image

            `[urls]` are the image urls or users or previous images in chat to add a caption to.
            `[text=Caption]` is the text to caption on the image.
            `[color=white]` is the color of the text.
            `[size=40]` is the size of the text
            `[x=0]` is the height the text starts at between 0 and 100% where 0 is the top and 100 is the bottom of the image.
            `[y=0]` is the width the text starts at between 0 and 100% where 0 is the left and 100 is the right of the image.
        """
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        if url is None:
            await ctx.send(
                "Error: Invalid Syntax\n`.caption <image_url> <text>**"
                " <color>* <size>* <x>* <y>*`\n`* = Optional`\n`** = Wrap text in quotes`"
            )
            return
        async with ctx.typing():
            xx = await ctx.message.channel.send("ok, processing")
            b, mime = await self.bytes_download(url)
            is_gif = mime in self.gif_mimes
            font_path = str(bundled_data_path(self)) + "/arial.ttf"
            color = wand.color.Color(color)
            font = wand.font.Font(path=font_path, size=size, color=color)
            if x > 100:
                x = 100
            if x < 0:
                x = 0
            if y > 100:
                y = 100
            if y < 0:
                y = 0

            def make_caption_image(b, text, color, font, x, y, is_gif):
                final = BytesIO()
                with wand.image.Image(file=b) as img:

                    i = img.clone()
                    x = int(i.height*(x*0.01))
                    y = int(i.width*(y*0.01))
                    if not is_gif:
                        i.caption(str(text), left=x, top=y, font=font)
                    else:
                        with wand.image.Image() as new_image:
                            for frame in img.sequence:
                                frame.caption(str(text), left=x, top=y, font=font)
                                new_image.sequence.append(frame)
                            new_image.save(file=final)
                    i.save(file=final)
                file_size = final.tell()
                final.seek(0)
                filename = f"caption.{'png' if not is_gif else 'gif'}"
                return discord.File(final, filename=filename), file_size

            await xx.delete()
            file, file_size = await ctx.bot.loop.run_in_executor(
                None, make_caption_image, b, text, color, font, x, y, is_gif
            )
            await ctx.send(file=file)

    @commands.command()
    @commands.cooldown(1, 5)
    @commands.bot_has_permissions(attach_files=True)
    async def triggered(self, ctx, urls: ImageFinder = None):
        """Generate a Triggered Gif for a User or Image"""
        if urls is None:
            urls = [ctx.author.avatar_url_as(format="png")]
        avatar = urls[0]
        path = str(bundled_data_path(self) / self.random(True))
        path2 = path[:-3] + "gif"
        async with ctx.typing():
            await self.download(str(avatar), path)
            t_path = str(bundled_data_path(self) / "zDAY2yo.jpg")
            await self.download("https://i.imgur.com/zDAY2yo.jpg", t_path)
            args = [
                    "convert",
                    "canvas:none",
                    "-size",
                    "512x680!",
                    "-resize",
                    "512x680!",
                    "-draw",
                    'image over -60,-60 640,640 "{0}"'.format(path),
                    "-draw",
                    'image over 0,586 0,0 "{0}"'.format(t_path),
                    "-dispose",
                    "background",
                    "(",
                    "canvas:none",
                    "-size",
                    "512x680!",
                    "-draw",
                    'image over -45,-50 640,640 "{0}"'.format(path),
                    "-draw",
                    'image over 0,586 0,0 "{0}"'.format(t_path),
                    ")",
                    "(",
                    "canvas:none",
                    "-size",
                    "512x680!",
                    "-draw",
                    'image over -50,-45 640,640 "{0}"'.format(path),
                    "-draw",
                    'image over 0,586 0,0 "{0}"'.format(t_path),
                    "-dispose",
                    "background",
                    ")",
                    "(",
                    "canvas:none",
                    "-size",
                    "512x680!",
                    "-draw",
                    'image over -45,-65 640,640 "{0}"'.format(path),
                    "-draw",
                    'image over 0,586 0,0 "{0}"'.format(t_path),
                    "-dispose",
                    "background",
                    ")",
                    "-layers",
                    "Optimize",
                    "-set",
                    "delay",
                    "2",
                    path2,
                ]
            worked, response = await self.run_process(args, True)
            log.info(response)
            if not worked:
                return await ctx.send(
                    "`Error in command 'triggered'. Check your console or logs for details.`"
                )
            file = discord.File(path2, filename="/triggered.gif")
            file_size = os.path.getsize(path2)
            await self.safe_send(ctx, None, file, file_size)
            os.remove(path)
            os.remove(path2)

    @commands.command(aliases=["aes"])
    @commands.bot_has_permissions(attach_files=True)
    async def aesthetics(self, ctx, *, text: str):
        """Returns inputed text in aesthetics"""
        final = ""
        pre = " ".join(text)
        for char in pre:
            if not ord(char) in range(33, 127):
                final += char
                continue
            final += chr(ord(char) + 65248)
        await self.truncate(ctx.message.channel, final)

    def do_ascii(self, text):
        try:
            i = PIL.Image.new("RGB", (2000, 1000))
            img = PIL.ImageDraw.Draw(i)
            txt = figlet_format(text, font="starwars")
            img.text((20, 20), figlet_format(text, font="starwars"), fill=(0, 255, 0))
            text_width, text_height = img.textsize(figlet_format(text, font="starwars"))
            imgs = PIL.Image.new("RGB", (text_width + 30, text_height))
            ii = PIL.ImageDraw.Draw(imgs)
            ii.text((20, 20), figlet_format(text, font="starwars"), fill=(0, 255, 0))
            text_width, text_height = ii.textsize(figlet_format(text, font="starwars"))
            final = BytesIO()
            imgs.save(final, "png")
            file_size = final.tell()
            final.seek(0)
            return final, txt, file_size
        except Exception:
            return False, False

    @commands.command(aliases=["expand"])
    @commands.cooldown(1, 5)
    @commands.bot_has_permissions(attach_files=True)
    async def ascii(self, ctx, *, text: str):
        """Convert text into ASCII"""
        if len(text) > 1000:
            await ctx.send("Text is too long!")
            return
        if text == "donger" or text == "dong":
            text = "8====D"
        async with ctx.typing():
            final, txt, file_size = await self.bot.loop.run_in_executor(None, self.do_ascii, text)
            if final is False:
                await ctx.send(":no_entry: go away with your invalid characters.")
                return
            if len(txt) >= 1999:
                await self.gist(ctx, text, txt)
                msg = None
            elif len(txt) <= 600:
                msg = "```fix\n{0}```".format(txt)
            else:
                msg = None
            file = discord.File(final, filename="ascii.png")
            await self.safe_send(ctx, msg, file, file_size)

    def generate_ascii(self, image):
        font = PIL.ImageFont.truetype(
            str(cog_data_path(self)) + "/FreeMonoBold.ttf", 15
        )
        image_width, image_height = image.size
        aalib_screen_width = int(image_width / 24.9) * 10
        aalib_screen_height = int(image_height / 41.39) * 10
        screen = aalib.AsciiScreen(width=aalib_screen_width, height=aalib_screen_height)

        im = image.convert("L").resize(screen.virtual_size)
        screen.put_image((0, 0), im)
        y = 0
        how_many_rows = len(screen.render().splitlines())
        new_img_width, font_size = font.getsize(screen.render().splitlines()[0])
        img = PIL.Image.new("RGBA", (new_img_width, how_many_rows * 15), (255, 255, 255))
        draw = PIL.ImageDraw.Draw(img)
        for lines in screen.render().splitlines():
            draw.text((0, y), lines, (0, 0, 0), font=font)
            y += 15
        imagefit = PIL.ImageOps.fit(img, (image_width, image_height), PIL.Image.ANTIALIAS)
        return imagefit

    async def check_font_file(self):
        try:
            PIL.ImageFont.truetype(cog_data_path(self)/"FreeMonoBold.ttf", 15)
        except Exception:
            async with self.session.get(
                "https://github.com/opensourcedesign/fonts"
                "/raw/master/gnu-freefont_freemono/FreeMonoBold.ttf"
            ) as resp:
                data = await resp.read()
            with open(cog_data_path(self)/"FreeMonoBold.ttf", "wb") as save_file:
                save_file.write(data)

    @commands.command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.check(lambda ctx: AALIB_INSTALLED)
    @commands.bot_has_permissions(attach_files=True)
    async def iascii(self, ctx, urls: ImageFinder = None):
        """Generate an ascii art image of last image in chat or from URL"""
        if not AALIB_INSTALLED:
            await ctx.send("aalib couldn't be found on this machine!")
            return
        await self.check_font_file()
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        x = await ctx.send("ok, processing")
        async with ctx.typing():
            b, mime = await self.bytes_download(url)
            if b is False:
                await ctx.send(":warning: **Command download function failed...**")
                return
            im = PIL.Image.open(b)
            img = await self.bot.loop.run_in_executor(None, self.generate_ascii, im)
            final = BytesIO()
            img.save(final, "png")
            file_size = final.tell()
            final.seek(0)
            await x.delete()
            file = discord.File(final, filename="iascii.png")
            await self.safe_send(ctx, None, file, file_size)

    def do_gascii(self, b):
        img_list = []
        temp = BytesIO()
        try:
            try:
                image = PIL.Image.open(b)
                gif_list = [frame.copy() for frame in ImageSequence.Iterator(image)]
            except IOError:
                return ":warning: Cannot load gif."
            count = 0
            try:
                for frame in gif_list[:20]:
                    im = frame.copy()
                    new_im = self.generate_ascii(im)
                    img_list.append(new_im)
                    count += 1

            except EOFError:
                pass
            temp = BytesIO()
            new_im.save(
                temp, format="GIF", save_all=True, append_images=img_list, duration=0, loop=0
            )
            return temp
        except Exception:
            log.error("Error running gascii", exc_info=True)

    @commands.command()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    @commands.check(lambda ctx: AALIB_INSTALLED)
    @commands.bot_has_permissions(attach_files=True)
    async def gascii(self, ctx, urls: ImageFinder = None):
        """Gif to ASCII"""
        if not AALIB_INSTALLED:
            await ctx.send("aalib couldn't be found on this machine!")
            return
        await self.check_font_file()
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        x = await ctx.message.channel.send("ok, processing")
        async with ctx.typing():

            b, mime = await self.bytes_download(url)
            result = self.bot.loop.run_in_executor(None, self.do_gascii, b)
            try:
                result = await asyncio.wait_for(result, timeout=60)
            except asyncio.TimeoutError:
                return
            if type(result) == str:
                await ctx.send(result)
                return
            file_size = result.tell()
            result.seek(0)
            await x.delete()
            file = discord.File(result, filename="gascii.gif")
            await self.safe_send(ctx, None, file, file_size)

    @commands.command()
    @commands.bot_has_permissions(attach_files=True)
    async def rip(self, ctx, name: str = None, *, text: str = None):
        """Generate tombstone image with name and optional text"""
        if name is None:
            name = ctx.message.author.name
        if len(ctx.message.mentions) >= 1:
            name = ctx.message.mentions[0].name
        if text:
            if len(text) > 22:
                one = text[:22]
                two = text[22:]
                url = "http://www.tombstonebuilder.com/generate.php?top1=R.I.P&top3={0}&top4={1}&top5={2}".format(
                    name, one, two
                ).replace(
                    " ", "%20"
                )
            else:
                url = "http://www.tombstonebuilder.com/generate.php?top1=R.I.P&top3={0}&top4={1}".format(
                    name, text
                ).replace(
                    " ", "%20"
                )
        else:
            if name[-1].lower() != "s":
                name += "'s"
            url = "http://www.tombstonebuilder.com/generate.php?top1=R.I.P&top3={0}&top4=Hopes and Dreams".format(
                name
            ).replace(
                " ", "%20"
            )
        b, mime = await self.bytes_download(url)
        file = discord.File(b, filename="rip.png")
        await ctx.send(file=file)

    @commands.command()
    @commands.cooldown(1, 5)
    @commands.bot_has_permissions(attach_files=True)  # ImageFinder consumes rest this is so goat'd
    async def merge(self, ctx, vertical: Optional[bool] = True, *, urls: Optional[ImageFinder]):
        """Merge/Combine Two Photos"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        if not urls:
            return await ctx.send("No images found.")
        async with ctx.typing():
            if len(urls) == 1:
                await ctx.send("You gonna merge one image?")
                return
            xx = await ctx.message.channel.send("ok, processing")
            count = 0
            list_im = []
            for url in urls:
                count += 1
                b, mime = await self.bytes_download(str(url))
                if sys.getsizeof(b) == 215:
                    await ctx.send(":no_entry: Image `{0}` is invalid!".format(str(count)))
                    continue
                list_im.append(b)
            imgs = [PIL.Image.open(i).convert("RGBA") for i in list_im]
            if vertical:
                # Vertical
                max_shape = sorted([(np.sum(i.size), i.size) for i in imgs])[1][1]
                imgs_comb = np.vstack((np.asarray(i.resize(max_shape)) for i in imgs))
            else:
                # Horizontal
                min_shape = sorted([(np.sum(i.size), i.size) for i in imgs])[0][1]
                imgs_comb = np.hstack((np.asarray(i.resize(min_shape)) for i in imgs))
            imgs_comb = PIL.Image.fromarray(imgs_comb)
            final = BytesIO()
            imgs_comb.save(final, "png")
            file_size = final.tell()
            final.seek(0)
            await xx.delete()
            file = discord.File(final, filename="merge.png")
            await self.safe_send(ctx, None, file, file_size)

    @commands.command(aliases=["cancerify", "em"])
    async def emojify(self, ctx, *, txt: str):
        """Replace characters in text with emojis"""
        txt = txt.lower()
        msg = ""
        for s in txt:
            if s in self.emoji_map:
                msg += "{0}".format(self.emoji_map[s])
            else:
                msg += s
        await ctx.send(msg)

    async def get_colour(self, channel):
        try:
            if await self.bot.db.guild(channel.guild).use_bot_color():
                return channel.guild.me.colour
            else:
                return await self.bot.db.color()
        except AttributeError:
            return await self.bot.get_embed_colour(channel)

    @commands.command(aliases=["text2img", "texttoimage", "text2image"])
    @commands.bot_has_permissions(attach_files=True)
    async def tti(self, ctx, *, txt: str):
        """Generate an image of text"""
        api = "http://api.img4me.com/?font=arial&fcolor=FFFFFF&size=35&type=png&text={0}".format(
            quote(txt)
        )
        async with ctx.typing():
            r = await self.get_text(api)
            b, mime = await self.bytes_download(r)
            file = discord.File(b, filename="tti.png")
            await ctx.send(file=file)

    @commands.command(aliases=["comicsans"])
    @commands.bot_has_permissions(attach_files=True)
    async def sans(self, ctx, *, txt: str):
        """Generate an image of text with comicsans"""
        api = "http://api.img4me.com/?font=comic&fcolor=000000&size=35&type=png&text={0}".format(
            quote(txt)
        )
        async with ctx.typing():
            r = await self.get_text(api)
            b, mime = await self.bytes_download(r)
            file = discord.File(b, filename="tti.png")
            await ctx.send(file=file)

    @commands.command(aliases=["needsmorejpeg", "jpegify", "magik2"])
    @commands.cooldown(2, 5, commands.BucketType.user)
    @commands.bot_has_permissions(attach_files=True)
    async def jpeg(self, ctx, urls: Optional[ImageFinder] = None, quality: int = 1):
        """
        Add more JPEG to an Image

        Needs More JPEG!
        `[urls]` is optional, if not provided will search chat for a valid image.
        `[quality]` is the quality of the new jpeg image to make
        """
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        if quality > 10:
            quality = 10
        elif quality < 1:
            quality = 1
        async with ctx.typing():
            b, mime = await self.bytes_download(url)
            if b is False:
                await ctx.send(":warning: **Command download function failed...**")
                return

            def make_jpeg(b):
                img = PIL.Image.open(b).convert("RGB")
                final = BytesIO()
                img.save(final, "JPEG", quality=quality)
                file_size = final.tell()
                final.seek(0)
                return discord.File(final, filename="needsmorejpeg.jpg"), file_size
            file, file_size = await ctx.bot.loop.run_in_executor(None, make_jpeg, b)
            await self.safe_send(ctx, None, file, file_size)

    def do_vw(self, b, txt):
        im = PIL.Image.open(b)
        k = random.randint(0, 100)
        im = macintoshplus.draw_method1(k, txt, im)
        final = BytesIO()
        im.save(final, "png")
        file_size = final.tell()
        final.seek(0)
        return final, file_size

    @commands.command(aliases=["vaporwave", "vape", "vapewave"])
    @commands.cooldown(2, 5)
    @commands.bot_has_permissions(attach_files=True)
    async def vw(self, ctx, urls: ImageFinder = None, *, txt: str = None):
        """Add vaporwave flavours to an image"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        if txt is None:
            txt = "vapor wave"
        b, mime = await self.bytes_download(url)
        try:
            final, file_size = await self.bot.loop.run_in_executor(None, self.do_vw, b, txt)
        except Exception:
            return await ctx.send("That image cannot be vaporwaved.")
        file = discord.File(final, filename="vapewave.png")
        await self.safe_send(ctx, None, file, file_size)

    @commands.command(aliases=["achievement"])
    @commands.bot_has_permissions(attach_files=True)
    async def minecraftachievement(self, ctx, *, txt: str):
        """Generate a Minecraft Achievement"""
        api = "https://mcgen.herokuapp.com/a.php?i=1&h=Achievement-{0}&t={1}".format(
            ctx.message.author.name, txt
        )
        b, mime = await self.bytes_download(api)
        i = 0
        while sys.getsizeof(b) == 88 and i != 10:
            b, mime = await self.bytes_download(api)
            if sys.getsizeof(b) != 0:
                i = 10
            else:
                i += 1
        if i == 10 and sys.getsizeof(b) == 88:
            await ctx.send("Minecraft Achievement Generator API is bad, pls try again")
            return
        file = discord.File(b, filename="achievement.png")
        await ctx.send(file=file)

    @commands.command(aliases=["wm"])
    @commands.bot_has_permissions(attach_files=True)
    async def watermark(
        self,
        ctx,
        urls: ImageFinder = None,
        mark: str = None,
        x: int = 0,
        y: int = 0,
        transparency: Union[int, float] = 0
    ):
        """
            Add a watermark to an image

            `[urls]` are the image urls or users or previous images in chat to add a watermark to.
            `[mark]` is the image to use as the watermark. By default the brazzers icon is used.
            `[x=0]` is the height the watermark will be at between 0 and 100% where 0 is the top and 100 is the bottom of the image.
            `[y=0]` is the width the watermark will be at between 0 and 100% where 0 is the left and 100 is the right of the image.
            `[transparency=0]` is a value from 0 to 100 which determines the percentage the watermark will be transparent.
        """
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            if x > 100:
                x = 100
            if x < 0:
                x = 0
            if y > 100:
                y = 100
            if y < 0:
                y = 0
            if transparency > 1 and transparency < 100:
                transparency = transparency * 0.01
            if transparency < 0:
                transparency = 0
            if transparency > 100:
                transparency = 1
            b, mime = await self.bytes_download(url)
            is_gif = mime in self.gif_mimes
            if mime not in self.image_mimes + self.gif_mimes:
                return await ctx.send("That is not a valid image.")
            if mark == "brazzers" or mark is None:
                wmm, mime = await self.bytes_download("https://i.imgur.com/YAb1RMZ.png")
                wmm.name = "watermark.png"
                wm_gif = False
            else:
                wmm, mime = await self.bytes_download(mark)
                wm_gif = mime in self.gif_mimes
                wmm.name = "watermark.png"
                if wm_gif:
                    wmm.name = "watermark.gif"

            def add_watermark(b, wmm, x, y, transparency, is_gif=False, wm_gif=False):
                final = BytesIO()
                with wand.image.Image(file=b) as img:

                    if not is_gif and not wm_gif:
                        log.debug("There are no gifs")
                        with img.clone() as new_img:
                            new_img.transform(resize="65536@")
                            final_x = int(new_img.height*(x*0.01))
                            final_y = int(new_img.width*(y*0.01))
                            with wand.image.Image(file=wmm) as wm:
                                new_img.watermark(
                                    image=wm,
                                    left=final_x,
                                    top=final_y,
                                    transparency=transparency
                                )
                            new_img.save(file=final)

                    elif is_gif and not wm_gif:
                        log.debug("The base image is a gif")
                        wm = wand.image.Image(file=wmm)
                        with wand.image.Image() as new_image:
                            with img.clone() as new_img:
                                for frame in new_img.sequence:
                                    frame.transform(resize="65536@")
                                    final_x = int(frame.height*(x*0.01))
                                    final_y = int(frame.width*(y*0.01))
                                    frame.watermark(
                                        image=wm,
                                        left=final_x,
                                        top=final_y,
                                        transparency=transparency
                                    )
                                    new_image.sequence.append(frame)
                            new_image.save(file=final)

                    else:
                        log.debug("The mark is a gif")
                        with wand.image.Image() as new_image:
                            with wand.image.Image(file=wmm) as new_img:
                                for frame in new_img.sequence:
                                    with img.clone() as clone:
                                        if is_gif:
                                            clone = clone.sequence[0]
                                            # we only care about the first frame of the gif in this case
                                        else:
                                            clone = clone.convert("gif")

                                        clone.transform(resize="65536@")
                                        final_x = int(clone.height*(x*0.01))
                                        final_y = int(clone.width*(y*0.01))
                                        clone.watermark(
                                            image=frame,
                                            left=final_x,
                                            top=final_y,
                                            transparency=transparency
                                        )
                                        new_image.sequence.append(clone)
                                        new_image.dispose = "background"
                                        with new_image.sequence[-1] as new_frame:
                                            new_frame.delay = frame.delay

                            new_image.save(file=final)

                size = final.tell()
                final.seek(0)
                filename = f"watermark.{'gif' if is_gif or wm_gif else 'png'}"
                return discord.File(final, filename=filename), size

            file, file_size = await ctx.bot.loop.run_in_executor(
                None, add_watermark, b, wmm, x, y, transparency, is_gif, wm_gif
            )
            await self.safe_send(ctx, None, file, file_size)

    def do_glitch(self, b, amount, seed, iterations):
        img = PIL.Image.open(b)
        img = img.convert("RGB")
        b = BytesIO()
        img.save(b, format="JPEG")
        b.seek(0)
        img = jpglitch.Jpeg(bytearray(b.getvalue()), amount, seed, iterations)
        final = BytesIO()
        final.name = "glitch.jpg"
        img.save_image(final)
        file_size = final.tell()
        final.seek(0)
        return final, file_size

    def do_gglitch(self, b):
        b = bytearray(b.getvalue())
        for x in range(0, sys.getsizeof(b)):
            if b[x] == 33:
                if b[x + 1] == 255:
                    end = x
                    break
                elif b[x + 1] == 249:
                    end = x
                    break
        for x in range(13, end):
            b[x] = random.randint(0, 255)
        return BytesIO(b)

    @commands.command(aliases=["jpglitch"])
    @commands.cooldown(10, 15)
    @commands.bot_has_permissions(attach_files=True)
    async def glitch(
        self,
        ctx,
        urls: ImageFinder = None,
        iterations: int = None,
        amount: int = None,
        seed: int = None,
    ):
        """Glitch a gif or png"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            if iterations is None:
                iterations = random.randint(1, 30)
            if amount is None:
                amount = random.randint(1, 20)
            elif amount > 99:
                amount = 99
            if seed is None:
                seed = random.randint(1, 20)
            b, mime = await self.bytes_download(url)
            gif = mime in self.gif_mimes
            if not gif:
                final, file_size = await self.bot.loop.run_in_executor(
                    None, self.do_glitch, b, amount, seed, iterations
                )
                file = discord.File(final, filename="glitch.jpeg")
                msg = f"Iterations: `{iterations}` | Amount: `{amount}` | Seed: `{seed}`"
                await self.safe_send(ctx, msg, file, file_size)
            else:
                final = await self.bot.loop.run_in_executor(None, self.do_gglitch, b)
                file = discord.File(final, filename="glitch.gif")
                await self.safe_send(ctx, None, file, final.tell())

    @commands.command()
    @commands.bot_has_permissions(attach_files=True)
    async def glitch2(self, ctx, urls: ImageFinder = None):
        """Glitch a jpegs"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            path = str(bundled_data_path(self)) + "/" + self.random(True)
            await self.download(url, path)
            args = [
                "convert",
                "(",
                path,
                "-resize",
                "1024x1024>",
                ")",
                "-alpha",
                "on",
                "(",
                "-clone",
                "0",
                "-channel",
                "RGB",
                "-separate",
                "-channel",
                "A",
                "-fx",
                "0",
                "-compose",
                "CopyOpacity",
                "-composite",
                ")",
                "(",
                "-clone",
                "0",
                "-roll",
                "+5",
                "-channel",
                "R",
                "-fx",
                "0",
                "-channel",
                "A",
                "-evaluate",
                "multiply",
                ".3",
                ")",
                "(",
                "-clone",
                "0",
                "-roll",
                "-5",
                "-channel",
                "G",
                "-fx",
                "0",
                "-channel",
                "A",
                "-evaluate",
                "multiply",
                ".3",
                ")",
                "(",
                "-clone",
                "0",
                "-roll",
                "+0+5",
                "-channel",
                "B",
                "-fx",
                "0",
                "-channel",
                "A",
                "-evaluate",
                "multiply",
                ".3",
                ")",
                "(",
                "-clone",
                "0",
                "-channel",
                "A",
                "-fx",
                "0",
                ")",
                "-delete",
                "0",
                "-background",
                "none",
                "-compose",
                "SrcOver",
                "-layers",
                "merge",
                "-rotate",
                "90",
                "-wave",
                "1x5",
                "-rotate",
                "-90",
                path,
            ]
            worked, response = await self.run_process(args, True)
            if not worked:
                return await ctx.send(
                    "`Error in command 'glitch2'. Check your console or logs for details.`"
                )
            file = discord.File(path, filename="glitch2.png")
            file_size = os.path.getsize(path)
            await self.safe_send(ctx, None, file, file_size)
            os.remove(path)

    @commands.command(aliases=["pixel"])
    @commands.bot_has_permissions(attach_files=True)
    async def pixelate(self, ctx, urls: ImageFinder = None, pixels=None, scale_msg=None):
        """Picelate an image"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            img_urls = urls[0]
            if pixels is None:
                pixels = 9
            if scale_msg is None:
                scale_msg = ""
            b, mime = await self.bytes_download(url)
            if b is False:
                if len(img_urls) > 1:
                    await ctx.send(":warning: **Command download function failed...**")
                    return
            file, file_size = await ctx.bot.loop.run_in_executor(
                None, self.make_pixel, b, pixels, scale_msg
            )
            await self.safe_send(ctx, scale_msg, file, file_size)

    def make_pixel(self, b, pixels, scale_msg):
        bg = (0, 0, 0)
        img = PIL.Image.open(b)
        img = img.resize(
            (int(img.size[0] / pixels), int(img.size[1] / pixels)), PIL.Image.NEAREST
        )
        img = img.resize(
            (int(img.size[0] * pixels), int(img.size[1] * pixels)), PIL.Image.NEAREST
        )
        load = img.load()
        for i in range(0, img.size[0], pixels):
            for j in range(0, img.size[1], pixels):
                for r in range(pixels):
                    load[i + r, j] = bg
                    load[i, j + r] = bg
        final = BytesIO()
        img.save(final, "png")
        file_size = final.tell()
        final.seek(0)
        return discord.File(final, filename="pixelated.png"), file_size

    async def do_retro(self, text, bcg):
        if "|" not in text:
            if len(text) >= 15:
                text = [text[i: i + 15] for i in range(0, len(text), 15)]
            else:
                split = text.split()
                if len(split) == 1:
                    text = [x for x in text]
                    if len(text) == 4:
                        text[2] = text[2] + text[-1]
                        del text[3]
                else:
                    text = split
        else:
            text = text.split("|")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:43.0) Gecko/20100101 Firefox/43.0"
        }
        payload = aiohttp.FormData()
        payload.add_field("current-category", "all_effects")
        payload.add_field("bcg", bcg)
        payload.add_field("txt", "4")
        count = 1
        for s in text:
            if count > 3:
                break
            payload.add_field("text" + str(count), s.replace("'", '"'))
            count += 1
        try:
            async with self.session.post(
                "https://photofunia.com/effects/retro-wave?guild=3", data=payload, headers=headers
            ) as r:
                txt = await r.text()
        except Exception:
            return
        match = self.retro_regex.findall(txt)
        if match:
            download_url = match[0][0]
            b, mime = await self.bytes_download(download_url)
            return b
        return False

    @commands.command()
    @commands.bot_has_permissions(attach_files=True)
    async def retro(self, ctx, *, text: str):
        """Create a retro looking image"""
        async with ctx.typing():
            retro_result = await self.do_retro(text, "5")
            if retro_result is False:
                await ctx.send(":warning: This text contains unsupported characters")
            else:
                file = discord.File(retro_result, filename="retro.png")
                await ctx.send(file=file)

    @commands.command()
    @commands.bot_has_permissions(attach_files=True)
    async def retro2(self, ctx, *, text: str):
        """Create a retro looking image"""
        async with ctx.typing():
            retro_result = await self.do_retro(text, "2")
            if retro_result is False:
                await ctx.send(":warning: This text contains unsupported characters")
            else:
                file = discord.File(retro_result, filename="retro.png")
                await ctx.send(file=file)

    @commands.command()
    @commands.bot_has_permissions(attach_files=True)
    async def retro3(self, ctx, *, text: str):
        """Create a retro looking image"""
        async with ctx.typing():
            retro_result = await self.do_retro(text, "4")
            if retro_result is False:
                await ctx.send(":warning: This text contains unsupported characters")
            else:
                file = discord.File(retro_result, filename="retro.png")
                await ctx.send(file=file)

    def do_waaw(self, b):
        f = BytesIO()
        f2 = BytesIO()
        with wand.image.Image(file=b) as img:
            h1 = img.clone()
            width = int(img.width / 2) if int(img.width / 2) > 0 else 1
            h1.crop(width=width, height=int(img.height), gravity="east")
            h2 = h1.clone()
            h1.rotate(degree=180)
            h1.flip()
            h1.save(file=f)
            h2.save(file=f2)
        f.seek(0)
        f2.seek(0)
        list_im = [f2, f]
        imgs = [PIL.ImageOps.mirror(PIL.Image.open(i).convert("RGBA")) for i in list_im]
        min_shape = sorted([(np.sum(i.size), i.size) for i in imgs])[0][1]
        imgs_comb = np.hstack([np.asarray(i.resize(min_shape)) for i in imgs])
        imgs_comb = PIL.Image.fromarray(imgs_comb)
        final = BytesIO()
        imgs_comb.save(final, "png")
        file_size = final.tell()
        final.seek(0)
        return final, file_size

    # Thanks to Iguniisu#9746 for the idea
    @commands.command(aliases=["magik3", "mirror"])
    @commands.cooldown(30, 60, commands.BucketType.user)
    @commands.bot_has_permissions(attach_files=True)
    async def waaw(self, ctx, urls: ImageFinder = None):
        """Mirror an image vertically right to left"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            b, mime = await self.bytes_download(url)
            if b is False:
                await ctx.send(":warning: **Command download function failed...**")
                return
            final, file_size = await self.bot.loop.run_in_executor(None, self.do_waaw, b)
            file = discord.File(final, filename="waaw.png")
            await self.safe_send(ctx, None, file, file_size)

    def do_haah(self, b):
        f = BytesIO()
        f2 = BytesIO()
        with wand.image.Image(file=b) as img:
            h1 = img.clone()
            h1.transform("50%x100%")
            h2 = h1.clone()
            h2.rotate(degree=180)
            h2.flip()
            h1.save(file=f)
            h2.save(file=f2)
        f.seek(0)
        f2.seek(0)
        list_im = [f2, f]
        imgs = [PIL.ImageOps.mirror(PIL.Image.open(i).convert("RGBA")) for i in list_im]
        min_shape = sorted([(np.sum(i.size), i.size) for i in imgs])[0][1]
        imgs_comb = np.hstack([np.asarray(i.resize(min_shape)) for i in imgs])
        imgs_comb = PIL.Image.fromarray(imgs_comb)
        final = BytesIO()
        imgs_comb.save(final, "png")
        file_size = final.tell()
        final.seek(0)
        return final, file_size

    @commands.command(aliases=["magik4", "mirror2"])
    @commands.cooldown(30, 60, commands.BucketType.user)
    @commands.bot_has_permissions(attach_files=True)
    async def haah(self, ctx, urls: ImageFinder = None):
        """Mirror an image vertically left to right"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            b, mime = await self.bytes_download(url)
            if b is False:
                await ctx.send(":warning: **Command download function failed...**")
                return
            final, file_size = await self.bot.loop.run_in_executor(None, self.do_haah, b)
            file = discord.File(final, filename="haah.png")
            await self.safe_send(ctx, None, file, file_size)

    def do_woow(self, b):
        f = BytesIO()
        f2 = BytesIO()
        with wand.image.Image(file=b) as img:
            h1 = img.clone()
            width = int(img.width) if int(img.width) > 0 else 1
            h1.crop(width=width, height=int(img.height / 2), gravity="north")
            h2 = h1.clone()
            h2.rotate(degree=180)
            h2.flop()
            h1.save(file=f)
            h2.save(file=f2)
        f.seek(0)
        f2.seek(0)
        list_im = [f, f2]
        imgs = [PIL.Image.open(i).convert("RGBA") for i in list_im]
        min_shape = sorted([(np.sum(i.size), i.size) for i in imgs])[0][1]
        imgs_comb = np.vstack([np.asarray(i.resize(min_shape)) for i in imgs])
        imgs_comb = PIL.Image.fromarray(imgs_comb)
        final = BytesIO()
        imgs_comb.save(final, "png")
        file_size = final.tell()
        final.seek(0)
        return final, file_size

    @commands.command(aliases=["magik5", "mirror3"])
    @commands.cooldown(30, 60, commands.BucketType.user)
    @commands.bot_has_permissions(attach_files=True)
    async def woow(self, ctx, urls: ImageFinder = None):
        """Mirror an image horizontally top to bottom"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            b, mime = await self.bytes_download(url)
            if b is False:
                await ctx.send(":warning: **Command download function failed...**")
                return
            final, file_size = await self.bot.loop.run_in_executor(None, self.do_woow, b)
            file = discord.File(final, filename="woow.png")
            await self.safe_send(ctx, None, file, file_size)

    def do_hooh(self, b):
        f = BytesIO()
        f2 = BytesIO()
        with wand.image.Image(file=b) as img:
            h1 = img.clone()
            width = int(img.width) if int(img.width) > 0 else 1
            h1.crop(width=width, height=int(img.height / 2), gravity="south")
            h2 = h1.clone()
            h1.rotate(degree=180)
            h2.flop()
            h1.save(file=f)
            h2.save(file=f2)
        f.seek(0)
        f2.seek(0)
        list_im = [f, f2]
        imgs = [PIL.Image.open(i).convert("RGBA") for i in list_im]
        min_shape = sorted([(np.sum(i.size), i.size) for i in imgs])[0][1]
        imgs_comb = np.vstack([np.asarray(i.resize(min_shape)) for i in imgs])
        imgs_comb = PIL.Image.fromarray(imgs_comb)
        final = BytesIO()
        imgs_comb.save(final, "png")
        file_size = final.tell()
        final.seek(0)
        return final, file_size

    @commands.command(aliases=["magik6", "mirror4"])
    @commands.cooldown(30, 60, commands.BucketType.user)
    @commands.bot_has_permissions(attach_files=True)
    async def hooh(self, ctx, urls: ImageFinder = None):
        """Mirror an image horizontally bottom to top"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            b, mime = await self.bytes_download(url)
            if b is False:
                await ctx.send(":warning: **Command download function failed...**")
                return
            final, file_size = await self.bot.loop.run_in_executor(None, self.do_hooh, b)
            file = discord.File(final, filename="hooh.png")
            await self.safe_send(ctx, None, file, file_size)

    @commands.command()
    @commands.bot_has_permissions(attach_files=True)
    async def flipimg(self, ctx, urls: ImageFinder = None):
        """Rotate an image 180 degrees"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            b, mime = await self.bytes_download(url)

            def flip_img(b):
                img = PIL.Image.open(b)
                img = PIL.ImageOps.flip(img)
                final = BytesIO()
                img.save(final, "png")
                file_size = final.tell()
                final.seek(0)
                return discord.File(final, filename="flip.png"), file_size

            file, file_size = await ctx.bot.loop.run_in_executor(None, flip_img, b)
            await self.safe_send(ctx, None, file, file_size)

    @commands.command()
    @commands.bot_has_permissions(attach_files=True)
    async def flop(self, ctx, urls: ImageFinder = None):
        """Flip an image"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            b, mime = await self.bytes_download(url)

            def flop_img(b):
                img = PIL.Image.open(b)
                img = PIL.ImageOps.mirror(img)
                final = BytesIO()
                img.save(final, "png")
                file_size = final.tell()
                final.seek(0)
                return discord.File(final, filename="flop.png"), file_size
            file, file_size = await ctx.bot.loop.run_in_executor(None, flop_img, b)
            await self.safe_send(ctx, None, file, file_size)

    @commands.command(aliases=["inverse", "negate"])
    @commands.bot_has_permissions(attach_files=True)
    async def invert(self, ctx, urls: ImageFinder = None):
        """Invert the colours of an image"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            b, mime = await self.bytes_download(url)

            def invert_img(b):
                img = PIL.Image.open(b).convert("RGB")
                img = PIL.ImageOps.invert(img)
                final = BytesIO()
                img.save(final, "png")
                file_size = final.tell()
                final.seek(0)
                return discord.File(final, filename="flop.png"), file_size
            file, file_size = await ctx.bot.loop.run_in_executor(None, invert_img, b)
            await self.safe_send(ctx, None, file, file_size)

    @commands.command()
    @commands.bot_has_permissions(attach_files=True)
    async def rotate(self, ctx, degrees: int = 90, urls: ImageFinder = None):
        """Rotate image X degrees"""
        if urls is None:
            urls = await ImageFinder().search_for_images(ctx)
        url = urls[0]
        async with ctx.typing():
            b, mime = await self.bytes_download(url)
            if not b:
                return await ctx.send("That's not a valid image to rotate.")

            def rotate_img(b, degrees):
                img = PIL.Image.open(b).convert("RGBA")
                img = img.rotate(int(degrees))
                final = BytesIO()
                img.save(final, "png")
                file_size = final.tell()
                final.seek(0)
                return discord.File(final, filename="rotate.png"), file_size
            file, file_size = await ctx.bot.loop.run_in_executor(None, rotate_img, b, degrees)
            await self.safe_send(ctx, f"Rotated: `{degrees}°`", file, file_size)

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

    __unload = cog_unload
