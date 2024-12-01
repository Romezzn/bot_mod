import discord
from discord.ext import commands
from discord import app_commands, Embed, Interaction
import os
import json
from dotenv import load_dotenv

# Cargar token desde .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_ROLE_IDS = os.getenv("ALLOWED_ROLE_IDS").split(",")  # IDs de roles permitidos desde .env

# Configuración del bot
intents = discord.Intents.default()
intents.members = True  # Habilitar intents para obtener miembros
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Cargar reglas desde JSON
with open("rules.json", "r", encoding="utf-8") as f:
    RULES = json.load(f)

# Canales de moderación y registro
TEXT_CHANNEL = 1308550309869654108
AUDIO_CHANNEL = 1309521466106052659
URL_CHANNEL = 1309542661526388756
LOG_CHANNEL = 1312752312569036860  # Canal para registrar las acciones del bot

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}.")
    print(f"ID: {bot.user.id}")


@bot.event
async def on_message(message):
    # Ignorar mensajes del bot
    if message.author.bot:
        return

    # Verificar si el mensaje proviene de un servidor
    if message.guild is not None:
        # Crear el embed para el mensaje
        embed = Embed(
            color=discord.Color.blue(),
        )
        embed.set_author(
            name=f"@{message.author.display_name}",  # Usa el nombre del servidor
            icon_url=message.author.avatar.url if message.author.avatar else message.author.default_avatar.url,
        )
        embed.add_field(name="Contenido", value=message.content if message.content else "Sin texto", inline=False)
        
        # Agregar la URL del mensaje original
        embed.add_field(name="Enlace al mensaje", value=f"[Haz clic aquí]({message.jump_url})", inline=False)

        # Generar botones con custom_id únicos
        view = ModerationActions(message)

        # Filtrar mensajes por tipo
        try:
            # Mensajes con archivos adjuntos
            if message.attachments:
                files = [await attachment.to_file() for attachment in message.attachments]
                await bot.get_channel(AUDIO_CHANNEL).send(
                    content=f"@{message.author.display_name} ha enviado archivos adjuntos:",
                    files=files,
                    embed=embed,
                    view=view
                )

            # Mensajes con URLs
            elif "http://" in message.content or "https://" in message.content:
                await bot.get_channel(URL_CHANNEL).send(embed=embed, view=view)

            # Mensajes de texto sin adjuntos ni URLs
            elif message.content:
                await bot.get_channel(TEXT_CHANNEL).send(embed=embed, view=view)

        except Exception as e:
            print(f"Error procesando mensaje: {e}")
    else:
        print("Mensaje recibido fuera del servidor. Ignorando.")

    await bot.process_commands(message)


class ModerationActions(discord.ui.View):
    def __init__(self, message):
        super().__init__()
        self.message = message
        self.add_item(discord.ui.Button(label="Banear", style=discord.ButtonStyle.red, custom_id=f"ban-{message.id}-{message.author.id}"))
        self.add_item(discord.ui.Button(label="Expulsar", style=discord.ButtonStyle.blurple, custom_id=f"kick-{message.id}-{message.author.id}"))
        self.add_item(discord.ui.Button(label="Advertir", style=discord.ButtonStyle.green, custom_id=f"warn-{message.id}-{message.author.id}"))

@bot.event
async def on_interaction(interaction: Interaction):
    if interaction.data.get("component_type") == 2:  # Tipo 2 es para botones
        custom_id = interaction.data["custom_id"]
        action, message_id, user_id = custom_id.split("-")

        if not any(role.id in map(int, ALLOWED_ROLE_IDS) for role in interaction.user.roles):
            await interaction.response.send_message("No tienes permiso para usar este botón.", ephemeral=True)
            return

        guild = interaction.guild
        member = guild.get_member(int(user_id))

        if not member:
            print(f"Usuario con ID {user_id} no encontrado en el servidor.")
            await interaction.response.send_message("El usuario ya no está en el servidor o no se encuentra disponible.", ephemeral=True)
            return

        log_channel = bot.get_channel(LOG_CHANNEL)
        await log_channel.send(
            f"**Moderador:** {interaction.user.mention}\n"
            f"**Acción:** {action.capitalize()}\n"
            f"**Usuario afectado:** {member.mention}\n"
            f"**Mensaje ID:** {message_id}\n"
            f"**Fecha:** {discord.utils.format_dt(discord.utils.utcnow(), style='F')}"
        )

        await start_punishment_process(interaction, action, member, message_id)


