"""
🤖 QN5K MODZ Telegram Bot — Single File Edition
Fully async · Firebase Realtime Database · aiogram 3.x
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

import firebase_admin
from firebase_admin import credentials, db


# ============================================================
# CONFIG
# ============================================================
load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]
FIREBASE_DATABASE_URL: str = os.getenv(
    "FIREBASE_DATABASE_URL",
    "https://qn5k-1655e-default-rtdb.firebaseio.com",
)
FIREBASE_CREDENTIALS_PATH: str = os.getenv(
    "FIREBASE_CREDENTIALS_PATH", "firebase-credentials.json"
)
WEBSITE_URL: str = os.getenv("WEBSITE_URL", "https://qn5kmodz.com")
TELEGRAM_CHANNEL: str = os.getenv("TELEGRAM_CHANNEL", "https://t.me/qn5kgaming")
SUPPORT_CONTACT: str = os.getenv("SUPPORT_CONTACT", "@BugSpyBots")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
ITEMS_PER_PAGE: int = 8

if not BOT_TOKEN:
    print("❌ BOT_TOKEN is required. Please set it in .env")
    sys.exit(1)


# ============================================================
# LOGGER
# ============================================================
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("qn5k")


# ============================================================
# HELPERS
# ============================================================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_date(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return "N/A"


def format_number(n) -> str:
    try:
        n = int(n) if n else 0
    except Exception:
        n = 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def escape_md(text: str) -> str:
    """Escape HTML special chars for safe display."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ============================================================
# FIREBASE
# ============================================================
_fb_initialized = False


def init_firebase():
    global _fb_initialized
    if _fb_initialized:
        return
    try:
        if os.path.exists(FIREBASE_CREDENTIALS_PATH):
            cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        else:
            cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DATABASE_URL})
        _fb_initialized = True
        logger.info("✅ Firebase initialized")
    except Exception as e:
        logger.error(f"❌ Firebase init error: {e}")
        raise


class FB:
    """Async wrapper around firebase-admin (blocking → to_thread)."""

    def __init__(self):
        init_firebase()

    async def get(self, path: str):
        def _get():
            try:
                return db.reference(path).get()
            except Exception as e:
                logger.error(f"FB GET [{path}]: {e}")
                return None
        return await asyncio.to_thread(_get)

    async def set(self, path: str, value):
        def _set():
            try:
                db.reference(path).set(value)
                return True
            except Exception as e:
                logger.error(f"FB SET [{path}]: {e}")
                return False
        return await asyncio.to_thread(_set)

    async def update(self, path: str, value: dict):
        def _upd():
            try:
                db.reference(path).update(value)
                return True
            except Exception as e:
                logger.error(f"FB UPDATE [{path}]: {e}")
                return False
        return await asyncio.to_thread(_upd)

    async def push(self, path: str, value):
        def _push():
            try:
                return db.reference(path).push(value).key
            except Exception as e:
                logger.error(f"FB PUSH [{path}]: {e}")
                return None
        return await asyncio.to_thread(_push)

    async def delete(self, path: str):
        def _del():
            try:
                db.reference(path).delete()
                return True
            except Exception as e:
                logger.error(f"FB DELETE [{path}]: {e}")
                return False
        return await asyncio.to_thread(_del)

    async def increment(self, path: str, amount: int = 1):
        def _inc():
            try:
                ref = db.reference(path)
                current = ref.get() or 0
                ref.set(current + amount)
                return current + amount
            except Exception as e:
                logger.error(f"FB INCREMENT [{path}]: {e}")
                return None
        return await asyncio.to_thread(_inc)


fb = FB()


# ============================================================
# SERVICES — PANELS
# ============================================================
async def panels_all():
    data = await fb.get("panels")
    if not data:
        return []
    return [{"id": k, **v} for k, v in data.items()]


async def panels_get(item_id: str):
    return await fb.get(f"panels/{item_id}")


