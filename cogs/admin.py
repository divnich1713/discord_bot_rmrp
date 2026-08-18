"""
Admin — Административные команды: настройка, синхронизация, ручное управление
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import commander_only
from utils.constants import COLORS, RANK_BY_ID, RANKS, STATUSES


class AdminCog(commands.Cog, name="Администрирование"):
    def __init__(self, bot):
        self.bot = bot

    admin_group = app_commands.Group(name="админ", description="⚙️ Администрирование бота")

    @admin_group.command(name="добавить", description="➕ Вручную добавить участника в базу")
    @app_commands.describe(
        участник="Discord участник",
        никнейм="Игровой никнейм (ФИО персонажа)",
        звание_id="Номер звания (2=Рядовой, 3=Ефрейтор...)",
    )
    @commander_only()
    async def admin_add(self, interaction: discord.Interaction,
                         участник: discord.Member,
                         никнейм: str,
                         звание_id: int = 2):
        await interaction.response.defer(ephemeral=True)

        from datetime import datetime
        await self.bot.db.update_member.__func__  # check exists
        # Используем прямой add или update
        existing = await self.bot.db.get_member(str(участник.id))
        if existing:
            await self.bot.db.update_member(str(участник.id), game_name=никнейм,
                                             rank_id=звание_id, status="active")
        else:
            from database import Database
            now = datetime.utcnow().isoformat()
            import aiosqlite
            async with aiosqlite.connect("rosguard.db") as db:
                await db.execute(
                    """INSERT OR REPLACE INTO members
                       (discord_id, game_name, rank_id, status, joined_faction, added_by)
                       VALUES (?, ?, ?, 'active', ?, ?)""",
                    (str(участник.id), никнейм, звание_id, now, str(interaction.user.id)),
                )
                await db.commit()

        # Применяем роль
        rank = RANK_BY_ID.get(звание_id)
        if rank:
            config = self.bot.config
            for r in RANKS:
                rid = config["roles"].get(r["role_key"], 0)
                if rid:
                    role = interaction.guild.get_role(rid)
                    if role and role in участник.roles:
                        try:
                            await участник.remove_roles(role)
                        except Exception:
                            pass
            new_rid = config["roles"].get(rank["role_key"], 0)
            if new_rid:
                new_role = interaction.guild.get_role(new_rid)
                if new_role:
                    try:
                        await участник.add_roles(new_role)
                    except Exception:
                        pass
            try:
                await участник.edit(nick=никнейм)  # Только ФИО
            except discord.Forbidden:
                pass

        await interaction.followup.send(
            f"✅ {участник.mention} добавлен/обновлён: **{никнейм}** | "
            f"**{rank['name'] if rank else звание_id}**",
            ephemeral=True,
        )

    @admin_group.command(name="удалить", description="🗑️ Удалить участника из базы данных")
    @app_commands.describe(участник="Участник для удаления")
    @commander_only()
    async def admin_remove(self, interaction: discord.Interaction,
                            участник: discord.Member):
        await interaction.response.defer(ephemeral=True)
        import aiosqlite
        async with aiosqlite.connect("rosguard.db") as db:
            await db.execute("DELETE FROM members WHERE discord_id=?", (str(участник.id),))
            await db.commit()
        await interaction.followup.send(
            f"✅ {участник.mention} удалён из базы данных.", ephemeral=True
        )

    @admin_group.command(name="статус", description="🔄 Изменить статус участника вручную")
    @app_commands.describe(участник="Участник", статус="Новый статус")
    @app_commands.choices(статус=[
        app_commands.Choice(name="🟢 Действующий",       value="active"),
        app_commands.Choice(name="🟡 Курсант",            value="cadet"),
        app_commands.Choice(name="🔴 Не прошёл академию", value="failed"),
        app_commands.Choice(name="⚫ Уволен",              value="fired"),
        app_commands.Choice(name="🟠 В отпуске",          value="vacation"),
    ])
    @commander_only()
    async def admin_status(self, interaction: discord.Interaction,
                            участник: discord.Member,
                            статус: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            await interaction.followup.send("❌ Участник не найден в базе!", ephemeral=True)
            return
        await self.bot.db.update_member(str(участник.id), status=статус.value)
        label = STATUSES.get(статус.value, статус.value)
        await interaction.followup.send(
            f"✅ Статус {участник.mention} изменён на **{label}**.", ephemeral=True
        )

    @admin_group.command(name="отпуск", description="🟠 Отправить/вернуть из отпуска")
    @app_commands.describe(участник="Участник")
    @commander_only()
    async def admin_vacation(self, interaction: discord.Interaction,
                              участник: discord.Member):
        await interaction.response.defer(ephemeral=True)
        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            await interaction.followup.send("❌ Участник не найден!", ephemeral=True)
            return

        config = self.bot.config
        vacation_role_id = config["roles"].get("vacation", 0)
        vacation_role = interaction.guild.get_role(vacation_role_id) if vacation_role_id else None

        if member_data["status"] == "vacation":
            # Возвращаем
            await self.bot.db.update_member(str(участник.id), status="active")
            if vacation_role and vacation_role in участник.roles:
                await участник.remove_roles(vacation_role)
            await interaction.followup.send(
                f"✅ {участник.mention} вернулся из отпуска.", ephemeral=True
            )
        else:
            # Отправляем в отпуск
            await self.bot.db.update_member(str(участник.id), status="vacation")
            if vacation_role:
                await участник.add_roles(vacation_role)
            await interaction.followup.send(
                f"✅ {участник.mention} отправлен в отпуск.", ephemeral=True
            )

    @admin_group.command(name="синхронизировать",
                          description="🔄 Синхронизировать роли участника по базе данных")
    @app_commands.describe(участник="Участник для синхронизации")
    @commander_only()
    async def admin_sync(self, interaction: discord.Interaction,
                          участник: discord.Member):
        await interaction.response.defer(ephemeral=True)
        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            await interaction.followup.send("❌ Участник не найден в базе!", ephemeral=True)
            return

        config = self.bot.config
        guild = interaction.guild
        rank_id = member_data["rank_id"]
        rank = RANK_BY_ID.get(rank_id)

        # Убираем все роли фракции
        all_keys = [r["role_key"] for r in RANKS] + ["fired", "vacation", "failed_cadet", "candidate"]
        for key in all_keys:
            rid = config["roles"].get(key, 0)
            if rid:
                role = guild.get_role(rid)
                if role and role in участник.roles:
                    try:
                        await участник.remove_roles(role)
                    except Exception:
                        pass

        # Выдаём нужную роль в зависимости от статуса
        status = member_data["status"]
        if status == "fired":
            role_key = "fired"
        elif status == "failed":
            role_key = "failed_cadet"
        elif status == "vacation":
            role_key = "vacation"
        elif status == "cadet":
            role_key = "cadet"
        elif rank:
            role_key = rank["role_key"]
        else:
            role_key = None

        if role_key:
            rid = config["roles"].get(role_key, 0)
            if rid:
                role = guild.get_role(rid)
                if role:
                    try:
                        await участник.add_roles(role)
                    except Exception:
                        pass

        # Никнейм — только ФИО персонажа, без ранговых префиксов
        if status not in ("fired", "failed"):
            try:
                await участник.edit(nick=member_data['game_name'])
            except discord.Forbidden:
                pass

        await interaction.followup.send(
            f"✅ Роли {участник.mention} синхронизированы с базой данных.", ephemeral=True
        )

    @admin_group.command(name="статистика", description="📊 Статистика бота")
    @commander_only()
    async def admin_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        import aiosqlite
        async with aiosqlite.connect("rosguard.db") as db:
            active = (await (await db.execute(
                "SELECT COUNT(*) FROM members WHERE status='active'"
            )).fetchone())[0]
            cadets = (await (await db.execute(
                "SELECT COUNT(*) FROM members WHERE status='cadet'"
            )).fetchone())[0]
            failed = (await (await db.execute(
                "SELECT COUNT(*) FROM members WHERE status='failed'"
            )).fetchone())[0]
            fired = (await (await db.execute(
                "SELECT COUNT(*) FROM members WHERE status='fired'"
            )).fetchone())[0]
            total_reports = (await (await db.execute(
                "SELECT COUNT(*) FROM reports"
            )).fetchone())[0]
            total_bonuses = (await (await db.execute(
                "SELECT COUNT(*) FROM bonuses"
            )).fetchone())[0]
            total_apps = (await (await db.execute(
                "SELECT COUNT(*) FROM applications"
            )).fetchone())[0]

        e = discord.Embed(
            title="📊 Статистика Росгвардии",
            color=COLORS["rosguard"],
        )
        e.add_field(name="🟢 Действующих", value=str(active), inline=True)
        e.add_field(name="🟡 Курсантов",  value=str(cadets), inline=True)
        e.add_field(name="🔴 Не прошли академию", value=str(failed), inline=True)
        e.add_field(name="⚫ Уволено", value=str(fired), inline=True)
        e.add_field(name="📋 Всего рапортов", value=str(total_reports), inline=True)
        e.add_field(name="⭐ Всего премий", value=str(total_bonuses), inline=True)
        e.add_field(name="📝 Всего заявок", value=str(total_apps), inline=True)
        await interaction.followup.send(embed=e, ephemeral=True)

    @admin_group.command(name="помощь", description="❓ Список всех команд бота")
    async def admin_help(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        e = discord.Embed(
            title="📖 Команды бота Росгвардия",
            color=COLORS["rosguard"],
        )
        e.add_field(name="🆕 Вступление", value=(
            "`/анкета` — подать заявку на вступление"
        ), inline=False)
        e.add_field(name="🎓 Академия (инструкторы)", value=(
            "`/академия список` — курсанты\n"
            "`/академия выпустить @user` — выпуск\n"
            "`/академия провалить @user` — отчисление\n"
            "`/тест создать` — создать тест\n"
            "`/тест вопрос` — добавить вопрос\n"
            "`/тест назначить @user id` — назначить тест\n"
            "`/тест сброс_попыток @user id` — сброс\n"
            "`/практика добавить @user` — задание\n"
            "`/практика выполнил id` — зачесть задание"
        ), inline=False)
        e.add_field(name="📝 Для курсантов", value=(
            "`/тест пройти id` — пройти тест\n"
            "`/мои-задания` — мои задания"
        ), inline=False)
        e.add_field(name="📋 Рапорты (офицеры)", value=(
            "`/рапорт повышение @user звание` \n"
            "`/рапорт увольнение @user причина`\n"
            "`/рапорт взыскание @user причина`\n"
            "`/рапорт работа текст` — отчёт о работе\n"
            "`/рапорт самоотвод причина`"
        ), inline=False)
        e.add_field(name="⭐ Прочее", value=(
            "`/премия @user причина` — выдать премию\n"
            "`/досье [@user]` — личное дело\n"
            "`/состав` — весь личный состав\n"
            "`/топ` — рейтинг\n"
            "`/повысить / /понизить` — прямое изменение звания"
        ), inline=False)
        e.add_field(name="⚙️ Администратор", value=(
            "`/админ добавить` — добавить в базу\n"
            "`/админ удалить` — удалить из базы\n"
            "`/админ статус` — изменить статус\n"
            "`/админ отпуск` — отпуск\n"
            "`/админ синхронизировать` — синхронизация ролей\n"
            "`/админ статистика` — общая статистика"
        ), inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    # ─────────────── ВЗЫСКАНИЯ ───────────────

    @admin_group.command(name="взыскание", description="⚠️ Выдать взыскание сотруднику")
    @app_commands.describe(
        участник="Кому выдать взыскание",
        причина="Причина взыскания",
    )
    @app_commands.choices(тип=[
        app_commands.Choice(name="⚠️ Предупреждение", value="warn"),
        app_commands.Choice(name="🔴 Выговор",         value="reprimand"),
    ])
    @commander_only()
    async def admin_reprimand(self, interaction: discord.Interaction,
                               участник: discord.Member,
                               причина: str,
                               тип: app_commands.Choice[str] = None):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            await interaction.followup.send("❌ Участник не найден в базе!", ephemeral=True)
            return

        rep_type = тип.value if тип else "warn"
        await self.bot.db.add_reprimand(str(участник.id), причина, str(interaction.user.id), rep_type)

        # Считаем текущие взыскания
        reprimands = await self.bot.db.get_member_reprimands(str(участник.id))
        warns    = [r for r in reprimands if r["type"] == "warn"]
        reps     = [r for r in reprimands if r["type"] == "reprimand"]

        config = self.bot.config
        guild  = interaction.guild

        # Убираем все роли взысканий
        disc_keys = ["warn_1", "warn_2", "reprimand_1", "reprimand_2"]
        for key in disc_keys:
            rid = config["roles"].get(key, 0)
            if rid:
                role = guild.get_role(rid)
                if role and role in участник.roles:
                    try:
                        await участник.remove_roles(role)
                    except Exception:
                        pass

        # Назначаем нужную роль взыскания
        role_key = None
        if len(reps) >= 2:
            role_key = "reprimand_2"   # Выговор 2/2
        elif len(reps) == 1:
            role_key = "reprimand_1"   # Выговор 1/2
        elif len(warns) >= 2:
            role_key = "warn_2"        # Предупреждение 2/3
        elif len(warns) == 1:
            role_key = "warn_1"        # Предупреждение 1/3

        label = "—"
        if role_key:
            rid = config["roles"].get(role_key, 0)
            if rid:
                role = guild.get_role(rid)
                if role:
                    try:
                        await участник.add_roles(role, reason=f"Взыскание: {причина}")
                        label = role.name
                    except Exception:
                        pass

        # DM
        icons = {"warn": "⚠️", "reprimand": "🔴"}
        try:
            e = discord.Embed(
                title=f"{icons.get(rep_type, '⚠️')} Вам выдано взыскание",
                description=f"**Причина:** {причина}",
                color=COLORS["warning"] if rep_type == "warn" else COLORS["error"],
            )
            e.add_field(name="Выдал", value=interaction.user.mention)
            e.add_field(name="Всего предупреждений", value=str(len(warns)), inline=True)
            e.add_field(name="Всего выговоров",      value=str(len(reps)),  inline=True)
            await участник.send(embed=e)
        except Exception:
            pass

        # Лог
        log_ch_id = config["channels"].get("bot_log", 0)
        log_ch = guild.get_channel(log_ch_id)
        if log_ch:
            e = discord.Embed(
                title=f"⚠️ Взыскание выдано — {участник}",
                description=(
                    f"**Причина:** {причина}\n"
                    f"**Роль:** {label}\n"
                    f"Выдал: {interaction.user.mention}"
                ),
                color=COLORS["warning"],
            )
            await log_ch.send(embed=e)

        await interaction.followup.send(
            f"✅ Взыскание выдано {участник.mention}. Роль: **{label}**\n"
            f"📊 Предупреждений: {len(warns)} | Выговоров: {len(reps)}",
            ephemeral=True,
        )

    @admin_group.command(name="снять_взыскание", description="✅ Снять все взыскания с сотрудника")
    @app_commands.describe(участник="С кого снять взыскания")
    @commander_only()
    async def admin_remove_reprimand(self, interaction: discord.Interaction,
                                      участник: discord.Member):
        await interaction.response.defer(ephemeral=True)

        config = self.bot.config
        guild  = interaction.guild

        # Убираем все роли взысканий
        for key in ["warn_1", "warn_2", "reprimand_1", "reprimand_2"]:
            rid = config["roles"].get(key, 0)
            if rid:
                role = guild.get_role(rid)
                if role and role in участник.roles:
                    try:
                        await участник.remove_roles(role)
                    except Exception:
                        pass

        # Удаляем из БД
        import aiosqlite
        async with aiosqlite.connect("rosguard.db") as db:
            await db.execute("DELETE FROM reprimands WHERE member_id=?", (str(участник.id),))
            await db.commit()

        try:
            e = discord.Embed(
                title="✅ Взыскания сняты",
                description="Все ваши взыскания сняты командованием.",
                color=COLORS["success"],
            )
            e.add_field(name="Снял", value=interaction.user.mention)
            await участник.send(embed=e)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ Все взыскания с {участник.mention} сняты.", ephemeral=True
        )

    # ─────────────── ОДОБРЕНО / ОТКАЗАНО ───────────────

    @admin_group.command(name="одобрить", description="✅ Выдать роль Одобрено участнику")
    @app_commands.describe(участник="Участник")
    @commander_only()
    async def admin_approve_role(self, interaction: discord.Interaction,
                                  участник: discord.Member):
        await interaction.response.defer(ephemeral=True)
        config = self.bot.config
        guild  = interaction.guild

        # Убираем Отказано, добавляем Одобрено
        for key in ["otkazano", "odobreno"]:
            rid = config["roles"].get(key, 0)
            if rid:
                role = guild.get_role(rid)
                if role:
                    if key == "otkazano" and role in участник.roles:
                        try:
                            await участник.remove_roles(role)
                        except Exception:
                            pass
                    elif key == "odobreno":
                        try:
                            await участник.add_roles(role, reason="Одобрено командованием")
                        except Exception:
                            pass

        await interaction.followup.send(
            f"✅ {участник.mention} — роль **Одобрено** выдана.", ephemeral=True
        )

    @admin_group.command(name="отказать", description="❌ Выдать роль Отказано участнику")
    @app_commands.describe(участник="Участник")
    @commander_only()
    async def admin_reject_role(self, interaction: discord.Interaction,
                                 участник: discord.Member):
        await interaction.response.defer(ephemeral=True)
        config = self.bot.config
        guild  = interaction.guild

        for key in ["odobreno", "otkazano"]:
            rid = config["roles"].get(key, 0)
            if rid:
                role = guild.get_role(rid)
                if role:
                    if key == "odobreno" and role in участник.roles:
                        try:
                            await участник.remove_roles(role)
                        except Exception:
                            pass
                    elif key == "otkazano":
                        try:
                            await участник.add_roles(role, reason="Отказано командованием")
                        except Exception:
                            pass

        await interaction.followup.send(
            f"✅ {участник.mention} — роль **Отказано** выдана.", ephemeral=True
        )

    @admin_group.command(name="снять_статус", description="🔄 Снять роли Одобрено/Отказано")
    @app_commands.describe(участник="Участник")
    @commander_only()
    async def admin_clear_status_role(self, interaction: discord.Interaction,
                                       участник: discord.Member):
        await interaction.response.defer(ephemeral=True)
        config = self.bot.config
        guild  = interaction.guild
        for key in ["odobreno", "otkazano"]:
            rid = config["roles"].get(key, 0)
            if rid:
                role = guild.get_role(rid)
                if role and role in участник.roles:
                    try:
                        await участник.remove_roles(role)
                    except Exception:
                        pass
        await interaction.followup.send(
            f"✅ Статусные роли с {участник.mention} сняты.", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
