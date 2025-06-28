import contextlib
import datetime
import io
import os
import textwrap
from traceback import format_exception

import discord
from discord.ext import commands, pages
from dotenv import load_dotenv

from mitdb import MITUserDB

load_dotenv()

bot = discord.Bot(owner_id=os.getenv("OWNER_ID"), intents=discord.Intents.all())
admin = bot.create_group("admin", "Admin Commands")

userdb = MITUserDB(bot)


@bot.slash_command(description="Start process to verify your MIT affiliation.")
@discord.option(
    "kerb",
    description="Your Kerberos ID (without the @mit.edu). If alumni, please use your MIT alumni email.",
)
async def verify(ctx, kerb: str):
    if not kerb:
        await ctx.respond("Please provide a kerb to verify as.")
        return

    if kerb.endswith("@mit.edu"):
        await ctx.respond("Please provide your Kerberos ID (without the @mit.edu).")
        return

    if not kerb.endswith("@alum.mit.edu"):
        kerb_info = userdb.fetch_kerb_info(kerb)

        if not kerb_info:
            await ctx.respond(
                f"Could not find that kerb! Please try again with your Kerberos ID (without the @mit.edu).",
                ephemeral=True,
            )
            return

    await ctx.defer(ephemeral=True)

    _, failure_reason = await userdb.generate_secure_code(kerb, ctx.author.id)

    if failure_reason:
        await ctx.respond(
            f"Could not start verification process. Please contact a moderator for assistance if needed. Failure reason: {failure_reason}",
            ephemeral=True,
        )
        return

    await ctx.respond(
        f"Verification process started. Please check your email! To complete your verification, run the following command. `/code <kerb> <verification code>`.",
        ephemeral=True,
    )
    return


@bot.slash_command(description="Complete verification process by using emailed code.")
@commands.guild_only()
@discord.option("kerb", description="Your Kerberos ID (without the @mit.edu).")
@discord.option("code", description="The code emailed to you.")
async def code(ctx: discord.ApplicationContext, kerb: str, code: str):
    if not kerb:
        await ctx.respond("Please provide a kerb to verify as.", ephemeral=True)
        return

    if not code:
        await ctx.respond("Please provide a verification code.", ephemeral=True)
        return

    if not userdb.get_verification_code(kerb):
        await ctx.respond(
            "Invalid verification code. Have you started the verification process with `/verify <kerb>`?",
            ephemeral=True,
        )
        return

    if not ctx.guild:
        return

    await ctx.defer(ephemeral=True)

    if not await userdb.verify_user(kerb, ctx.author.id, code, ctx.guild.id):
        await ctx.respond(
            "Invalid verification code. Please restart the process with `/verify <kerb>` or enter the correct code.",
            ephemeral=True,
        )
        return

    await ctx.respond("Successfully verified!", ephemeral=True)
    return


@admin.command(
    name="lookup_kerb", description="Lookup a user's kerb and return API info."
)
@discord.guild_only()
@discord.default_permissions(administrator=True)
@discord.option("kerb", description="Your Kerberos ID (without the @mit.edu).")
async def lookup_kerb(ctx: discord.ApplicationContext, kerb: str):
    if not ctx.author.guild_permissions.administrator:  # type: ignore
        await ctx.respond("You must be an administrator to use this command.")
        return

    if not kerb:
        await ctx.respond("Please provide a kerb to lookup.")
        return

    kerb_info = userdb.fetch_kerb_info(kerb)

    if not kerb_info:
        await ctx.respond(
            f"Could not find that kerb! Please try again with your Kerberos ID (without the @mit.edu).",
            ephemeral=True,
        )
        return

    await ctx.respond(
        f"Found user {kerb_info}",
        ephemeral=True,
    )
    return


@admin.command(name="blacklist_kerb", description="Blacklist a kerb from verification.")
@discord.default_permissions(administrator=True)
@discord.option("kerb", description="The Kerberos ID (without the @mit.edu).")
async def blacklist_kerb(ctx, kerb: str):
    if not ctx.author.guild_permissions.administrator:  # ignore: line
        await ctx.respond("You must be an administrator to use this command.")
        return

    if not kerb:
        await ctx.respond("Please provide a kerb to blacklist.")
        return

    userdb.blacklist_kerb(kerb)

    await ctx.respond(f"Successfully blacklisted {kerb}.")
    return


@admin.command(
    name="unblacklist_kerb", description="Unblacklist a kerb from verification."
)
@discord.default_permissions(administrator=True)
@discord.option("kerb", description="The Kerberos ID (without the @mit.edu).")
async def unblacklist_kerb(ctx, kerb: str):
    if not ctx.author.guild_permissions.administrator:  # ignore: line
        await ctx.respond("You must be an administrator to use this command.")
        return

    if not kerb:
        await ctx.respond("Please provide a kerb to unblacklist.")
        return

    userdb.unblacklist_kerb(kerb)

    await ctx.respond(f"Successfully unblacklisted {kerb}.")
    return