async def panels_by_category(category: str):
    items = await panels_all()
    if category.lower() == "all":
        return items
    return [i for i in items if (i.get("category") or "").lower() == category.lower()]


async def panels_trending(limit: int = 10):
    items = await panels_all()
    items.sort(key=lambda x: int(x.get("downloads") or 0), reverse=True)
    return items[:limit]


async def panels_latest(limit: int = 10):
    items = await panels_all()
    items.sort(key=lambda x: x.get("updatedAt") or x.get("createdAt") or "", reverse=True)
    return items[:limit]


async def panels_inc_downloads(item_id: str):
    return await fb.increment(f"panels/{item_id}/downloads", 1)


async def panels_create(data: dict) -> str:
    data["createdAt"] = now_iso()
    data["updatedAt"] = now_iso()
    data.setdefault("downloads", 0)
    data.setdefault("status", "published")
    item_id = await fb.push("panels", data)
    logger.info(f"Item created: {item_id} - {data.get('name')}")
    return item_id


async def panels_update(item_id: str, data: dict) -> bool:
    data["updatedAt"] = now_iso()
    return await fb.update(f"panels/{item_id}", data)


async def panels_delete(item_id: str) -> bool:
    return await fb.delete(f"panels/{item_id}")


# ============================================================
# SERVICES — USERS
# ============================================================
async def user_get(user_id: int):
    return await fb.get(f"users/{user_id}")


async def user_register(user):
    existing = await user_get(user.id)
    if existing:
        await fb.update(f"users/{user.id}", {
            "lastSeen": now_iso(),
            "name": user.full_name,
            "username": user.username or "",
        })
        return existing

    data = {
        "id": user.id,
        "name": user.full_name,
        "username": user.username or "",
        "language": user.language_code or "en",
        "isPremium": False,
        "isBanned": False,
        "downloads": 0,
        "createdAt": now_iso(),
        "lastSeen": now_iso(),
    }
    await fb.set(f"users/{user.id}", data)
    logger.info(f"New user: {user.id} ({user.full_name})")
    return data


async def users_all():
    data = await fb.get("users")
    if not data:
        return []
    return list(data.values())


async def users_stats():
    users = await users_all()
    total = len(users)
    banned = sum(1 for u in users if u.get("isBanned"))
    return {"total": total, "banned": banned, "active": total - banned}


async def user_inc_downloads(user_id: int):
    return await fb.increment(f"users/{user_id}/downloads", 1)


async def user_set_ban(user_id: int, banned: bool):
    return await fb.update(f"users/{user_id}", {"isBanned": banned})


# ============================================================
# KEYBOARDS
# ============================================================
def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Download Files", callback_data="menu:download")],
        [
            InlineKeyboardButton(text="🔥 Trending", callback_data="menu:trending"),
            InlineKeyboardButton(text="🆕 New Updates", callback_data="menu:new"),
        ],
        [
            InlineKeyboardButton(text="👤 My Account", callback_data="menu:account"),
            InlineKeyboardButton(text="🔔 Notifications", callback_data="menu:notifs"),
        ],
        [
            InlineKeyboardButton(text="📢 Telegram Channel", url=TELEGRAM_CHANNEL),
            InlineKeyboardButton(text="🌐 Website", url=WEBSITE_URL),
        ],
        [InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{SUPPORT_CONTACT.lstrip('@')}")],
    ])


def kb_back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu:home")],
    ])


def kb_categories() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 All Files", callback_data="cat:all")],
        [
            InlineKeyboardButton(text="🆓 Free Files", callback_data="cat:free"),
            InlineKeyboardButton(text="💎 Premium Files", callback_data="cat:premium"),
        ],
        [
            InlineKeyboardButton(text="🛠️ Tools", callback_data="cat:tools"),
            InlineKeyboardButton(text="📚 Tutorials", callback_data="cat:tutorials"),
        ],
        [InlineKeyboardButton(text="🆕 Latest Updates", callback_data="cat:latest")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="menu:home")],
    ])


