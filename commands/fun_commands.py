import discord
from discord.ext import commands

COOLDOWN_TIME = 1800  # 30 minutes in seconds

class FunCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="winddd")
    @commands.cooldown(1, COOLDOWN_TIME, commands.BucketType.user)
    async def winddd(self, ctx):
        await ctx.send("Wherever I go on the internet, I see the Wind set and Dance Dance Dance (DDD). It’s like the Honkai: Star Rail community collectively decided, 'You know what this game needs? More wind and awkward dance routines.' Every guide is like, 'Just throw on the Wind set and call it a day,' as if the other relic sets are just there to make the inventory look pretty. And DDD? Oh, don’t even get me started. It’s the Light Cone equivalent of that one friend who insists they can fix anything with duct tape and a prayer. I’m half convinced the Astral Express runs on Wind energy now, with Pom-Pom leading a conga line every time we warp. At this point, I’m pretty sure the real endgame boss isn’t some cosmic horror—it’s the Wind set and DDD, haunting every comment section, every build guide, and every waking moment of my life. If I see one more 'Wind set + DDD = OP' post, I’m starting a support group for Trailblazers who just want to use something else. But hey, at least we’re all dancing together in this never-ending meta nightmare, right? I mean, who needs variety when you can just slap on the Wind set and pretend you’re a genius? And DDD? It’s like the game’s way of saying, 'Here, have a Light Cone that’s basically a participation trophy.' I’m starting to think the Wind set and DDD are secretly dating, because they’re everywhere together. Maybe they’re planning a wedding, and we’re all just guests at their meta-dominating ceremony. Honestly, if I see one more 'Wind set + DDD = OP' post, I’m going to start a petition to rename the game to 'Honkai: Wind Rail.' But hey, at least we’re all dancing together in this never-ending meta nightmare, right?")

    @commands.command(name="xiangling")
    @commands.cooldown(1, COOLDOWN_TIME, commands.BucketType.user)
    async def xiangling(self, ctx):
        await ctx.send("I come home from my third job, Xiangling is in my bed. ’You forgot to log onto genshin today to farm more emblem for me’ - she says. I don't have time for playing genshin, I spent thousands of dollars on r5 engulfing lightning which put me in debt. She doesn't care. I turn on my laptop, I'm farming emblem. My landlord is knocking on my door, I haven't paid rent in months. Next day, the police is here , I'm getting evicted. I guess this is it. As I'm being put in handcuffs I hear her voice - ’You still have 40 resin left, where do you think you're going?’. She unleashes a pyronado and one shots all officers and the landlord. I am now a wanted criminal in 50 states. But I couldn't care less. Xiangling saved my life, so I shall dedicate the rest of mine to her. I will never stop farming emblem. I will never have a normal life. I play Xiangling.")

    @commands.command(name="e2herta")
    @commands.cooldown(1, COOLDOWN_TIME, commands.BucketType.user)
    async def e2herta(self, ctx):
        await ctx.send("E2? E2 what? E2 Therta? Please shut the fuck up and use proper units you fuckin troglodyte, do you think Mihoyo gave us Stellar Jades just to pull broken units that have no skill and anyone with room temperature IQ can use for 0 cycle? Like please you always complain about why no one talks to you, because you're always using overpowered shit like E2 Therta or E2 Therta, and when you try to explain how good you are at pulling units and people should just pull better like what? What the fuck is skillful about using E2 Therta? Do you think you'll just become Star Rail’s Faker that will get a standing ovation just because you used E2 Therta in MOC12? HELL NO YOU FUCKIN IDIOT, so please shut the fuck up and use proper units you dumb fuck.")

    # Cooldown error handler (shared for all commands)
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            # Calculate remaining time in minutes
            remaining_time = round(error.retry_after / 60, 1)
            await ctx.send(f"Whoa, slow down! You can use this command again in **{remaining_time} minutes**.")
        else:
            await ctx.send("An error occurred. Please try again later.")
            
async def setup(bot):
    await bot.add_cog(FunCommands(bot))