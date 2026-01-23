import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types.input_file import BufferedInputFile
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .db import DB
from .template import render_template_html, settings_from_json
from .qr import make_qr_png
from .settings import Settings
from .validation import is_valid_node_id


log = logging.getLogger("tgbot")


def _start_text(s: Settings) -> str:
    parts: list[str] = []
    parts.append("Сеть ZeroTier для подключения.")
    if s.zt_network_id:
        parts.append(f"Network ID: {s.zt_network_id}")
    parts.append("")
    parts.append("Ссылка для присоединения:")
    parts.append(s.web_page_url_1)
    parts.append("")
    parts.append("Альтернативный способ:")
    parts.append(s.web_page_url_2)
    parts.append("")
    parts.append("Используйте только если ссылка получена от доверенного источника.")
    parts.append("")
    parts.append("Чтобы отправить заявку на одобрение узла:")
    parts.append("/approve <node_id>")
    return "\n".join(parts)


def _howto_kb(url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text="Как подключиться?", url=url))
    return kb.as_markup()


def _admin_action_kb(request_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text="Подтвердить", callback_data=f"approve:{request_id}"))
    kb.add(InlineKeyboardButton(text="Отклонить", callback_data=f"deny:{request_id}"))
    kb.adjust(2)
    return kb.as_markup()


async def create_dispatcher(s: Settings, db: DB) -> tuple[Bot, Dispatcher]:
    bot = Bot(token=s.tg_token)
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def start(m: Message) -> None:
        if m.from_user:
            await db.upsert_user_profile(
                tg_id=m.from_user.id,
                username=m.from_user.username,
                first_name=m.from_user.first_name,
                last_name=m.from_user.last_name,
            )
        await m.answer(_start_text(s), reply_markup=_howto_kb(s.instruction_article_url), disable_web_page_preview=True)
        try:
            png = make_qr_png(s.web_page_url_1)
            f = BufferedInputFile(png, filename="join-network.png")
            await bot.send_photo(
                chat_id=m.chat.id,
                photo=f,
                caption="QR-код для присоединения",
            )
        except Exception:
            log.exception("Failed to send QR")

    @dp.message(Command("approve"))
    async def approve(m: Message) -> None:
        if m.from_user:
            await db.upsert_user_profile(
                tg_id=m.from_user.id,
                username=m.from_user.username,
                first_name=m.from_user.first_name,
                last_name=m.from_user.last_name,
            )
        parts = (m.text or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            await m.answer("Формат: /approve <node_id>")
            return
        node_id_raw = parts[1].strip()
        if not is_valid_node_id(node_id_raw):
            await m.answer("node_id должен быть 10-значным hex (пример: a1b2c3d4e5)")
            return
        node_id = node_id_raw.lower()
        req_id = await db.create_request(m.from_user.id, node_id)
        log.info("request_created tg_id=%s node_id=%s request_id=%s", m.from_user.id, node_id, req_id)
        await m.answer(f"Заявка принята. ID: {req_id}. Ожидайте решения администратора.")
        admin_msg = "\n".join(
            [
                "Новая заявка на одобрение",
                f"request_id: {req_id}",
                f"tg_id: {m.from_user.id}",
                f"username: @{m.from_user.username}" if m.from_user.username else "username: (none)",
                f"node_id: {node_id}",
            ]
        )
        await bot.send_message(
            chat_id=s.admin_chat_id,
            text=admin_msg,
            reply_markup=_admin_action_kb(req_id),
            disable_web_page_preview=True,
        )

    @dp.message()
    async def maybe_node_id(m: Message) -> None:
        if not m.from_user:
            return
        text = (m.text or "").strip()
        if not text or text.startswith("/"):
            return
        token = text.split(maxsplit=1)[0].strip()
        if not is_valid_node_id(token):
            return
        await db.upsert_user_profile(
            tg_id=m.from_user.id,
            username=m.from_user.username,
            first_name=m.from_user.first_name,
            last_name=m.from_user.last_name,
        )
        node_id = token.lower()
        req_id = await db.create_request(m.from_user.id, node_id)
        log.info("request_created tg_id=%s node_id=%s request_id=%s via=text", m.from_user.id, node_id, req_id)
        await m.answer(f"Заявка принята. ID: {req_id}. Ожидайте решения администратора.")
        admin_msg = "\n".join(
            [
                "Новая заявка на одобрение",
                f"request_id: {req_id}",
                f"tg_id: {m.from_user.id}",
                f"username: @{m.from_user.username}" if m.from_user.username else "username: (none)",
                f"node_id: {node_id}",
            ]
        )
        await bot.send_message(
            chat_id=s.admin_chat_id,
            text=admin_msg,
            reply_markup=_admin_action_kb(req_id),
            disable_web_page_preview=True,
        )

    async def _handle_decision(q: CallbackQuery, status: str) -> None:
        if q.from_user.id != s.admin_chat_id:
            await q.answer("Недостаточно прав", show_alert=True)
            return
        data = (q.data or "")
        try:
            req_id = int(data.split(":", 1)[1])
        except Exception:
            await q.answer("Некорректные данные", show_alert=True)
            return
        req = await db.get_request(req_id)
        if not req:
            await q.answer("Заявка не найдена", show_alert=True)
            return
        ok = await db.decide_request(req_id, status=status, decided_by=q.from_user.id)
        if not ok:
            await q.answer("Заявка уже обработана", show_alert=True)
            return

        log.info("request_%s request_id=%s decided_by=%s tg_id=%s node_id=%s", status, req_id, q.from_user.id, req.tg_id, req.node_id)
        await q.message.edit_reply_markup(reply_markup=None)
        await q.message.answer(f"Заявка {req_id}: {status}")

        if status == "approved":
            raw = await db.get_setting("approval_message")
            st = settings_from_json(raw or "")
            u = await db.get_user(req.tg_id)
            client_name = ""
            username = ""
            if u:
                parts = [p for p in [u.first_name, u.last_name] if p]
                client_name = " ".join(parts)
                username = u.username or ""
            variables = {
                "client_name": client_name,
                "request_id": req_id,
                "node_id": req.node_id,
                "tg_id": req.tg_id,
                "username": username,
                "bot_username": s.bot_username,
                "network_id": s.zt_network_id,
            }
            msg_html = render_template_html(st.template_html, variables=variables, fallbacks=st.fallbacks)
            await bot.send_message(chat_id=req.tg_id, text=msg_html, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=req.tg_id, text=f"Ваша заявка {req_id} отклонена. node_id: {req.node_id}")
        await q.answer("Готово")

    @dp.callback_query(F.data.startswith("approve:"))
    async def approve_cb(q: CallbackQuery) -> None:
        await _handle_decision(q, "approved")

    @dp.callback_query(F.data.startswith("deny:"))
    async def deny_cb(q: CallbackQuery) -> None:
        await _handle_decision(q, "denied")

    return bot, dp