@admin.command(name="blacklist", description="Get a list of blacklisted kerbs.")
@discord.default_permissions(administrator=True)
async def get_blacklist(ctx):
    if not ctx.author.guild_permissions.administrator:  # ignore: line
        await ctx.respond("You must be an administrator to use this command.")
        return
    blacklist = userdb.get_blacklisted_kerbs()
    await ctx.respond(f"**Blacklisted Kerbs:** {blacklist}")
    return


# set logging channel
@admin.command(name="set_logging_channel", description="Set the logging channel.")
@discord.default_permissions(administrator=True)
@discord.option(
    "channel",
    description="The channel to set as the logging channel.",
    channel_type=discord.ChannelType.text,
)
async def set_logging_channel(ctx, channel: discord.TextChannel):
    if not ctx.author.guild_permissions.administrator:  # ignore: line
        await ctx.respond("You must be an administrator to use this command.")
        return
    userdb.set_logging_channel(channel.id)
    await ctx.respond(f"Successfully set logging channel to {channel.mention}.")
    await channel.send("Logging channel set.")
    return


@admin.command(
    name="get_affiliations", description="Get affiliations for a specified kerb."
)
@discord.default_permissions(administrator=True)
@discord.option("kerb", description="The Kerberos ID (without the @mit.edu).")
async def get_affiliations(ctx, kerb: str):
    if not ctx.author.guild_permissions.administrator:  # ignore: line
        await ctx.respond("You must be an administrator to use this command.")
        return
    if not kerb:
        await ctx.respond("Please provide a kerb to lookup.")
        return

    if not kerb.endswith("@alum.mit.edu"):
        kerb_info = userdb.fetch_kerb_info(kerb)

        if not kerb_info:
            await ctx.respond(
                f"Could not find that kerb! Please try again with your Kerberos ID (without the @mit.edu).",
                ephemeral=True,
            )
            return

    roles = await userdb.assign_discord_roles(
        ctx.guild.id, ctx.author.id, kerb, True, kerb.endswith("@alum.mit.edu")
    )

    if roles is False:
        await ctx.respond("Could not find roles for that kerb.")
        return

    await ctx.respond(f"**Affiliations for {kerb}:** {[role.name for role in roles]}")
    return


@admin.command(
    name="update_roles",
    description="Updates roles for a specified user assuming they're verified.",
)
@discord.default_permissions(administrator=True)
async def update_roles(ctx, member: discord.Member):
    if not ctx.author.guild_permissions.administrator:  # ignore: line
        await ctx.respond("You must be an administrator to use this command.")
        return

    verification_data = userdb.get_user_from_discordid(member.id)
    if verification_data is None:
        await ctx.respond("Could not find that user's verification.")
        return

    roles = await userdb.assign_discord_roles(
        ctx.guild.id, member.id, verification_data["kerb"]
    )  # ignore: line

    if roles is False:
        await ctx.respond("Could not find roles for that user.")
        return

    await ctx.respond(f"**Roles for {member}:** {[role.name for role in roles]}")
    return


@admin.command(
    name="add_togglerole",
    description="Add a role that can be toggled with /toggle_role.",
)
@discord.guild_only()
@discord.default_permissions(administrator=True)
@discord.option("role", description="The role to add.")
async def add_togglerole(ctx: discord.ApplicationContext, role: discord.Role):
    if not ctx.author.guild_permissions.administrator:  # type: ignore
        await ctx.respond("You must be an administrator to use this command.")
        return

    if role.id in userdb.get_togglable_roles():
        await ctx.respond("That role is already a togglerole.")
        return

    userdb.add_togglable_role(role)
    await ctx.respond(f"Successfully added togglerole {role.name}.")
    return


@admin.command(
    name="remove_togglerole",
    description="Remove a role that can be toggled with /toggle_role.",
)
@discord.default_permissions(administrator=True)
@discord.option("role", description="The role to remove.")
async def remove_togglerole(ctx: discord.ApplicationContext, role: discord.Role):
    if not ctx.author.guild_permissions.administrator:  # type: ignore
        await ctx.respond("You must be an administrator to use this command.")
        return

    if role.id not in userdb.get_togglable_roles():
        await ctx.respond("That role is not a togglerole.")
        return

    userdb.remove_togglable_role(role)
    await ctx.respond(f"Successfully removed togglerole {role.name}.")
    return


@bot.slash_command(
    name="get_toggleroles",
    description="Get a list of roles that can be toggled with /toggle_role.",
)
async def get_toggleroles(ctx: discord.ApplicationContext):
    if not ctx.guild:
        await ctx.respond("This command can only be used in a server.")
        return

    server_roles = ctx.guild.roles
    toggleroles = [
        role for role in server_roles if role.id in userdb.get_togglable_roles()
    ]
    toggleroles.sort(key=lambda role: role.name)
    toggleroles = [role.mention for role in toggleroles]
    roles_string = "\n".join(toggleroles)
    await ctx.respond(f"**Toggle Roles:**\n{roles_string}", ephemeral=True)
    return


