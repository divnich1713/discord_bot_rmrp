"""
Applications — Система подачи заявлений
Панель с кнопками: Собеседование / Перевод/Восстановление / Гос.Сотрудник
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

from utils.checks import commander_only, is_commander
from utils.constants import COLORS, build_nickname


# ─────────────────────────────────────────────
#  МОДАЛЬНАЯ ФОРМА — СОБЕСЕДОВАНИЕ (5 полей)
# ─────────────────────────────────────────────

class ApplicationModal(discord.ui.Modal):
    static_id = discord.ui.TextInput(
        label="Статик (игровой ID)",
        placeholder="Например: 123-123",
        min_length=1,
        max_length=20,
    )
    full_name = discord.ui.TextInput(
        label="ФИО персонажа",
        placeholder="Например: Алексей Иванов",
        min_length=3,
        max_length=64,
    )
    age = discord.ui.TextInput(
        label="Возраст персонажа на сервере",
        placeholder="Например: 28",
        min_length=1,
        max_length=10,
    )
    reason = discord.ui.TextInput(
        label="Причина подачи заявления",
        placeholder="Опишите причину...",
        style=discord.TextStyle.paragraph,
        min_length=10,
        max_length=500,
    )
    military_id = discord.ui.TextInput(
        label="Военный билет (да / нет)",
        placeholder="Введите: «да» — есть, «нет» — отсутствует",
        min_length=2,
        max_length=3,
    )

    def __init__(self, cog, app_type: str):
        titles = {
            "interview": "📋 Заявление — Собеседование",
        }
        super().__init__(title=titles.get(app_type, "📋 Заявление"), timeout=300)
        self.cog = cog
        self.app_type = app_type

    async def on_submit(self, interaction: discord.Interaction):
        mil_val = self.military_id.value.strip().lower()
        VALID = {"да", "нет", "da", "net", "yes", "no"}
        if mil_val not in VALID:
            await interaction.response.send_message(
                "❌ В поле **Военный билет** укажите только `да` или `нет`.",
                ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        config = self.cog.bot.config

        app_id = await self.cog.bot.db.add_application(
            discord_id=str(user.id),
            game_name=self.full_name.value.strip(),
            age=self.age.value.strip(),
            reason=self.reason.value.strip(),
            extra={
                "static_id":   self.static_id.value.strip(),
                "military_id": self.military_id.value.strip(),
                "app_type":    self.app_type,
            }
        )

        candidate_role_id = config["roles"].get("candidate", 0)
        if candidate_role_id:
            role = interaction.guild.get_role(candidate_role_id)
            if role and role not in user.roles:
                try:
                    await user.add_roles(role, reason="Подача заявления")
                except Exception:
                    pass

        type_labels = {"interview": "📢 Собеседование"}
        type_colors = {"interview": 0x3498DB}

        embed = discord.Embed(
            title=f"📨 Новое заявление #{app_id}",
            description=f"**Тип:** {type_labels.get(self.app_type, self.app_type)}",
            color=type_colors.get(self.app_type, COLORS["rosguard"]),
            timestamp=datetime.utcnow(),
        )
        embed.set_author(name=f"{user.display_name} ({user})", icon_url=user.display_avatar.url)
        embed.add_field(name="👤 ФИО персонажа",    value=self.full_name.value.strip(),  inline=True)
        embed.add_field(name="🎮 Статик (ID)",       value=self.static_id.value.strip(),  inline=True)
        embed.add_field(name="🎂 Возраст персонажа", value=self.age.value.strip(),        inline=True)
        embed.add_field(name="📋 Причина",           value=self.reason.value.strip(),     inline=False)
        embed.add_field(name="🪖 Военный билет",     value=self.military_id.value.strip(),inline=True)
        embed.add_field(name="🏷️ Discord",           value=user.mention,                  inline=True)
        embed.set_footer(text=f"ID заявления: {app_id} • ID пользователя: {user.id}")

        log_ch_id = config["channels"].get("applications_log", 0)
        log_ch = interaction.guild.get_channel(log_ch_id)
        view = ApplicationDecisionView(self.cog, app_id, str(user.id),
                                       self.full_name.value.strip(), self.app_type)

        commander_ids = config["roles"].get("commander_roles", [])
        if isinstance(commander_ids, int):
            commander_ids = [commander_ids]
        ping = " ".join(f"<@&{r}>" for r in commander_ids if r)

        if log_ch:
            msg = await log_ch.send(
                content=f"{ping}\n📨 Новое заявление от {user.mention}!" if ping
                        else f"📨 Новое заявление от {user.mention}!",
                embed=embed,
                view=view,
            )
            await self.cog.bot.db.set_application_message(app_id, str(msg.id), str(log_ch.id))

        await interaction.followup.send(
            "✅ **Заявление подано!**\n"
            "Ваша заявка отправлена на рассмотрение командования.\n"
            "Ожидайте ответа в течение 24 часов.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import traceback, logging
        tb = traceback.format_exc()
        logging.getLogger('rosguard.applications').error(
            f"ApplicationModal.on_error [{self.app_type}]: {error}\n{tb}"
        )
        msg = f"❌ Ошибка при отправке заявления: `{type(error).__name__}: {error}`"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


# ─────────────────────────────────────────────
#  МОДАЛЬНАЯ ФОРМА — ПЕРЕВОД / ВОССТАНОВЛЕНИЕ (5 полей)
# ─────────────────────────────────────────────

class TransferModal(discord.ui.Modal, title="🔄 Заявление — Перевод/Восстановление"):
    static_id = discord.ui.TextInput(
        label="Статик (игровой ID)",
        placeholder="Например: 123-123",
        min_length=1,
        max_length=20,
    )
    full_name = discord.ui.TextInput(
        label="ФИО персонажа",
        placeholder="Например: Алексей Иванов",
        min_length=3,
        max_length=64,
    )
    prev_structure = discord.ui.TextInput(
        label="Из какой гос. структуры",
        placeholder="Например: ОМОН, СОБР, МЧС...",
        min_length=2,
        max_length=100,
    )
    prev_rank = discord.ui.TextInput(
        label="Прежнее звание",
        placeholder="Ваше звание в предыдущей структуре",
        min_length=2,
        max_length=64,
    )
    military_id = discord.ui.TextInput(
        label="Военный билет (да / нет)",
        placeholder="Введите: «да» — есть, «нет» — отсутствует",
        min_length=2,
        max_length=3,
    )

    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog
        self.app_type = "transfer"

    async def on_submit(self, interaction: discord.Interaction):
        mil_val = self.military_id.value.strip().lower()
        VALID = {"да", "нет", "da", "net", "yes", "no"}
        if mil_val not in VALID:
            await interaction.response.send_message(
                "❌ В поле **Военный билет** укажите только `да` или `нет`.",
                ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        config = self.cog.bot.config

        app_id = await self.cog.bot.db.add_application(
            discord_id=str(user.id),
            game_name=self.full_name.value.strip(),
            age="—",
            reason=f"Перевод/Восстановление из: {self.prev_structure.value.strip()}",
            extra={
                "static_id":      self.static_id.value.strip(),
                "military_id":    self.military_id.value.strip(),
                "app_type":       "transfer",
                "prev_structure": self.prev_structure.value.strip(),
                "prev_rank":      self.prev_rank.value.strip(),
            }
        )

        candidate_role_id = config["roles"].get("candidate", 0)
        if candidate_role_id:
            role = interaction.guild.get_role(candidate_role_id)
            if role and role not in user.roles:
                try:
                    await user.add_roles(role, reason="Подача заявления на перевод")
                except Exception:
                    pass

        embed = discord.Embed(
            title=f"📨 Новое заявление #{app_id}",
            description="**Тип:** 🔄 Перевод/Восстановление",
            color=0xF39C12,
            timestamp=datetime.utcnow(),
        )
        embed.set_author(name=f"{user.display_name} ({user})", icon_url=user.display_avatar.url)
        embed.add_field(name="👤 ФИО персонажа",       value=self.full_name.value.strip(),      inline=True)
        embed.add_field(name="🎮 Статик (ID)",         value=self.static_id.value.strip(),      inline=True)
        embed.add_field(name="🏛️ Из какой структуры", value=self.prev_structure.value.strip(),  inline=False)
        embed.add_field(name="🏅 Прежнее звание",      value=self.prev_rank.value.strip(),       inline=True)
        embed.add_field(name="🪖 Военный билет",       value=self.military_id.value.strip(),     inline=True)
        embed.add_field(name="🏷️ Discord",             value=user.mention,                       inline=True)
        embed.set_footer(text=f"ID заявления: {app_id} • ID пользователя: {user.id}")

        log_ch_id = config["channels"].get("applications_log", 0)
        log_ch = interaction.guild.get_channel(log_ch_id)
        view = ApplicationDecisionView(self.cog, app_id, str(user.id),
                                       self.full_name.value.strip(), "transfer")

        commander_ids = config["roles"].get("commander_roles", [])
        if isinstance(commander_ids, int):
            commander_ids = [commander_ids]
        ping = " ".join(f"<@&{r}>" for r in commander_ids if r)

        if log_ch:
            msg = await log_ch.send(
                content=f"{ping}\n📨 Новое заявление (Перевод/Восстановление) от {user.mention}!" if ping
                        else f"📨 Новое заявление (Перевод/Восстановление) от {user.mention}!",
                embed=embed,
                view=view,
            )
            await self.cog.bot.db.set_application_message(app_id, str(msg.id), str(log_ch.id))

        await interaction.followup.send(
            "✅ **Заявление подано!**\n"
            "Ваша заявка на перевод/восстановление отправлена на рассмотрение командования.\n"
            "Ожидайте ответа в течение 24 часов.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import traceback, logging
        logging.getLogger('rosguard.applications').error(
            f"TransferModal.on_error: {error}\n{traceback.format_exc()}"
        )
        msg = f"❌ Ошибка при отправке заявления: `{type(error).__name__}: {error}`"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


# ─────────────────────────────────────────────
#  МОДАЛЬНАЯ ФОРМА ГОС.СОТРУДНИК — 4 поля
# ─────────────────────────────────────────────

class GosModal(discord.ui.Modal, title="🏗️ Заявление — Гос.Сотрудник"):
    static_id = discord.ui.TextInput(
        label="Статик ID",
        placeholder="Например: 123-123",
        min_length=1,
        max_length=20,
    )
    full_name = discord.ui.TextInput(
        label="ФИО",
        placeholder="Например: Алексей Иванов",
        min_length=3,
        max_length=64,
    )
    gos_structure = discord.ui.TextInput(
        label="Название Гос.Структуры",
        placeholder="Например: Мёрия, Прокуратура, Администрация...",
        min_length=2,
        max_length=100,
    )
    rank = discord.ui.TextInput(
        label="Звание",
        placeholder="Ваше звание / должность",
        min_length=2,
        max_length=64,
    )

    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog
        self.app_type = "gos"

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        config = self.cog.bot.config
        game_name = self.full_name.value.strip()

        app_id = await self.cog.bot.db.add_application(
            discord_id=str(user.id),
            game_name=game_name,
            age="—",
            reason=f"Гос.Структура: {self.gos_structure.value.strip()}",
            experience=self.rank.value.strip(),
            extra={
                "static_id":   self.static_id.value.strip(),
                "military_id": "—",
                "app_type":    "gos",
            }
        )

        candidate_rid = config["roles"].get("candidate", 0)
        if candidate_rid:
            role = interaction.guild.get_role(candidate_rid)
            if role and role not in user.roles:
                try:
                    await user.add_roles(role, reason="Подача заявления Гос.Сотрудник")
                except Exception:
                    pass

        embed = discord.Embed(
            title=f"📨 Новое заявление #{app_id}",
            description="**Тип:** 🏗️ Гос.Сотрудник",
            color=0x2ECC71,
            timestamp=datetime.utcnow(),
        )
        embed.set_author(name=f"{user.display_name} ({user})", icon_url=user.display_avatar.url)
        embed.add_field(name="👤 ФИО",                      value=game_name,                          inline=True)
        embed.add_field(name="🎮 Статик ID",                value=self.static_id.value.strip(),       inline=True)
        embed.add_field(name="🏗️ Название Гос.Структуры",  value=self.gos_structure.value.strip(),   inline=False)
        embed.add_field(name="🏅 Звание",                   value=self.rank.value.strip(),            inline=True)
        embed.add_field(name="🏷️ Discord",                  value=user.mention,                       inline=True)
        embed.set_footer(text=f"ID заявления: {app_id} • ID пользователя: {user.id}")

        log_ch_id = config["channels"].get("applications_log", 0)
        log_ch = interaction.guild.get_channel(log_ch_id)
        view = ApplicationDecisionView(self.cog, app_id, str(user.id), game_name, "gos")

        commander_ids = config["roles"].get("commander_roles", [])
        if isinstance(commander_ids, int):
            commander_ids = [commander_ids]
        ping = " ".join(f"<@&{r}>" for r in commander_ids if r)

        if log_ch:
            msg = await log_ch.send(
                content=f"{ping}\n📨 Новое заявление Гос.Сотрудник от {user.mention}!" if ping
                        else f"📨 Новое заявление Гос.Сотрудник от {user.mention}!",
                embed=embed, view=view,
            )
            await self.cog.bot.db.set_application_message(app_id, str(msg.id), str(log_ch.id))

        await interaction.followup.send(
            "✅ **Заявление подано!**\n"
            "Ваша заявка отправлена на рассмотрение командования.\n"
            "Ожидайте ответа в течение 24 часов.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        import traceback, logging
        logging.getLogger('rosguard.applications').error(
            f"GosModal.on_error: {error}\n{traceback.format_exc()}"
        )
        msg = f"❌ Ошибка: `{type(error).__name__}: {error}`"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


# ─────────────────────────────────────────────
#  КНОПКИ ОДОБРЕНИЯ / ОТКЛОНЕНИЯ
# ─────────────────────────────────────────────

class ApplicationDecisionView(discord.ui.View):
    def __init__(self, cog, app_id: int, user_id: str, game_name: str, app_type: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.app_id = app_id
        self.user_id = user_id
        self.game_name = game_name
        self.app_type = app_type

    @discord.ui.button(label="✅ Одобрить", style=discord.ButtonStyle.success,
                        custom_id="app_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_commander(interaction):
            await interaction.response.send_message(
                "❌ Только командиры могут одобрять заявления!", ephemeral=True
            )
            return
        await self._process(interaction, approved=True)

    @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger,
                        custom_id="app_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_commander(interaction):
            await interaction.response.send_message(
                "❌ Только командиры могут отклонять заявления!", ephemeral=True
            )
            return
        await self._process(interaction, approved=False)

    @staticmethod
    def _has_military_id(value: str) -> bool:
        """Вернут True если пользователь ответил «да» (роль выдаём),
        и False если ответил «нет» (роль не выдаём)."""
        YES_VALUES = {"да", "da", "yes"}
        return value.strip().lower() in YES_VALUES

    async def _process(self, interaction: discord.Interaction, approved: bool):
        await interaction.response.defer()

        config = self.cog.bot.config
        guild = interaction.guild
        app = await self.cog.bot.db.get_application(self.app_id)

        if app and app["status"] != "pending":
            await interaction.followup.send("⚠️ Заявление уже рассмотрено!", ephemeral=True)
            return

        status = "approved" if approved else "rejected"
        await self.cog.bot.db.update_application(self.app_id, status, str(interaction.user.id))

        target = guild.get_member(int(self.user_id))

        import logging
        log = logging.getLogger('rosguard.applications')

        if approved and target:
            roles = config["roles"]
            guild_roles_to_add = []

            # Убираем роль кандидата
            candidate_rid = roles.get("candidate", 0)
            if candidate_rid:
                r = guild.get_role(candidate_rid)
                if r and r in target.roles:
                    try:
                        await target.remove_roles(r)
                    except Exception as e:
                        log.warning(f"remove_roles candidate failed: {e}")

            if self.app_type in ("interview", "transfer"):
                # ── Читаем extra из БД ──
                app_data = await self.cog.bot.db.get_application(self.app_id)
                # military_id хранится как отдельная колонка в БД
                military_id_value = ""
                if app_data:
                    # Пробуем прямую колонку
                    if hasattr(app_data, "__getitem__"):
                        try:
                            military_id_value = str(app_data["military_id"] or "")
                        except (KeyError, TypeError):
                            military_id_value = ""
                give_military_id_role = self._has_military_id(military_id_value)
                log.info(f"Военный билет значение из БД: {military_id_value!r}, выдаём роль: {give_military_id_role}")

                # ── Базовые роли курсанта ──
                cadet_role_keys = [
                    "cadet",            # Курсант АВНГ
                    "sotrudnik_fsvng",  # Сотрудник ФСВНГ
                    "div_avng",         # Академия Войск Национальной Гвардии
                    "zvanie_separator", # ──── | Звание | ────
                    "private",          # Рядовой
                ]
                for key in cadet_role_keys:
                    rid = roles.get(key, 0)
                    if rid:
                        r = guild.get_role(rid)
                        if r and r not in target.roles:
                            guild_roles_to_add.append(r)

                # ── Роль военного билета — только если билет есть ──
                if give_military_id_role:
                    rid = roles.get("voennyy_bilet", 0)
                    if rid:
                        r = guild.get_role(rid)
                        if r and r not in target.roles:
                            guild_roles_to_add.append(r)
                else:
                    log.info(f"⚠️ Военный билет не выдаётся {target} (указано: '{military_id_value}')")

                # ── Для перевода/восстановления — дополнительные роли ──
                if self.app_type == "transfer":
                    for key in ("pereattestaciya", "perevod_vosstanovlenie"):
                        rid = roles.get(key, 0)
                        if rid:
                            r = guild.get_role(rid)
                            if r and r not in target.roles:
                                guild_roles_to_add.append(r)
                    log.info(f"🔄 Перевод: выдаём роли переаттестации для {target}")

                log.info(f"Роли для добавления ({target}): {[r.name for r in guild_roles_to_add]}")
                log.info(f"Позиция роли бота: {guild.me.top_role.position}, топ роль юзера: {target.top_role.position}")
                if guild_roles_to_add:
                    try:
                        await target.add_roles(*guild_roles_to_add, reason="Зачислен в Академию АВНГ")
                        log.info(f"✅ Роли выданы курсанту {target}")
                    except discord.Forbidden as e:
                        log.error(f"❌ add_roles Forbidden для {target}: {e}. Бот={guild.me.top_role.position}, Юзер={target.top_role.position}")
                    except Exception as e:
                        log.error(f"❌ add_roles ошибка для {target}: {e}")

                await self.cog.bot.db.add_member(str(target.id), self.game_name, str(interaction.user.id))
                await self.cog.bot.db.update_member(str(target.id), status="cadet", rank_id=1,
                                                     position_prefix="Курсант")

                # Никнейм: «Курсант | Алексей Накамура»
                nick = f"Курсант | {self.game_name}"[:32]
                try:
                    await target.edit(nick=nick)
                    log.info(f"Ник изменён: {target} -> {nick}")
                except discord.Forbidden:
                    log.warning(
                        f"Не могу изменить ник {target} (Forbidden). "
                        f"Позиция роли бота: {target.guild.me.top_role.position}, "
                        f"Позиция роли пользователя: {target.top_role.position}"
                    )
                except Exception as e:
                    log.error(f"Ошибка ника: {e}")

            elif self.app_type == "gos":
                from utils.constants import RANK_BY_NAME

                app_data = await self.cog.bot.db.get_application(self.app_id)
                chosen_rank_name = (app_data.get("experience") or "").strip() if app_data else ""

                for key in ("gossotr", "zvanie_separator"):
                    rid = roles.get(key, 0)
                    if rid:
                        r = guild.get_role(rid)
                        if r and r not in target.roles:
                            guild_roles_to_add.append(r)

                rank_match = RANK_BY_NAME.get(chosen_rank_name)
                if not rank_match:
                    for name, data in RANK_BY_NAME.items():
                        if name.lower() == chosen_rank_name.lower():
                            rank_match = data
                            break
                if rank_match:
                    rid = roles.get(rank_match["role_key"], 0)
                    if rid:
                        rank_role = guild.get_role(rid)
                        if rank_role and rank_role not in target.roles:
                            guild_roles_to_add.append(rank_role)

                log.info(f"Роли для добавления гос ({target}): {[r.name for r in guild_roles_to_add]}")
                if guild_roles_to_add:
                    try:
                        await target.add_roles(*guild_roles_to_add, reason="Гос.Сотрудник одобрен")
                        log.info(f"✅ Роли выданы гос.сотруднику {target}")
                    except discord.Forbidden as e:
                        log.error(f"❌ add_roles Forbidden гос {target}: {e}. Бот={guild.me.top_role.position}, Юзер={target.top_role.position}")
                    except Exception as e:
                        log.error(f"❌ add_roles ошибка гос {target}: {e}")

                await self.cog.bot.db.add_member(str(target.id), self.game_name, str(interaction.user.id))
                await self.cog.bot.db.update_member(str(target.id), status="active",
                                                     rank_id=rank_match["id"] if rank_match else 2)

                try:
                    await target.edit(nick=self.game_name[:32])
                except discord.Forbidden:
                    pass

            # DM уведомление
            try:
                e = discord.Embed(
                    title="✅ Заявление одобрено!",
                    description=(
                        "Добро пожаловать в ряды Росгвардии!\n\n"
                        + ("Вы зачислены в **Академию АВНГ** как Курсант.\n"
                           "Ожидайте назначения инструктора."
                           if self.app_type in ("interview", "transfer")
                           else "Вам выдана роль **Государственного Сотрудника**.")
                    ),
                    color=COLORS["success"],
                )
                e.add_field(name="Одобрил", value=interaction.user.mention)
                await target.send(embed=e)
            except Exception:
                pass

        elif not approved and target:
            # Убираем роль кандидата
            candidate_rid = config["roles"].get("candidate", 0)
            if candidate_rid:
                r = guild.get_role(candidate_rid)
                if r and r in target.roles:
                    try:
                        await target.remove_roles(r)
                    except Exception:
                        pass

            # Выдаём роль Отказано
            otkazano_rid = config["roles"].get("otkazano", 0)
            if otkazano_rid:
                r = guild.get_role(otkazano_rid)
                if r:
                    try:
                        await target.add_roles(r, reason="Заявление отклонено")
                    except Exception:
                        pass

            # DM уведомление
            try:
                e = discord.Embed(
                    title="❌ Заявление отклонено",
                    description="Ваше заявление на вступление в Росгвардию отклонено командованием.",
                    color=COLORS["error"],
                )
                e.add_field(name="Рассмотрел", value=interaction.user.mention)
                await target.send(embed=e)
            except Exception:
                pass

        # Обновляем embed сообщения
        action = "✅ Одобрено" if approved else "❌ Отклонено"
        color  = COLORS["success"] if approved else COLORS["error"]
        new_embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        new_embed.color = color
        new_embed.add_field(
            name=f"{action} командиром",
            value=f"{interaction.user.mention}\n<t:{int(datetime.utcnow().timestamp())}:R>",
            inline=False,
        )
        await interaction.message.edit(embed=new_embed, view=None)
        await interaction.followup.send(
            f"{action}: заявление #{self.app_id}", ephemeral=True
        )


# ─────────────────────────────────────────────
#  ПАНЕЛЬ — 3 кнопки
# ─────────────────────────────────────────────

class ApplicationPanelView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="📢  Собеседование",
        style=discord.ButtonStyle.primary,
        custom_id="app_panel_interview",
        row=0,
    )
    async def interview(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            ApplicationModal(self.cog, "interview")
        )

    @discord.ui.button(
        label="🔄  Перевод / Восстановление",
        style=discord.ButtonStyle.secondary,
        custom_id="app_panel_transfer",
        row=0,
    )
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            TransferModal(self.cog)
        )

    @discord.ui.button(
        label="🏙️  Гос. Сотрудник",
        style=discord.ButtonStyle.success,
        custom_id="app_panel_gos",
        row=0,
    )
    async def gos(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            GosModal(self.cog)
        )


# ─────────────────────────────────────────────
#  COG
# ─────────────────────────────────────────────

class ApplicationsCog(commands.Cog, name="Заявления"):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(ApplicationPanelView(self))
        bot.add_view(ApplicationDecisionView(self, 0, "0", "", "interview"))

    @app_commands.command(
        name="setup-заявки",
        description="📋 Разместить панель подачи заявлений в канале получение-роли"
    )
    @commander_only()
    async def setup_applications(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        config = self.bot.config
        ch_id = config["channels"].get("applications", 0)
        channel = interaction.guild.get_channel(ch_id)

        if not channel:
            await interaction.followup.send(
                "❌ Канал `applications` не найден в config.json!", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📋 Подача заявления в Росгвардию",
            color=0x1A237E,
        )
        embed.description = (
            "\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\n"
            "🔷 Выберите нужный тип заявления и нажмите кнопку ниже.\n"
            "\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\u2003\n"
            "―――――――――――――――――――――――\n"
            "📢 **СОБЕСЕДОВАНИЕ**\n"
            "› Первичное вступление в Росгвардию с нуля.\n"
            "› Обязательно пройдёте Курс Академии АВНГ.\n\n"
            "🔄 **ПЕРЕВОД / ВОССТАНОВЛЕНИЕ**\n"
            "› Перевод из другого подразделения или восстановление после отсутствия.\n"
            "› Укажите прежнюю структуру и звание.\n\n"
            "🏙️ **ГОС. СОТРУДНИК**\n"
            "› Оформление статуса государственного сотрудника.\n"
            "› Укажите структуру и звание в вашей организации.\n"
            "―――――――――――――――――――――――\n"
            "ℹ️ Заявления рассматриваются в течение **24 часов**. Убедитесь в достоверности введённых данных."
        )
        embed.set_footer(
            text="Росгвардия УФСВНГ • Нажмите на кнопку для подачи заявления",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

        view = ApplicationPanelView(self)
        await channel.send(embed=embed, view=view)

        await interaction.followup.send(
            f"✅ Панель заявлений размещена в {channel.mention}!", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(ApplicationsCog(bot))