def kb_item(item_id: str, download_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬇️ DOWNLOAD", url=download_url)],
        [
            InlineKeyboardButton(text="⭐ Rate", callback_data=f"rate:{item_id}"),
            InlineKeyboardButton(text="🚨 Report", callback_data=f"report:{item_id}"),
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data="menu:download")],
    ])


def kb_items_list(items: list, page: int = 0) -> InlineKeyboardMarkup:
    per_page = ITEMS_PER_PAGE
    start = page * per_page
    end = start + per_page
    page_items = items[start:end]

    rows = []
    for item in page_items:
        name = item.get("name", "Unknown")
        version = item.get("version", "")
        label = f"📦 {name} {version}".strip()
        if len(label) > 55:
            label = label[:52] + "..."
        rows.append([InlineKeyboardButton(text=label, callback_data=f"item:{item['id']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"page:{page-1}"))
    if end < len(items):
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"page:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_rating(item_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1⭐", callback_data=f"stars:{item_id}:1"),
            InlineKeyboardButton(text="2⭐", callback_data=f"stars:{item_id}:2"),
            InlineKeyboardButton(text="3⭐", callback_data=f"stars:{item_id}:3"),
        ],
        [
            InlineKeyboardButton(text="4⭐", callback_data=f"stars:{item_id}:4"),
            InlineKeyboardButton(text="5⭐", callback_data=f"stars:{item_id}:5"),
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data=f"item:{item_id}")],
    ])


def kb_report(item_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Broken Link", callback_data=f"rep:{item_id}:broken")],
        [InlineKeyboardButton(text="❌ Wrong Info", callback_data=f"rep:{item_id}:wrong")],
        [InlineKeyboardButton(text="🚫 Inappropriate", callback_data=f"rep:{item_id}:bad")],
        [InlineKeyboardButton(text="📝 Other", callback_data=f"rep:{item_id}:other")],
        [InlineKeyboardButton(text="🔙 Cancel", callback_data=f"item:{item_id}")],
    ])


def kb_account() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Download History", callback_data="acc:history")],
        [InlineKeyboardButton(text="❤️ Favorites", callback_data="acc:favorites")],
        [InlineKeyboardButton(text="🔔 Notifications", callback_data="menu:notifs")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="menu:home")],
    ])


# ---- Admin keyboards ----
def kb_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Add Item", callback_data="adm:add"),
            InlineKeyboardButton(text="📊 Stats", callback_data="adm:stats"),
        ],
        [
            InlineKeyboardButton(text="👥 Users", callback_data="adm:users"),
            InlineKeyboardButton(text="🚨 Reports", callback_data="adm:reports"),
        ],
        [
            InlineKeyboardButton(text="📢 Broadcast", callback_data="adm:broadcast"),
            InlineKeyboardButton(text="🔔 Notify", callback_data="adm:notify"),
        ],
        [InlineKeyboardButton(text="📋 Logs", callback_data="adm:logs")],
    ])


def kb_admin_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="adm:back")],
    ])


def kb_confirm_delete(item_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ DELETE", callback_data=f"del:yes:{item_id}"),
            InlineKeyboardButton(text="❌ CANCEL", callback_data=f"del:no:{item_id}"),
        ],
    ])


def kb_categories_select(prefix: str = "addcat") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🆓 Free", callback_data=f"{prefix}:free"),
            InlineKeyboardButton(text="💎 Premium", callback_data=f"{prefix}:premium"),
        ],
        [
            InlineKeyboardButton(text="🛠️ Tools", callback_data=f"{prefix}:tools"),
            InlineKeyboardButton(text="📚 Tutorials", callback_data=f"{prefix}:tutorials"),
        ],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")],
    ])


def kb_status_select() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Published", callback_data="addstatus:published"),
            InlineKeyboardButton(text="📝 Draft", callback_data="addstatus:draft"),
        ],
    ])