@bot.slash_command(
    name="toggle_role", description="Update your class year, major, hometown, or dorm."
)
async def toggle_role(ctx: discord.ApplicationContext, role: discord.Role):
    if not isinstance(ctx.author, discord.Member):
        await ctx.respond(
            "You must be in a server to use this command.", ephemeral=True
        )
        return

    if "Verified" in [role.name for role in ctx.author.roles]:
        if role.id not in userdb.get_togglable_roles():
            await ctx.respond("You cannot toggle that role.", ephemeral=True)
            return

        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
            await ctx.respond(f"Removed role {role.name}.", ephemeral=True)
        else:
            await ctx.author.add_roles(role)
            await ctx.respond(f"Added role {role.name}.", ephemeral=True)
    else:
        await ctx.respond(
            "You must be verified to use this command. Please run /verify.",
            ephemeral=True,
        )


def clean_code(content):
    """Automatically removes code blocks from the code."""
    # remove ```py\n```
    if content.startswith("```") and content.endswith("```"):
        return "\n".join(content.split("\n")[1:])[:-3]
    else:
        return content


@bot.slash_command(dm_permission=False)
@commands.is_owner()
async def eval(ctx: discord.ApplicationContext, code: str):
    if not ctx.author.id == bot.owner_id:  # ignore: line
        await ctx.respond("You must be an administrator to use this command.")
        return

    await ctx.response.defer(ephemeral=True)
    code = clean_code(code)

    code = "\n".join(code.split("|"))

    local_variables = {
        "discord": discord,
        "bot": bot,
        "ctx": ctx,
        "mitdb": userdb,
    }

    stdout = io.StringIO()

    result: str = ""

    try:
        with contextlib.redirect_stdout(stdout):
            exec(
                f"async def func():\n{textwrap.indent(code, '    ')}",
                local_variables,
            )

            obj = await local_variables["func"]()
            result: str = f"{stdout.getvalue()}\n-- {obj}\n"

    except Exception as e:
        result: str = "".join(format_exception(e, e, e.__traceback__))  # type: ignore

    def format_page(code: str) -> discord.Embed:
        embed = discord.Embed(title=f"Evaluation")
        embed.description = f"```\n{code}\n```"
        embed.colour = discord.Colour.blurple()
        return embed

    formatted_pages = [
        format_page(result[i : i + 2000]) for i in range(0, len(result), 2000)
    ]
    paginator = pages.Paginator([formatted_pages])
    await paginator.respond(ctx.interaction)


@bot.event
async def on_typing(
    channel: discord.abc.Messageable, user: discord.User, when: datetime.datetime
):
    """Event handler for when a user starts typing in a channel."""

    print("User started typing in channel:", channel.name)
    if user.bot:
        return

    if not isinstance(channel, discord.TextChannel):
        return

    # check last time user had roles updated, if it's been more than 24 hours, check if roles should change
    user_data = userdb.get_user_from_discordid(user.id)
    if user_data is None:
        print("User not found in database, skipping role update check.")
        return

    # if undefined or more than 24 hours since last roles update, check roles
    if "lastRoleUpdate" in user_data:
        print("User found in database, checking last roles update time.")
        last_updated = user_data["lastRoleUpdate"]
        if (when - last_updated).total_seconds() < 86400:
            return

    kerb = user_data["kerb"]
    if not kerb.endswith("@alum.mit.edu"):
        # if not alum, fetch kerb info
        print("Fetching kerb info for user:", kerb)
        kerb_info = userdb.fetch_kerb_info(kerb)

        if not kerb_info:
            return

    roles = await userdb.assign_discord_roles(
        channel.guild.id, user.id, kerb, True, kerb.endswith("@alum.mit.edu")
    )
    print("Roles assigned:", roles)

    # if roles were updated, send a message to the channel
    if roles:
        print("Roles updated for user:", user.name)
        roles_names = [role.name for role in roles]
        await channel.guild.get_channel(userdb.logging_channel_id).send(
            f"Roles updated for {user.mention} ({user.id}): {', '.join(roles_names)}"
        )


@bot.event
async def on_member_join(member: discord.Member):
    """Event handler for when a member joins a guild."""
    print(f"Member joined: {member.name} ({member.id})")
    if not isinstance(member, discord.Member):
        return

    # Assign roles based on verification status
    roles = await userdb.assign_discord_roles(member.guild.id, member.id, member.name)
    if roles:
        await member.guild.get_channel(userdb.logging_channel_id).send(
            f"Roles assigned to {member.mention} ({member.id}): {', '.join(role.name for role in roles)}"
        )
    else:
        print(f"No roles assigned to {member.name}.")


@bot.event
async def on_ready():
    if bot.is_ready() and bot.user:
        print(f"Logged in as {bot.user.name} - {bot.user.id}")
        print("Servers connected to:", [guild.name for guild in bot.guilds])


bot.run(os.getenv("DISCORD_TOKEN"))
