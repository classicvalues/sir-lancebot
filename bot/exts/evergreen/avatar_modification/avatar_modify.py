import asyncio
import json
import logging
import string
import typing as t
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import discord
from aiohttp import client_exceptions
from discord.ext import commands
from discord.ext.commands.errors import BadArgument

from bot.constants import Client, Colours, Emojis
from bot.exts.evergreen.avatar_modification._effects import PfpEffects
from bot.utils.extensions import invoke_help_command
from bot.utils.halloween import spookifications

log = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(10)

FILENAME_STRING = "{effect}_{author}.png"

with open("bot/resources/pride/gender_options.json") as f:
    GENDER_OPTIONS = json.load(f)


async def in_executor(func: t.Callable, *args) -> t.Any:
    """
    Runs the given synchronus function `func` in an executor.

    This is useful for running slow, blocking code within async
    functions, so that they don't block the bot.
    """
    log.trace(f"Running {func.__name__} in an executor.")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_EXECUTOR, func, *args)


def file_safe_name(effect: str, display_name: str) -> str:
    """Returns a file safe filename based on the given effect and display name."""
    valid_filename_chars = f"-_. {string.ascii_letters}{string.digits}"

    file_name = FILENAME_STRING.format(effect=effect, author=display_name)

    # Replace spaces
    file_name = file_name.replace(" ", "_")

    # Normalize unicode characters
    cleaned_filename = unicodedata.normalize("NFKD", file_name).encode("ASCII", "ignore").decode()

    # Remove invalid filename characters
    cleaned_filename = "".join(c for c in cleaned_filename if c in valid_filename_chars)
    return cleaned_filename


