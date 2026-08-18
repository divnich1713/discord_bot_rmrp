"""
Academy — Академия АВНГ: управление курсантами, тесты (3 попытки), практика
"""
import json
from typing import Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import commander_only, instructor_only
from utils.constants import COLORS, MAX_TEST_ATTEMPTS, RANK_BY_ID
from utils.embeds import (cadet_list_embed, task_list_embed,
                           test_question_embed, test_result_embed)

# Хранилище активных тест-сессий в памяти {user_id: session_data}
_test_sessions: Dict[int, dict] = {}


class TestQuestionView(discord.ui.View):
    """Отображает один вопрос теста с кнопками A/B/C/D"""

    def __init__(self, cog, user_id: int, test_id: int, test_name: str,
                 questions: List[Dict], current_q: int = 0, answers: List[str] = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.test_id = test_id
        self.test_name = test_name
        self.questions = questions
        self.current_q = current_q
        self.answers = answers or []
        self._add_buttons()

    def _add_buttons(self):
        labels = [("🅐 А", "a"), ("🅑 Б", "b"), ("🅒 В", "c"), ("🅓 Г", "d")]
        for label, ans in labels:
            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                custom_id=f"test_{self.test_id}_{self.current_q}_{ans}",
            )
            btn.callback = self._make_callback(ans)
            self.add_item(btn)

    def _make_callback(self, answer: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    "❌ Это не ваш тест!", ephemeral=True
                )
                return

            # Записываем ответ
            new_answers = self.answers + [answer]
            new_q = self.current_q + 1

            if new_q >= len(self.questions):
                # Тест завершён
                await self._finish_test(interaction, new_answers)
            else:
                # Следующий вопрос
                q = self.questions[new_q]
                embed = test_question_embed(
                    self.test_name, new_q + 1, len(self.questions), q
                )
                new_view = TestQuestionView(
                    self.cog, self.user_id, self.test_id, self.test_name,
                    self.questions, new_q, new_answers,
                )
                await interaction.response.edit_message(embed=embed, view=new_view)

        return callback

    async def _finish_test(self, interaction: discord.Interaction, answers: List[str]):
        questions = self.questions
        correct = sum(
            1 for i, q in enumerate(questions)
            if i < len(answers) and answers[i] == q["correct"]
        )
        total = len(questions)
        score = int(correct / total * 100) if total > 0 else 0

        test = await self.cog.bot.db.get_test(self.test_id)
        passed = score >= (test["pass_score"] if test else 70)

        attempt_num = await self.cog.bot.db.count_test_attempts(
            str(self.user_id), self.test_id
        ) + 1

        # Записываем результат
        await self.cog.bot.db.record_test_attempt(
            member_id=str(self.user_id),
            test_id=self.test_id,
            score=score,
            passed=passed,
            answers=answers,
        )

        remaining = max(0, MAX_TEST_ATTEMPTS - attempt_num)
        embed = test_result_embed(
            self.test_name, correct, total, score, passed, attempt_num, remaining
        )

        # Лог в канал
        config = self.cog.bot.config
        guild = interaction.guild
        academy_ch_id = config["channels"].get("academy", 0)
        academy_ch = guild.get_channel(academy_ch_id) if academy_ch_id else None
        if academy_ch:
            status = "✅ Сдан" if passed else f"❌ Не сдан ({attempt_num}/3)"
            log_e = discord.Embed(
                title=f"📝 Тест: {self.test_name}",
                description=(
                    f"{interaction.user.mention} — **{score}%** ({correct}/{total}) {status}"
                ),
                color=COLORS["success"] if passed else COLORS["error"],
            )
            await academy_ch.send(embed=log_e)

        # Лог в личное дело (Форум)
        try:
            from utils.dossier_service import DossierService
            res_status = "✅ Сдан" if passed else f"❌ Не сдан (Попытка {attempt_num}/3)"
            await DossierService.log_event(
                self.cog.bot, guild, str(self.user_id),
                title="📝 Прохождение академического теста",
                description=f"Тест: **{self.test_name}** — {res_status}",
                color=COLORS["success"] if passed else COLORS["error"],
                fields=[
                    ("Результат", f"**{score}%** ({correct}/{total} правильных)", True),
                    ("Попытка", f"{attempt_num}/3", True),
                ],
                author=interaction.user,
            )
        except Exception:
            pass

        _test_sessions.pop(self.user_id, None)
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        _test_sessions.pop(self.user_id, None)