# ============================================================
# ROUTERS
# ============================================================
router = Router()

WELCOME = (
    "🤖 <b>QN5K MODZ</b>\n\n"
    "Welcome to QN5K MODZ!\n"
    "Your hub for downloads, tools & updates.\n\n"
    "Select an option below 👇"
)


# ---------- START ----------
@router.message(CommandStart())
async def cmd_start(message: Message):
    await user_register(message.from_user)
    logger.info(f"/start by {message.from_user.id}")
    await message.answer(WELCOME, reply_markup=kb_main_menu(), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🆘 <b>Help</b>\n\nUse the menu to browse files.\nContact support for any issue.",
        reply_markup=kb_main_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:home")
async def back_home(callback: CallbackQuery):
    await callback.message.edit_text(WELCOME, reply_markup=kb_main_menu(), parse_mode="HTML")
    await callback.answer()


# ---------- DOWNLOAD ----------
@router.callback_query(F.data == "menu:download")
async def show_categories(callback: CallbackQuery):
    await callback.message.edit_text(
        "📦 <b>Download Files</b>\n\nChoose a category 👇",
        reply_markup=kb_categories(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def show_category(callback: CallbackQuery):
    category = callback.data.split(":", 1)[1]
    await callback.answer("⏳ Loading...")

    if category == "latest":
        items = await panels_latest(50)
        title = "🆕 <b>Latest Updates</b>"
    else:
        items = await panels_by_category(category)
        title = f"📂 <b>{category.title()}</b>"

    if not items:
        await callback.message.edit_text(
            f"{title}\n\n❌ No files in this category yet.",
            reply_markup=kb_back_home(),
            parse_mode="HTML",
        )
        return

    await callback.message.edit_text(
        f"{title}\n\n📄 Total: <b>{len(items)}</b> files",
        reply_markup=kb_items_list(items, 0),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("page:"))
async def paginate(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    items = await panels_all()
    await callback.message.edit_reply_markup(reply_markup=kb_items_list(items, page))
    await callback.answer()


@router.callback_query(F.data.startswith("item:"))
async def show_item(callback: CallbackQuery):
    item_id = callback.data.split(":", 1)[1]
    item = await panels_get(item_id)
    if not item:
        await callback.answer("❌ Item not found", show_alert=True)
        return

    name = item.get("name", "Unknown")
    version = item.get("version", "N/A")
    desc = item.get("description", "No description")
    updated = format_date(item.get("updatedAt") or item.get("createdAt"))
    category = (item.get("category") or "general").title()
    downloads = format_number(item.get("downloads"))
    image = item.get("image")
    download_url = item.get("downloadUrl", "#")

    caption = (
        f"📦 <b>{escape_md(name)}</b>\n"
        f"🆕 Version: <b>{escape_md(version)}</b>\n"
        f"📂 Category: <b>{escape_md(category)}</b>\n"
        f"📅 Updated: <b>{updated}</b>\n"
        f"⬇️ Downloads: <b>{downloads}</b>\n\n"
        f"📝 <b>Description</b>\n{escape_md(desc)}"
    )

    if image:
        try:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=image,
                caption=caption,
                reply_markup=kb_item(item_id, download_url),
                parse_mode="HTML",
            )
            await callback.answer()
            return
        except Exception:
            pass

    await callback.message.edit_text(
        caption, reply_markup=kb_item(item_id, download_url), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "menu:trending")
async def show_trending(callback: CallbackQuery):
    await callback.answer("⏳ Loading...")
    items = await panels_trending(10)
    if not items:
        await callback.message.edit_text(
            "🔥 <b>Trending</b>\n\nNo data yet.",
            reply_markup=kb_back_home(),
            parse_mode="HTML",
        )
        return

    lines = ["🔥 <b>TRENDING NOW</b>\n"]
    for i, item in enumerate(items, 1):
        name = item.get("name", "Unknown")
        dl = format_number(item.get("downloads"))
        lines.append(f"{i}. 📦 <b>{escape_md(name)}</b> — {dl} downloads")

    await callback.message.edit_text(
        "\n".join(lines), reply_markup=kb_items_list(items, 0), parse_mode="HTML"
    )


@router.callback_query(F.data == "menu:new")
async def show_new(callback: CallbackQuery):
    await callback.answer("⏳ Loading...")
    items = await panels_latest(10)
    if not items:
        await callback.message.edit_text(
            "🆕 <b>New Updates</b>\n\nNothing new yet.",
            reply_markup=kb_back_home(),
            parse_mode="HTML",
        )
        return

    lines = ["🆕 <b>NEW UPDATES</b>\n"]
    for item in items:
        name = item.get("name", "Unknown")
        ver = item.get("version", "")
        upd = format_date(item.get("updatedAt"))
        lines.append(f"📦 <b>{escape_md(name)}</b> {escape_md(ver)}\n   📅 {upd}")

    await callback.message.edit_text(
        "\n".join(lines), reply_markup=kb_items_list(items, 0), parse_mode="HTML"
    )


# ---------- RATE ----------
@router.callback_query(F.data.startswith("rate:"))
async def rate_item(callback: CallbackQuery):
    item_id = callback.data.split(":", 1)[1]
    await callback.message.edit_text(
        "⭐ <b>Rate this item</b>\n\nHow many stars?",
        reply_markup=kb_rating(item_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stars:"))
async def submit_rating(callback: CallbackQuery):
    _, item_id, stars = callback.data.split(":")
    data = {
        "userId": callback.from_user.id,
        "userName": callback.from_user.full_name,
        "itemId": item_id,
        "rating": int(stars),
        "createdAt": now_iso(),
    }
    await fb.set(f"reviews/{item_id}/{callback.from_user.id}", data)
    logger.info(f"Rating: user={callback.from_user.id} item={item_id} stars={stars}")
    await callback.answer("✅ Thanks for rating!", show_alert=True)

    item = await panels_get(item_id)
    if item:
        await callback.message.edit_text(
            "✅ <b>Thank you!</b>\n\nUse the button below to open the item.",
            reply_markup=kb_item(item_id, item.get("downloadUrl", "#")),
            parse_mode="HTML",
        )


# ---------- REPORT ----------
@router.callback_query(F.data.startswith("report:"))
async def report_item(callback: CallbackQuery):
    item_id = callback.data.split(":", 1)[1]
    await callback.message.edit_text(
        "🚨 <b>Report this item</b>\n\nWhat's wrong?",
        reply_markup=kb_report(item_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rep:"))
async def submit_report(callback: CallbackQuery):
    _, item_id, rtype = callback.data.split(":")
    data = {
        "userId": callback.from_user.id,
        "userName": callback.from_user.full_name,
        "itemId": item_id,
        "type": rtype,
        "status": "pending",
        "createdAt": now_iso(),
    }
    await fb.push("reports", data)
    logger.info(f"Report: user={callback.from_user.id} item={item_id} type={rtype}")
    await callback.answer("🚨 Report submitted!", show_alert=True)
    await callback.message.edit_text(
        "✅ <b>Report submitted</b>\n\nThank you! Our team will review it soon.",
        reply_markup=kb_back_home(),
        parse_mode="HTML",
    )


# ---------- ACCOUNT ----------
@router.callback_query(F.data == "menu:account")
async def show_account(callback: CallbackQuery):
    user = callback.from_user
    data = await user_get(user.id) or {}

    joined = format_date(data.get("createdAt"))
    downloads = format_number(data.get("downloads", 0))
    is_premium = "💎 Yes" if data.get("isPremium") else "🆓 No"

    text = (
        "👤 <b>MY ACCOUNT</b>\n\n"
        f"👤 Name: <b>{escape_md(user.full_name)}</b>\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📅 Joined: <b>{joined}</b>\n"
        f"⬇️ Downloads: <b>{downloads}</b>\n"
        f"💎 Premium: <b>{is_premium}</b>"
    )
    await callback.message.edit_text(text, reply_markup=kb_account(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "acc:history")
async def acc_history(callback: CallbackQuery):
    await callback.answer("📜 History coming soon!", show_alert=True)


@router.callback_query(F.data == "acc:favorites")
async def acc_favorites(callback: CallbackQuery):
    await callback.answer("❤️ Favorites coming soon!", show_alert=True)


# ---------- NOTIFICATIONS ----------
@router.callback_query(F.data == "menu:notifs")
async def show_notifs(callback: CallbackQuery):
    data = await fb.get("notifications")
    if not data:
        await callback.message.edit_text(
            "🔔 <b>Notifications</b>\n\nNo notifications yet.",
            reply_markup=kb_back_home(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    items = [{"id": k, **v} for k, v in data.items()]
    items.sort(key=lambda x: x.get("createdAt") or "", reverse=True)

    lines = ["🔔 <b>NOTIFICATIONS</b>\n"]
    for n in items[:10]:
        title = escape_md(n.get("title", "Update"))
        msg = escape_md((n.get("message") or "")[:120])
        d = format_date(n.get("createdAt"))
        lines.append(f"<b>{title}</b>\n{msg}\n<i>{d}</i>\n")

    await callback.message.edit_text(
        "\n".join(lines), reply_markup=kb_back_home(), parse_mode="HTML"
    )
    await callback.answer()


# ============================================================
# ADMIN PANEL
# ============================================================
class AddItem(StatesGroup):
    name = State()
    version = State()
    description = State()
    category = State()
    image = State()
    download_url = State()
    status = State()


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Access denied.")
        return
    await message.answer(
        "👑 <b>ADMIN PANEL</b>\n\nChoose an action:",
        reply_markup=kb_admin_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "adm:back")
async def adm_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await callback.message.edit_text(
        "👑 <b>ADMIN PANEL</b>\n\nChoose an action:",
        reply_markup=kb_admin_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "adm:cancel")
async def adm_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Cancelled.",
        reply_markup=kb_admin_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------- STATS ----------
@router.callback_query(F.data == "adm:stats")
async def adm_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return

    items = await panels_all()
    u = await users_stats()
    total_dl = sum(int(i.get("downloads") or 0) for i in items)

    text = (
        "📊 <b>QN5K MODZ STATS</b>\n\n"
        f"👥 Total Users: <b>{format_number(u['total'])}</b>\n"
        f"🟢 Active Users: <b>{format_number(u['active'])}</b>\n"
        f"🚫 Banned: <b>{format_number(u['banned'])}</b>\n"
        f"📦 Total Files: <b>{format_number(len(items))}</b>\n"
        f"⬇️ Total Downloads: <b>{format_number(total_dl)}</b>"
    )
    await callback.message.edit_text(text, reply_markup=kb_admin_back(), parse_mode="HTML")
    await callback.answer()


# ---------- ADD (FSM) ----------
@router.callback_query(F.data == "adm:add")
async def adm_add_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await state.set_state(AddItem.name)
    await callback.message.edit_text(
        "➕ <b>Add New Item</b>\n\nStep 1/7: Send the <b>name</b>:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AddItem.name)
async def add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddItem.version)
    await message.answer("Step 2/7: Send the <b>version</b> (e.g. v4.0):", parse_mode="HTML")


@router.message(AddItem.version)
async def add_version(message: Message, state: FSMContext):
    await state.update_data(version=message.text.strip())
    await state.set_state(AddItem.description)
    await message.answer("Step 3/7: Send the <b>description</b>:")


@router.message(AddItem.description)
async def add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddItem.category)
    await message.answer(
        "Step 4/7: Choose the <b>category</b>:",
        reply_markup=kb_categories_select(),
    )


@router.callback_query(F.data.startswith("addcat:"), AddItem.category)
async def add_category(callback: CallbackQuery, state: FSMContext):
    cat = callback.data.split(":")[1]
    await state.update_data(category=cat)
    await state.set_state(AddItem.image)
    await callback.message.edit_text(
        "Step 5/7: Send the <b>image URL</b> (or type <code>skip</code>):",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AddItem.image)
async def add_image(message: Message, state: FSMContext):
    url = message.text.strip()
    await state.update_data(image="" if url.lower() == "skip" else url)
    await state.set_state(AddItem.download_url)
    await message.answer("Step 6/7: Send the <b>download URL</b>:")


@router.message(AddItem.download_url)
async def add_url(message: Message, state: FSMContext):
    await state.update_data(downloadUrl=message.text.strip())
    await state.set_state(AddItem.status)
    await message.answer(
        "Step 7/7: Choose the <b>status</b>:",
        reply_markup=kb_status_select(),
    )


@router.callback_query(F.data.startswith("addstatus:"), AddItem.status)
async def add_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split(":")[1]
    await state.update_data(status=status)
    data = await state.get_data()

    summary = (
        "📋 <b>Confirm New Item</b>\n\n"
        f"📦 Name: <b>{escape_md(data.get('name'))}</b>\n"
        f"🆕 Version: <b>{escape_md(data.get('version'))}</b>\n"
        f"📂 Category: <b>{escape_md(data.get('category'))}</b>\n"
        f"📝 Desc: {escape_md((data.get('description') or '')[:100])}\n"
        f"🔗 URL: {escape_md(data.get('downloadUrl'))}\n"
        f"🎯 Status: <b>{escape_md(status)}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ CONFIRM", callback_data="addconfirm:yes")],
        [InlineKeyboardButton(text="❌ CANCEL", callback_data="addconfirm:no")],
    ])
    await callback.message.edit_text(summary, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("addconfirm:"))
async def add_confirm(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":")[1]
    if choice == "no":
        await state.clear()
        await callback.message.edit_text("❌ Cancelled.", reply_markup=kb_admin_menu())
        await callback.answer()
        return

    data = await state.get_data()
    item_id = await panels_create(data)
    await state.clear()

    logger.info(f"Admin {callback.from_user.id} created item {item_id}")
    await callback.message.edit_text(
        f"✅ Item created!\nID: <code>{item_id}</code>",
        reply_markup=kb_admin_menu(),
        parse_mode="HTML",
    )
    await callback.answer("✅ Created")


# ---------- DELETE ----------
@router.message(Command("delete"))
async def cmd_delete(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: <code>/delete ITEM_ID</code>", parse_mode="HTML")
        return
    item_id = args[1].strip()
    item = await panels_get(item_id)
    if not item:
        await message.answer("❌ Item not found.")
        return
    await message.answer(
        f"⚠️ Delete <b>{escape_md(item.get('name'))}</b>?\n\nAre you sure?",
        reply_markup=kb_confirm_delete(item_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("del:"))
async def delete_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    _, choice, item_id = callback.data.split(":")
    if choice == "no":
        await callback.message.edit_text("❌ Cancelled.", reply_markup=kb_admin_menu())
        await callback.answer()
        return

    await panels_delete(item_id)
    logger.info(f"Admin {callback.from_user.id} deleted item {item_id}")
    await callback.message.edit_text("✅ Deleted.", reply_markup=kb_admin_menu())
    await callback.answer("✅ Deleted")


# ---------- BROADCAST ----------
@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: <code>/broadcast Your message</code>", parse_mode="HTML")
        return
    text = args[1].strip()

    users_list = await users_all()
    sent = failed = 0
    for u in users_list:
        try:
            await message.bot.send_message(
                u["id"],
                f"📢 <b>QN5K MODZ ANNOUNCEMENT</b>\n\n{escape_md(text)}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await message.answer(
        f"📢 <b>Broadcast complete</b>\n\n✅ Sent: {sent}\n❌ Failed: {failed}\n👥 Total: {len(users_list)}",
        parse_mode="HTML",
    )


# ---------- USERS ----------
@router.callback_query(F.data == "adm:users")
async def adm_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    u = await users_stats()
    await callback.message.edit_text(
        f"👥 <b>Users</b>\n\nTotal: <b>{u['total']}</b>\nActive: <b>{u['active']}</b>\nBanned: <b>{u['banned']}</b>\n\n"
        f"Use <code>/user USER_ID</code>, <code>/ban USER_ID</code>, <code>/unban USER_ID</code>.",
        reply_markup=kb_admin_back(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(Command("user"))
async def cmd_user(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Usage: <code>/user USER_ID</code>", parse_mode="HTML")
        return
    uid = int(args[1])
    data = await user_get(uid)
    if not data:
        await message.answer("❌ User not found.")
        return
    text = (
        f"👤 <b>User Info</b>\n\n"
        f"ID: <code>{uid}</code>\n"
        f"Name: <b>{escape_md(data.get('name'))}</b>\n"
        f"Username: @{escape_md(data.get('username') or 'N/A')}\n"
        f"Downloads: <b>{format_number(data.get('downloads'))}</b>\n"
        f"Joined: <b>{format_date(data.get('createdAt'))}</b>\n"
        f"Banned: <b>{'Yes' if data.get('isBanned') else 'No'}</b>"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("ban"))
async def cmd_ban(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Usage: /ban USER_ID")
        return
    await user_set_ban(int(args[1]), True)
    await message.answer(f"🚫 Banned {args[1]}")


@router.message(Command("unban"))
async def cmd_unban(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Usage: /unban USER_ID")
        return
    await user_set_ban(int(args[1]), False)
    await message.answer(f"✅ Unbanned {args[1]}")


# ---------- NOTIFY ----------
@router.message(Command("notify"))
async def cmd_notify(message: Message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /notify Your notification text")
        return
    text = args[1].strip()

    await fb.push("notifications", {
        "title": "QN5K MODZ Notification",
        "message": text,
        "type": "announcement",
        "createdAt": now_iso(),
    })

    users_list = await users_all()
    sent = failed = 0
    for u in users_list:
        try:
            await message.bot.send_message(
                u["id"],
                f"🔔 <b>Notification</b>\n\n{escape_md(text)}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await message.answer(f"✅ Notify done\nSent: {sent} | Failed: {failed}")


# ---------- REPORTS ----------
@router.callback_query(F.data == "adm:reports")
async def adm_reports(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    data = await fb.get("reports")
    if not data:
        await callback.message.edit_text(
            "🚨 <b>Reports</b>\n\nNo reports.",
            reply_markup=kb_admin_back(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    items = [{"id": k, **v} for k, v in data.items()]
    pending = [i for i in items if i.get("status") == "pending"][:10]
    lines = ["🚨 <b>Pending Reports</b>\n"]
    for i in pending:
        lines.append(
            f"• Item: <code>{i.get('itemId')}</code>\n  Type: {i.get('type')}\n  By: {escape_md(i.get('userName') or '')}"
        )
    if not pending:
        lines.append("✅ No pending reports.")
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=kb_admin_back(), parse_mode="HTML"
    )
    await callback.answer()


# ---------- LOGS ----------
@router.callback_query(F.data == "adm:logs")
async def adm_logs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔", show_alert=True)
        return
    await callback.message.edit_text(
        "📋 <b>Activity Logs</b>\n\nCheck the server console for full logs.",
        reply_markup=kb_admin_back(),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
# BOT LIFECYCLE
# ============================================================
async def main():
    logger.info("🚀 Starting QN5K MODZ Bot...")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("✅ Bot online")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Bot stopped")