class AvatarModify(commands.Cog):
    """Various commands for users to apply affects to their own avatars."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _fetch_member(self, member_id: int) -> t.Optional[discord.Member]:
        """
        Fetches a member and handles errors.

        This helper funciton is required as the member cache doesn't always have the most up to date
        profile picture. This can lead to errors if the image is delted from the Discord CDN.
        """
        try:
            member = await self.bot.get_guild(Client.guild).fetch_member(member_id)
        except discord.errors.NotFound:
            log.debug(f"Member {member_id} left the guild before we could get their pfp.")
            return None
        except discord.HTTPException:
            log.exception(f"Exception while trying to retrieve member {member_id} from Discord.")
            return None

        return member

    @commands.group(aliases=("avatar_mod", "pfp_mod", "avatarmod", "pfpmod"))
    async def avatar_modify(self, ctx: commands.Context) -> None:
        """Groups all of the pfp modifying commands to allow a single concurrency limit."""
        if not ctx.invoked_subcommand:
            await invoke_help_command(ctx)

    @avatar_modify.command(name="8bitify", root_aliases=("8bitify",))
    async def eightbit_command(self, ctx: commands.Context) -> None:
        """Pixelates your avatar and changes the palette to an 8bit one."""
        async with ctx.typing():
            member = await self._fetch_member(ctx.author.id)
            if not member:
                await ctx.send(f"{Emojis.cross_mark} Could not get member info.")
                return

            image_bytes = await member.avatar_url.read()
            file_name = file_safe_name("eightbit_avatar", member.display_name)

            file = await in_executor(
                PfpEffects.apply_effect,
                image_bytes,
                PfpEffects.eight_bitify_effect,
                file_name
            )

            embed = discord.Embed(
                title="Your 8-bit avatar",
                description="Here is your avatar. I think it looks all cool and 'retro'."
            )

            embed.set_image(url=f"attachment://{file_name}")
            embed.set_footer(text=f"Made by {member.display_name}.", icon_url=member.avatar_url)

        await ctx.send(embed=embed, file=file)

    @avatar_modify.command(aliases=("easterify",), root_aliases=("easterify", "avatareasterify"))
    async def avatareasterify(self, ctx: commands.Context, *colours: t.Union[discord.Colour, str]) -> None:
        """
        This "Easterifies" the user's avatar.

        Given colours will produce a personalised egg in the corner, similar to the egg_decorate command.
        If colours are not given, a nice little chocolate bunny will sit in the corner.
        Colours are split by spaces, unless you wrap the colour name in double quotes.
        Discord colour names, HTML colour names, XKCD colour names and hex values are accepted.
        """
        async def send(*args, **kwargs) -> str:
            """
            This replaces the original ctx.send.

            When invoking the egg decorating command, the egg itself doesn't print to to the channel.
            Returns the message content so that if any errors occur, the error message can be output.
            """
            if args:
                return args[0]

        async with ctx.typing():
            member = await self._fetch_member(ctx.author.id)
            if not member:
                await ctx.send(f"{Emojis.cross_mark} Could not get member info.")
                return

            egg = None
            if colours:
                send_message = ctx.send
                ctx.send = send  # Assigns ctx.send to a fake send
                egg = await ctx.invoke(self.bot.get_command("eggdecorate"), *colours)
                if isinstance(egg, str):  # When an error message occurs in eggdecorate.
                    await send_message(egg)
                    return
                ctx.send = send_message  # Reassigns ctx.send

            image_bytes = await member.avatar_url_as(size=256).read()
            file_name = file_safe_name("easterified_avatar", member.display_name)

            file = await in_executor(
                PfpEffects.apply_effect,
                image_bytes,
                PfpEffects.easterify_effect,
                file_name,
                egg
            )

            embed = discord.Embed(
                name="Your Lovely Easterified Avatar!",
                description="Here is your lovely avatar, all bright and colourful\nwith Easter pastel colours. Enjoy :D"
            )
            embed.set_image(url=f"attachment://{file_name}")
            embed.set_footer(text=f"Made by {member.display_name}.", icon_url=member.avatar_url)

        await ctx.send(file=file, embed=embed)

    @staticmethod
    async def send_pride_image(
        ctx: commands.Context,
        image_bytes: bytes,
        pixels: int,
        flag: str,
        option: str
    ) -> None:
        """Gets and sends the image in an embed. Used by the pride commands."""
        async with ctx.typing():
            file_name = file_safe_name("pride_avatar", ctx.author.display_name)

            file = await in_executor(
                PfpEffects.apply_effect,
                image_bytes,
                PfpEffects.pridify_effect,
                file_name,
                pixels,
                flag
            )

            embed = discord.Embed(
                name="Your Lovely Pride Avatar!",
                description=f"Here is your lovely avatar, surrounded by\n a beautiful {option} flag. Enjoy :D"
            )
            embed.set_image(url=f"attachment://{file_name}")
            embed.set_footer(text=f"Made by {ctx.author.display_name}.", icon_url=ctx.author.avatar_url)
            await ctx.send(file=file, embed=embed)

    @avatar_modify.group(
        aliases=("avatarpride", "pridepfp", "prideprofile"),
        root_aliases=("prideavatar", "avatarpride", "pridepfp", "prideprofile"),
        invoke_without_command=True
    )
    async def prideavatar(self, ctx: commands.Context, option: str = "lgbt", pixels: int = 64) -> None:
        """
        This surrounds an avatar with a border of a specified LGBT flag.

        This defaults to the LGBT rainbow flag if none is given.
        The amount of pixels can be given which determines the thickness of the flag border.
        This has a maximum of 512px and defaults to a 64px border.
        The full image is 1024x1024.
        """
        option = option.lower()
        pixels = max(0, min(512, pixels))
        flag = GENDER_OPTIONS.get(option)
        if flag is None:
            await ctx.send("I don't have that flag!")
            return

        async with ctx.typing():
            member = await self._fetch_member(ctx.author.id)
            if not member:
                await ctx.send(f"{Emojis.cross_mark} Could not get member info.")
                return
            image_bytes = await member.avatar_url_as(size=1024).read()
            await self.send_pride_image(ctx, image_bytes, pixels, flag, option)

    @prideavatar.command()
    async def image(self, ctx: commands.Context, url: str, option: str = "lgbt", pixels: int = 64) -> None:
        """
        This surrounds the image specified by the URL with a border of a specified LGBT flag.

        This defaults to the LGBT rainbow flag if none is given.
        The amount of pixels can be given which determines the thickness of the flag border.
        This has a maximum of 512px and defaults to a 64px border.
        The full image is 1024x1024.
        """
        option = option.lower()
        pixels = max(0, min(512, pixels))
        flag = GENDER_OPTIONS.get(option)
        if flag is None:
            await ctx.send("I don't have that flag!")
            return

        async with ctx.typing():
            try:
                async with self.bot.http_session.get(url) as response:
                    if response.status != 200:
                        await ctx.send("Bad response from provided URL!")
                        return
                    image_bytes = await response.read()
            except client_exceptions.ClientConnectorError:
                raise BadArgument("Cannot connect to provided URL!")
            except client_exceptions.InvalidURL:
                raise BadArgument("Invalid URL!")

            await self.send_pride_image(ctx, image_bytes, pixels, flag, option)

    @prideavatar.command()
    async def flags(self, ctx: commands.Context) -> None:
        """This lists the flags that can be used with the prideavatar command."""
        choices = sorted(set(GENDER_OPTIONS.values()))
        options = "• " + "\n• ".join(choices)
        embed = discord.Embed(
            title="I have the following flags:",
            description=options,
            colour=Colours.soft_red
        )
        await ctx.send(embed=embed)

    @avatar_modify.command(
        aliases=("savatar", "spookify"),
        root_aliases=("spookyavatar", "spookify", "savatar"),
        brief="Spookify an user's avatar."
    )
    async def spookyavatar(self, ctx: commands.Context, member: discord.Member = None) -> None:
        """This "spookifies" the given user's avatar, with a random *spooky* effect."""
        if member is None:
            member = ctx.author

        member = await self._fetch_member(member.id)
        if not member:
            await ctx.send(f"{Emojis.cross_mark} Could not get member info.")
            return

        async with ctx.typing():
            image_bytes = await member.avatar_url.read()

            file_name = file_safe_name("spooky_avatar", member.display_name)

            file = await in_executor(
                PfpEffects.apply_effect,
                image_bytes,
                spookifications.get_random_effect,
                file_name
            )

            embed = discord.Embed(
                title="Is this you or am I just really paranoid?",
                colour=Colours.soft_red
            )
            embed.set_author(name=member.name, icon_url=member.avatar_url)
            embed.set_image(url=f"attachment://{file_name}")
            embed.set_footer(text=f"Made by {ctx.author.display_name}.", icon_url=ctx.author.avatar_url)

            await ctx.send(file=file, embed=embed)


def setup(bot: commands.Bot) -> None:
    """Load the PfpModify cog."""
    bot.add_cog(AvatarModify(bot))