# ─────────────────────────── COG ───────────────────────────

class AcademyCog(commands.Cog, name="Академия АВНГ"):
    def __init__(self, bot):
        self.bot = bot

    # ── Группы команд ──
    academy_group = app_commands.Group(name="академия", description="🎓 Управление Академией АВНГ")
    test_group = app_commands.Group(name="тест", description="📝 Управление тестами")
    praktika_group = app_commands.Group(name="практика", description="🛠️ Практические задания")

    # ─────────────── АКАДЕМИЯ ───────────────

    @academy_group.command(name="список", description="📋 Список всех курсантов")
    @instructor_only()
    async def academy_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cadets = await self.bot.db.get_cadets()
        embed = cadet_list_embed(cadets, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @academy_group.command(name="выпустить", description="🎓 Выпустить курсанта из академии")
    @app_commands.describe(участник="Курсант для выпуска")
    @instructor_only()
    async def academy_graduate(self, interaction: discord.Interaction,
                                участник: discord.Member):
        await interaction.response.defer(ephemeral=True)
        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data or member_data["status"] != "cadet":
            await interaction.followup.send(
                "❌ Этот пользователь не является курсантом!", ephemeral=True
            )
            return

        # Проверяем выполнение заданий
        tasks = await self.bot.db.get_practical_tasks(str(участник.id))
        cadet_tests_list = await self.bot.db.get_cadet_tests(str(участник.id))

        incomplete_tasks = [t for t in tasks if not t["completed"]]
        failed_tests = []
        for t in cadet_tests_list:
            if not await self.bot.db.has_passed_test(str(участник.id), t["test_id"]):
                failed_tests.append(t["name"])

        if incomplete_tasks or failed_tests:
            msg_parts = ["⚠️ **Курсант не выполнил все задания:**"]
            if incomplete_tasks:
                msg_parts.append(f"• Незакрытые практики: {len(incomplete_tasks)}")
            if failed_tests:
                msg_parts.append(f"• Непройденные тесты: {', '.join(failed_tests)}")
            msg_parts.append("\nВсё равно выпустить? Используйте `/академия выпустить_принудительно`")
            await interaction.followup.send("\n".join(msg_parts), ephemeral=True)
            return

        await self._graduate_cadet(участник, member_data, interaction.user, interaction.guild)
        await interaction.followup.send(
            f"✅ **{member_data['game_name']}** успешно выпущен из академии и переведён в звание Сержант!",
            ephemeral=True,
        )

    @academy_group.command(name="выпустить_принудительно",
                            description="⚡ Принудительно выпустить курсанта")
    @app_commands.describe(участник="Курсант для выпуска", причина="Причина принудительного выпуска")
    @commander_only()
    async def academy_force_graduate(self, interaction: discord.Interaction,
                                      участник: discord.Member, причина: str = ""):
        await interaction.response.defer(ephemeral=True)
        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data:
            await interaction.followup.send("❌ Пользователь не найден в базе!", ephemeral=True)
            return

        await self._graduate_cadet(участник, member_data, interaction.user, interaction.guild)
        await interaction.followup.send(
            f"✅ **{member_data['game_name']}** принудительно выпущен в звании Сержант. Причина: {причина or 'не указана'}",
            ephemeral=True,
        )

    @academy_group.command(name="провалить", description="❌ Отчислить курсанта из академии")
    @app_commands.describe(участник="Курсант для отчисления", причина="Причина отчисления")
    @instructor_only()
    async def academy_fail(self, interaction: discord.Interaction,
                            участник: discord.Member, причина: str = ""):
        await interaction.response.defer(ephemeral=True)
        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data or member_data["status"] != "cadet":
            await interaction.followup.send("❌ Пользователь не является курсантом!", ephemeral=True)
            return

        await self.bot.db.update_member(str(участник.id), status="failed", rank_id=0)

        config = self.bot.config
        guild = interaction.guild

        # Убираем роль курсанта, даём роль провалившегося
        cadet_role_id = config["roles"].get("cadet", 0)
        failed_role_id = config["roles"].get("failed_cadet", 0)
        if cadet_role_id:
            r = guild.get_role(cadet_role_id)
            if r and r in участник.roles:
                await участник.remove_roles(r)
        if failed_role_id:
            r = guild.get_role(failed_role_id)
            if r:
                await участник.add_roles(r)

        try:
            await участник.edit(nick=member_data['game_name'])
        except discord.Forbidden:
            pass

        # Лог в личное дело (Форум)
        try:
            from utils.dossier_service import DossierService
            await DossierService.log_event(
                self.bot, guild, str(участник.id),
                title="❌ Отчисление из Академии АВНГ",
                description=f"Курсант отчислен из Академии АВНГ.",
                color=COLORS["error"],
                fields=[
                    ("Причина", причина or "Не сдал нормативы / решение инструктора", False),
                    ("Отчислил", interaction.user.mention, True),
                ],
                author=interaction.user,
            )
        except Exception:
            pass

        # DM
        try:
            e = discord.Embed(
                title="❌ Отчислен из Академии АВНГ",
                description=(
                    f"Вы отчислены из Академии АВНГ.\n"
                    + (f"**Причина:** {причина}" if причина else "")
                ),
                color=COLORS["error"],
            )
            await участник.send(embed=e)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ **{member_data['game_name']}** отчислен из академии.", ephemeral=True
        )

    async def _graduate_cadet(self, member: discord.Member, member_data: dict,
                               approved_by: discord.Member, guild: discord.Guild):
        """Внутренний метод: выпускает курсанта → Сержант (rank_id=4)"""
        from datetime import datetime
        old_rank = member_data.get("rank_id", 2)
        await self.bot.db.update_member(
            str(member.id), status="active", rank_id=4,
            joined_faction=datetime.utcnow().isoformat(),
            position_prefix="ВБП",
        )
        await self.bot.db.add_promotion(str(member.id), old_rank, 4, str(approved_by.id))

        # Меняем роли: снимаем курсантские и рядовой, выдаём сержанта
        config = self.bot.config
        roles_cfg = config["roles"]
        for key in ["cadet", "candidate", "failed_cadet", "private"]:
            rid = roles_cfg.get(key, 0)
            if rid:
                role = guild.get_role(rid)
                if role and role in member.roles:
                    try:
                        await member.remove_roles(role)
                    except Exception:
                        pass
        sergeant_role_id = roles_cfg.get("sergeant", 0)
        if sergeant_role_id:
            role = guild.get_role(sergeant_role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Выпуск из академии АВНГ — присвоение звания Сержант")
                except Exception:
                    pass

        # Никнейм: «ВБП | Алексей Иванов»
        nick = f"ВБП | {member_data['game_name']}"[:32]
        try:
            await member.edit(nick=nick)
        except discord.Forbidden:
            pass

        # Лог в личное дело (Форум)
        try:
            from utils.dossier_service import DossierService
            await DossierService.log_event(
                self.bot, guild, str(member.id),
                title="🎓 Успешное окончание Академии АВНГ",
                description="Курсант успешно завершил обучение в Академии АВНГ и зачислен в ряды Росгвардии в звании **Сержант**.",
                color=COLORS["success"],
                fields=[
                    ("Присвоенное звание", "Сержант", True),
                    ("Инструктор / Выпустил", approved_by.mention, True),
                ],
                author=approved_by,
            )
        except Exception:
            pass

        # DM
        try:
            e = discord.Embed(
                title="🎓 Вы окончили Академию АВНГ!",
                description=(
                    f"Поздравляем, **{member_data['game_name']}**!\n\n"
                    "Вы успешно прошли обучение и получаете звание **Сержант**.\n"
                    "Добро пожаловать в ряды Росгвардии! ⚔️"
                ),
                color=COLORS["success"],
            )
            e.add_field(name="Выпустил", value=approved_by.mention)
            await member.send(embed=e)
        except Exception:
            pass

        # Лог
        log_ch_id = config["channels"].get("bot_log", 0)
        log_ch = guild.get_channel(log_ch_id)
        if log_ch:
            e = discord.Embed(
                title="🎓 Выпуск из Академии АВНГ",
                description=f"**{member_data['game_name']}** {member.mention} → Сержант",
                color=COLORS["success"],
            )
            e.add_field(name="Выпустил", value=approved_by.mention)
            await log_ch.send(embed=e)

    # ─────────────── ТЕСТЫ ───────────────

    @test_group.command(name="создать", description="📝 Создать новый тест")
    @app_commands.describe(
        название="Название теста",
        описание="Описание теста",
        проходной_балл="Минимальный % для сдачи (по умолчанию 70)",
        обязательный="Назначить автоматически всем курсантам",
    )
    @instructor_only()
    async def test_create(self, interaction: discord.Interaction,
                           название: str, описание: str = "",
                           проходной_балл: int = 70,
                           обязательный: bool = False):
        await interaction.response.defer(ephemeral=True)
        test_id = await self.bot.db.create_test(
            название, описание, str(interaction.user.id),
            проходной_балл, обязательный,
        )
        await interaction.followup.send(
            f"✅ Тест **«{название}»** создан с ID `{test_id}`.\n"
            f"Добавьте вопросы командой `/тест вопрос {test_id} ...`",
            ephemeral=True,
        )

    @test_group.command(name="вопрос", description="➕ Добавить вопрос к тесту")
    @app_commands.describe(
        тест_id="ID теста", вопрос="Текст вопроса",
        вариант_а="Вариант А", вариант_б="Вариант Б",
        вариант_в="Вариант В", вариант_г="Вариант Г",
        правильный="Правильный ответ (а/б/в/г)",
    )
    @instructor_only()
    async def test_add_question(self, interaction: discord.Interaction,
                                 тест_id: int, вопрос: str,
                                 вариант_а: str, вариант_б: str,
                                 вариант_в: str, вариант_г: str,
                                 правильный: str):
        await interaction.response.defer(ephemeral=True)

        answer_map = {"а": "a", "б": "b", "в": "c", "г": "d",
                      "a": "a", "b": "b", "c": "c", "d": "d"}
        correct = answer_map.get(правильный.lower())
        if not correct:
            await interaction.followup.send(
                "❌ Неверный правильный ответ! Используйте: а, б, в или г", ephemeral=True
            )
            return

        test = await self.bot.db.get_test(тест_id)
        if not test:
            await interaction.followup.send(f"❌ Тест #{тест_id} не найден!", ephemeral=True)
            return

        await self.bot.db.add_question(
            тест_id, вопрос, вариант_а, вариант_б, вариант_в, вариант_г, correct
        )
        questions = await self.bot.db.get_test_questions(тест_id)
        await interaction.followup.send(
            f"✅ Вопрос добавлен к тесту **«{test['name']}»**. "
            f"Всего вопросов: **{len(questions)}**",
            ephemeral=True,
        )

    @test_group.command(name="список", description="📋 Список всех тестов")
    async def test_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        tests = await self.bot.db.get_all_tests()
        if not tests:
            await interaction.followup.send("📭 Нет доступных тестов.", ephemeral=True)
            return

        e = discord.Embed(title="📝 Список тестов Академии АВНГ", color=COLORS["rosguard"])
        for t in tests:
            questions = await self.bot.db.get_test_questions(t["id"])
            val = (
                f"📋 {t['description'] or '—'}\n"
                f"❓ Вопросов: **{len(questions)}** | "
                f"Порог: **{t['pass_score']}%** | "
                f"{'🔴 Обязательный' if t['required_all'] else '🔵 Назначаемый'}"
            )
            e.add_field(name=f"`#{t['id']}` {t['name']}", value=val, inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

    @test_group.command(name="назначить", description="📤 Назначить тест курсанту")
    @app_commands.describe(участник="Курсант", тест_id="ID теста")
    @instructor_only()
    async def test_assign(self, interaction: discord.Interaction,
                           участник: discord.Member, тест_id: int):
        await interaction.response.defer(ephemeral=True)
        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data or member_data["status"] != "cadet":
            await interaction.followup.send("❌ Пользователь не является курсантом!", ephemeral=True)
            return

        test = await self.bot.db.get_test(тест_id)
        if not test:
            await interaction.followup.send(f"❌ Тест #{тест_id} не найден!", ephemeral=True)
            return

        await self.bot.db.assign_test_to_cadet(str(участник.id), тест_id, str(interaction.user.id))

        # Уведомляем курсанта
        try:
            e = discord.Embed(
                title="📝 Вам назначен тест",
                description=(
                    f"**{test['name']}**\n"
                    f"{test['description'] or ''}\n\n"
                    f"Проходной балл: **{test['pass_score']}%** | "
                    f"Попытки: **{MAX_TEST_ATTEMPTS}**\n\n"
                    f"Используйте `/тест пройти {тест_id}` для прохождения."
                ),
                color=COLORS["info"],
            )
            e.add_field(name="Назначил", value=interaction.user.mention)
            await участник.send(embed=e)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ Тест **«{test['name']}»** назначен курсанту {участник.mention}.", ephemeral=True
        )

    @test_group.command(name="пройти", description="▶️ Пройти назначенный тест")
    @app_commands.describe(тест_id="ID теста для прохождения")
    async def test_take(self, interaction: discord.Interaction, тест_id: int):
        await interaction.response.defer(ephemeral=True)

        member_data = await self.bot.db.get_member(str(interaction.user.id))
        if not member_data or member_data["status"] != "cadet":
            await interaction.followup.send(
                "❌ Только курсанты могут проходить тесты!", ephemeral=True
            )
            return

        # Проверяем, что тест назначен
        cadet_tests = await self.bot.db.get_cadet_tests(str(interaction.user.id))
        assigned_ids = [t["test_id"] for t in cadet_tests]
        if тест_id not in assigned_ids:
            await interaction.followup.send(
                f"❌ Тест #{тест_id} вам не назначен!", ephemeral=True
            )
            return

        # Проверяем: уже сдан?
        if await self.bot.db.has_passed_test(str(interaction.user.id), тест_id):
            await interaction.followup.send(
                "✅ Вы уже успешно сдали этот тест!", ephemeral=True
            )
            return

        # Проверяем количество попыток
        attempts = await self.bot.db.count_test_attempts(str(interaction.user.id), тест_id)
        if attempts >= MAX_TEST_ATTEMPTS:
            await interaction.followup.send(
                f"🚫 Вы исчерпали все **{MAX_TEST_ATTEMPTS}** попытки для этого теста.\n"
                "Обратитесь к инструктору для сброса попыток.",
                ephemeral=True,
            )
            return

        # Проверяем: нет ли активной сессии
        if interaction.user.id in _test_sessions:
            await interaction.followup.send(
                "⚠️ У вас уже есть активная тест-сессия! Завершите её сначала.",
                ephemeral=True,
            )
            return

        test = await self.bot.db.get_test(тест_id)
        questions = await self.bot.db.get_test_questions(тест_id)

        if not questions:
            await interaction.followup.send(
                "❌ В этом тесте нет вопросов! Обратитесь к инструктору.", ephemeral=True
            )
            return

        _test_sessions[interaction.user.id] = {"test_id": тест_id}

        # Показываем первый вопрос
        embed = test_question_embed(test["name"], 1, len(questions), questions[0])
        view = TestQuestionView(
            self, interaction.user.id, тест_id, test["name"], questions
        )

        e_info = discord.Embed(
            title=f"📝 Начало теста: {test['name']}",
            description=(
                f"Вопросов: **{len(questions)}** | "
                f"Порог сдачи: **{test['pass_score']}%** | "
                f"Попытка: **{attempts + 1}/{MAX_TEST_ATTEMPTS}**\n\n"
                "Отвечайте на вопросы нажатием кнопок. Удачи! 🍀"
            ),
            color=COLORS["info"],
        )
        await interaction.followup.send(embed=e_info, ephemeral=True)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @test_group.command(name="сброс_попыток", description="🔄 Сбросить попытки теста курсанту")
    @app_commands.describe(участник="Курсант", тест_id="ID теста")
    @instructor_only()
    async def test_reset_attempts(self, interaction: discord.Interaction,
                                   участник: discord.Member, тест_id: int):
        await interaction.response.defer(ephemeral=True)
        import aiosqlite
        async with aiosqlite.connect("rosguard.db") as db:
            await db.execute(
                "DELETE FROM test_attempts WHERE member_id=? AND test_id=?",
                (str(участник.id), тест_id),
            )
            await db.commit()
        test = await self.bot.db.get_test(тест_id)
        await interaction.followup.send(
            f"✅ Попытки теста **«{test['name'] if test else тест_id}»** "
            f"для {участник.mention} сброшены.",
            ephemeral=True,
        )

    # ─────────────── ПРАКТИКА ───────────────

    @praktika_group.command(name="добавить", description="➕ Назначить практическое задание курсанту")
    @app_commands.describe(
        участник="Курсант",
        название="Название задания",
        описание="Подробное описание",
    )
    @instructor_only()
    async def praktika_add(self, interaction: discord.Interaction,
                            участник: discord.Member,
                            название: str, описание: str = ""):
        await interaction.response.defer(ephemeral=True)
        member_data = await self.bot.db.get_member(str(участник.id))
        if not member_data or member_data["status"] != "cadet":
            await interaction.followup.send("❌ Пользователь не является курсантом!", ephemeral=True)
            return

        task_id = await self.bot.db.add_practical_task(
            str(участник.id), название, описание, str(interaction.user.id)
        )

        # Уведомление курсанту
        try:
            e = discord.Embed(
                title="🛠️ Вам назначено практическое задание",
                description=f"**{название}**\n{описание}",
                color=COLORS["info"],
            )
            e.add_field(name="Назначил", value=interaction.user.mention)
            e.set_footer(text=f"ID задания: #{task_id}")
            await участник.send(embed=e)
        except Exception:
            pass

        await interaction.followup.send(
            f"✅ Задание **«{название}»** (ID: `{task_id}`) назначено {участник.mention}.",
            ephemeral=True,
        )

    @praktika_group.command(name="выполнил", description="✅ Отметить задание как выполненное")
    @app_commands.describe(задание_id="ID практического задания")
    @instructor_only()
    async def praktika_complete(self, interaction: discord.Interaction, задание_id: int):
        await interaction.response.defer(ephemeral=True)
        task = await self.bot.db.get_task(задание_id)
        if not task:
            await interaction.followup.send("❌ Задание не найдено!", ephemeral=True)
            return
        if task["completed"]:
            await interaction.followup.send("⚠️ Задание уже выполнено!", ephemeral=True)
            return

        await self.bot.db.complete_practical_task(задание_id, str(interaction.user.id))
        await interaction.followup.send(
            f"✅ Задание **«{task['title']}»** (#{задание_id}) отмечено как выполненное!",
            ephemeral=True,
        )

    # ─────────────── МОИ ЗАДАНИЯ ───────────────

    @app_commands.command(name="мои-задания", description="📋 Посмотреть свои задания в академии")
    async def my_tasks(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        member_data = await self.bot.db.get_member(str(interaction.user.id))
        if not member_data or member_data["status"] != "cadet":
            await interaction.followup.send(
                "❌ Эта команда доступна только курсантам!", ephemeral=True
            )
            return

        tasks = await self.bot.db.get_practical_tasks(str(interaction.user.id))
        cadet_tests = await self.bot.db.get_cadet_tests(str(interaction.user.id))

        # Получаем попытки для каждого теста
        test_attempts = {}
        for t in cadet_tests:
            attempts = await self.bot.db.get_test_attempts(str(interaction.user.id), t["test_id"])
            test_attempts[t["test_id"]] = attempts

        embed = task_list_embed(tasks, cadet_tests, test_attempts, member_data["game_name"])
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(AcademyCog(bot))