async def start_punishment_process(interaction: Interaction, action: str, member: discord.Member, message_id: str):
    view = ReasonSelectionView(member, action, message_id)
    await interaction.response.send_message(
        f"Vas a **{action}** a @{member.name}. Selecciona el motivo de la sanción:",
        view=view,
        ephemeral=True,
    )


class ReasonSelectionView(discord.ui.View):
    def __init__(self, member, action, message_id):
        super().__init__()
        self.add_item(ReasonSelection(member, action, message_id))


class ReasonSelection(discord.ui.Select):
    def __init__(self, member, action, message_id):
        self.member = member
        self.action = action
        self.message_id = message_id

        options = [
            discord.SelectOption(label=f"Norma {rule_id}", description=rule_content[:50], value=str(rule_id))
            for rule_id, rule_content in RULES.items()
        ]

        super().__init__(
            placeholder="Selecciona el motivo de la sanción...",
            options=options,
        )

    async def callback(self, interaction: Interaction):
        rule_id = self.values[0]
        rule_content = RULES[rule_id]

        dm_message = (
            f"Has sido **{self.action}** por incumplir la **Norma Nº {rule_id}:** {rule_content}.\n\n"
            f"**Mensaje que causó la sanción (ID {self.message_id}):**"
        )
        try:
            await self.member.send(dm_message)
        except discord.Forbidden:
            await interaction.response.send_message(
                "No se pudo enviar el mensaje privado al usuario. Puede que tenga los DMs desactivados.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"El usuario @{self.member.name} ha sido **{self.action}** por el motivo: **Norma Nº {rule_id}**.",
            ephemeral=True,
        )

        if self.action == "ban":
            await self.member.ban(reason=f"Norma Nº {rule_id}: {rule_content}")
        elif self.action == "kick":
            await self.member.kick(reason=f"Norma Nº {rule_id}: {rule_content}")
        elif self.action == "warn":
            pass

        log_channel = bot.get_channel(LOG_CHANNEL)
        await log_channel.send(
            f"**Acción completada:** {self.action.capitalize()}\n"
            f"**Usuario:** {self.member.mention}\n"
            f"**Motivo:** Norma Nº {rule_id}: {rule_content}\n"
            f"**Moderador:** {interaction.user.mention}"
        )


@bot.command(name="ban")
async def ban(ctx, member: discord.Member, *, reason=None):
    if not any(role.id in map(int, ALLOWED_ROLE_IDS) for role in ctx.author.roles):
        await ctx.send("No tienes permiso para usar este comando.")
        return

    await member.ban(reason=reason)
    await ctx.send(f"{member.mention} ha sido baneado. Motivo: {reason}")
    await member.send(f"Has sido **baneado** por el siguiente motivo: {reason}")
    log_channel = bot.get_channel(LOG_CHANNEL)
    await log_channel.send(
        f"**Moderador:** {ctx.author.mention}\n**Acción:** Ban\n**Usuario:** {member.mention}\n**Motivo:** {reason}"
    )
    await ctx.message.delete()


@bot.command(name="kick")
async def kick(ctx, member: discord.Member, *, reason=None):
    if not any(role.id in map(int, ALLOWED_ROLE_IDS) for role in ctx.author.roles):
        await ctx.send("No tienes permiso para usar este comando.")
        return

    await member.kick(reason=reason)
    await ctx.send(f"{member.mention} ha sido expulsado. Motivo: {reason}")
    await member.send(f"Has sido **expulsado** por el siguiente motivo: {reason}")
    log_channel = bot.get_channel(LOG_CHANNEL)
    await log_channel.send(
        f"**Moderador:** {ctx.author.mention}\n**Acción:** Kick\n**Usuario:** {member.mention}\n**Motivo:** {reason}"
    )
    await ctx.message.delete()

@bot.command(name="warn")
async def warn(ctx, member: discord.Member, *, reason=None):
    if not any(role.id in map(int, ALLOWED_ROLE_IDS) for role in ctx.author.roles):
        await ctx.send("No tienes permiso para usar este comando.")
        return

    await ctx.send(f"{member.mention} ha sido advertido. Motivo: {reason}")
    await member.send(f"Has recibido una **advertencia** por el siguiente motivo: {reason}")
    log_channel = bot.get_channel(LOG_CHANNEL)
    await log_channel.send(
        f"**Moderador:** {ctx.author.mention}\n**Acción:** Warn\n**Usuario:** {member.mention}\n**Motivo:** {reason}"
    )
    await ctx.message.delete()

bot.run(TOKEN)
