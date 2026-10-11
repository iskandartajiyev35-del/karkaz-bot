"""
KARKAZ B2B Bot  (v3)
Qurilish materiallari e'lonlarini qabul qiluvchi Telegram bot.
 
Oqim:
/start -> [E'lon joylash] -> til -> kim sifatida (yuridik/jismoniy) -> telefon
-> tashkilot -> batafsil ma'lumot -> narx -> standart/sertifikat
-> rasm (min. 3) yoki video -> miqdor -> yetkazib berish -> hudud (14 ta tugma)
-> tekshirish (tasdiqlash / bo'limni tanlab o'zgartirish) -> adminga yuborish (+ Google Sheets)
 
Har bir savolga to'g'ri javob kelmaguncha keyingi savolga o'tilmaydi.
"""
 
import asyncio
import html
import json
import logging
import os
import re
from datetime import datetime
 
import gspread
from google.oauth2.service_account import Credentials
 
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
 
# ---------------------------------------------------------------------------
# SOZLAMALAR (Railway -> Variables bo'limida kiritiladi)
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")  # ixtiyoriy
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")  # ixtiyoriy
 
# Cheklovlar - kerak bo'lsa shu yerda o'zgartiring
MIN_DESC_WORDS = 15      # batafsil ma'lumotdagi minimal so'z soni
MAX_DESC_WORDS = 150     # maksimal so'z soni
MAX_DESC_CHARS = 2000    # maksimal belgi soni (himoya uchun)
MAX_SHORT_CHARS = 200    # qisqa javoblar (nom, narx, hudud...) uchun maksimal belgi
MIN_PHOTOS = 3           # video bo'lmasa, kamida nechta rasm kerak
MAX_PHOTOS = 10          # maksimal rasm soni
CAPTION_LIMIT = 1024     # Telegram: rasm tagidagi matn chegarasi
 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
 
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi! Railway'ning Variables bo'limiga qo'shing.")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID topilmadi! Railway'ning Variables bo'limiga qo'shing.")
ADMIN_ID = int(ADMIN_ID)
 
_sheet = None
if GOOGLE_CREDENTIALS and SPREADSHEET_ID:
    try:
        _creds = Credentials.from_service_account_info(
            json.loads(GOOGLE_CREDENTIALS),
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        _sheet = gspread.authorize(_creds).open_by_key(SPREADSHEET_ID).sheet1
        logger.info("Google Sheets muvaffaqiyatli ulandi.")
    except Exception as e:
        logger.error("Google Sheetsga ulanishda xatolik: %s", e)
else:
    logger.info("GOOGLE_CREDENTIALS yoki SPREADSHEET_ID kiritilmagan - Sheets o'chirilgan.")
 
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)
 
 
# ---------------------------------------------------------------------------
# HOLATLAR
# ---------------------------------------------------------------------------
class Form(StatesGroup):
    language = State()
    activity = State()
    phone = State()
    org_name = State()
    description = State()
    price = State()
    certificate = State()
    media = State()
    quantity = State()
    delivery = State()
    region = State()
    confirm = State()
    edit_choice = State()
 
 
# ---------------------------------------------------------------------------
# MATNLAR (UZ / RU)
# ---------------------------------------------------------------------------
WELCOME = (
    "🏗 <b>KARKAZ — B2B savdo platformasi</b>\n"
    "Qurilish va biznes uchun mahsulotlar bir joyda!\n\n"
    "🏗 <b>KARKAZ — B2B платформа для торговли</b>\n"
    "Товары для строительства и бизнеса в одном месте!"
)
 
ASK_LANGUAGE = (
    "🌐 <b>E'loningiz qaysi tilda bo'lishini xohlaysiz?</b>\n\n"
    "🌐 <b>На каком языке вы хотите разместить объявление?</b>"
)
 
TEXTS = {
    "uz": {
        "ask_activity": "🏢 <b>Siz kim sifatida faoliyat yuritasiz?</b>",
        "ask_phone": (
            "📞 <b>Telefon raqamingizni kiriting</b>\n"
            "Masalan: +998 90 123 45 67"
        ),
        "ask_org": (
            "🏢 <b>Tashkilotingiz nomini kiriting</b>\n"
            "Masalan: Tadjiyev Grup Management"
        ),
        "ask_description": (
            "📝 <b>Mahsulot haqida batafsil ma'lumot kiriting</b>\n"
            "📦 Mahsulotning nima uchun ishlatilishi, o'lchami, tarkibi, brendi va "
            "texnik xususiyatlari haqida kamida {min} ta, ko'pi bilan {max} ta so'z "
            "bilan ma'lumot bering.\n"
            "ℹ️ Ma'lumot aniq va tushunarli bo'lishi kerak. Bu xaridorlarga "
            "mahsulotni yaxshiroq tushunish va to'g'ri tanlashga yordam beradi."
        ),
        "ask_price": (
            "🧱 <b>Narxini kiriting</b>\n"
            "Narx va o'lchov birligini yozing.\n"
            "Masalan: 1 tonna sement — 850 000 so'm"
        ),
        "ask_certificate": (
            "📜 <b>Standart yoki sertifikat raqamini kiriting</b>\n"
            "Masalan: GOST 31108-2020\n"
            "Yo'q bo'lsa — «Mavjud emas» deb yozing. Sertifikat rasmini ham yuborishingiz mumkin."
        ),
        "ask_media": (
            "📸 <b>Mahsulot rasmlari yoki videosini yuboring</b>\n"
            "📷 Kamida {min_photos} ta rasm yoki 🎥 1 ta video.\n"
            "Rasmlar aniq va aynan shu mahsulotga tegishli bo'lsin."
        ),
        "ask_quantity": (
            "📦 <b>Qancha miqdorda mavjud?</b>\n"
            "Masalan: 50 tonna, 10 000 dona, 2 500 m²"
        ),
        "ask_delivery": "🚚 <b>Yetkazib berish qanday amalga oshiriladi?</b>",
        "ask_region": (
            "📍 <b>Mahsulot qayerda joylashgan?</b>\n"
            "Viloyatni tanlang 👇"
        ),
        # --- xatolik / ogohlantirish xabarlari ---
        "need_text": "⚠️ Iltimos, javobni matn ko'rinishida yozing.",
        "text_too_short": "⚠️ Javob juda qisqa. Iltimos, to'liqroq yozing.",
        "text_too_long": "⚠️ Javob juda uzun (ko'pi bilan {max_chars} ta belgi). Iltimos, qisqartiring.",
        "desc_too_short": (
            "⚠️ Ma'lumot juda qisqa. Siz {count} ta so'z yozdingiz, kamida {min} ta "
            "so'z kerak. Iltimos, mahsulot haqida batafsilroq yozing."
        ),
        "desc_too_long": (
            "⚠️ Ma'lumot juda uzun. Siz {count} ta so'z yozdingiz, ko'pi bilan {max} "
            "ta so'z bo'lishi kerak. Iltimos, qisqartiring."
        ),
        "cert_invalid": (
            "⚠️ Iltimos, standart/sertifikat raqamini matn ko'rinishida yozing yoki "
            "sertifikat rasmini yuboring."
        ),
        "media_need_more": "📷 Qabul qilindi: {count} ta rasm. Yana kamida {left} ta rasm yuboring.",
        "media_enough": (
            "📷 Qabul qilindi: {count} ta rasm. Yana rasm yuborishingiz yoki "
            "«Tayyor» tugmasini bosishingiz mumkin."
        ),
        "media_max": "ℹ️ Maksimal {max_photos} ta rasm qabul qilinadi. «Tayyor» tugmasini bosing.",
        "media_video_ok": "🎥 Video qabul qilindi!",
        "media_invalid": (
            "⚠️ Iltimos, mahsulot rasmini (kamida {min_photos} ta) yoki videosini "
            "yuboring. Matn yoki boshqa fayl qabul qilinmaydi."
        ),
        "media_not_enough": "⚠️ Kamida {min_photos} ta rasm yoki video yuborilishi shart! Hozircha: {count} ta rasm.",
        "phone_invalid": (
            "⚠️ Telefon raqami noto'g'ri. Iltimos, to'g'ri formatda kiriting.\n"
            "Masalan: +998 90 123 45 67"
        ),
        # --- tasdiqlash ---
        "ad_title": "📝 <b>E'loningiz shakllantirilmoqda</b>",
        "confirm_ask": "Ma'lumotlar to'g'rimi? Tasdiqlang yoki o'zgartiring 👇",
        "edit_menu": "✏️ <b>O'zgartirmoqchi bo'lgan bo'limingizni tanlang:</b>",
        "final": (
            "✅ <b>E'loningiz qabul qilindi!</b>\n"
            "🎉 E'loningiz muvaffaqiyatli tasdiqlandi va hozirda KARKAZ Telegram "
            "kanaliga joylashtirilmoqda.\n"
            "🏗️ KARKAZ — qurilish materiallari savdosida ishonchli hamkoringiz! 🤝"
        ),
        "cancelled": "❌ Jarayon bekor qilindi. Qaytadan boshlash uchun /start bosing.",
    },
    "ru": {
        "ask_activity": "🏢 <b>В каком качестве вы осуществляете деятельность?</b>",
        "ask_phone": (
            "📞 <b>Введите номер телефона</b>\n"
            "Например: +998 90 123 45 67"
        ),
        "ask_org": (
            "🏢 <b>Введите название организации</b>\n"
            "Например: Tadjiyev Grup Management"
        ),
        "ask_description": (
            "📝 <b>Введите подробную информацию о товаре</b>\n"
            "📦 Опишите, для чего используется товар, его размеры, состав, бренд и "
            "технические характеристики — не менее {min} и не более {max} слов.\n"
            "ℹ️ Информация должна быть точной и понятной. Это поможет покупателям "
            "лучше понять товар и сделать правильный выбор."
        ),
        "ask_price": (
            "🧱 <b>Укажите цену</b>\n"
            "Цена и единица измерения.\n"
            "Например: 1 тонна цемента — 850 000 сум"
        ),
        "ask_certificate": (
            "📜 <b>Укажите номер стандарта или сертификата</b>\n"
            "Например: ГОСТ 31108-2020\n"
            "Если нет — напишите «Отсутствует». Можно также отправить фото сертификата."
        ),
        "ask_media": (
            "📸 <b>Отправьте фото или видео товара</b>\n"
            "📷 Не менее {min_photos} фото или 🎥 1 видео.\n"
            "Фото должны быть чёткими и относиться именно к этому товару."
        ),
        "ask_quantity": (
            "📦 <b>Какое количество в наличии?</b>\n"
            "Например: 50 тонн, 10 000 штук, 2 500 м²"
        ),
        "ask_delivery": "🚚 <b>Как осуществляется доставка?</b>",
        "ask_region": (
            "📍 <b>Где находится товар?</b>\n"
            "Выберите область 👇"
        ),
        "need_text": "⚠️ Пожалуйста, напишите ответ текстом.",
        "text_too_short": "⚠️ Ответ слишком короткий. Пожалуйста, напишите подробнее.",
        "text_too_long": "⚠️ Ответ слишком длинный (не более {max_chars} символов). Пожалуйста, сократите.",
        "desc_too_short": (
            "⚠️ Описание слишком короткое. Вы написали слов: {count}, необходимо не "
            "менее {min}. Пожалуйста, опишите товар подробнее."
        ),
        "desc_too_long": (
            "⚠️ Описание слишком длинное. Вы написали слов: {count}, допускается не "
            "более {max}. Пожалуйста, сократите текст."
        ),
        "cert_invalid": (
            "⚠️ Пожалуйста, напишите номер стандарта/сертификата текстом или "
            "отправьте фото сертификата."
        ),
        "media_need_more": "📷 Принято: {count} фото. Отправьте ещё не менее {left} фото.",
        "media_enough": (
            "📷 Принято: {count} фото. Вы можете отправить ещё или нажать кнопку "
            "«Готово»."
        ),
        "media_max": "ℹ️ Принимается не более {max_photos} фото. Нажмите «Готово».",
        "media_video_ok": "🎥 Видео принято!",
        "media_invalid": (
            "⚠️ Пожалуйста, отправьте фото товара (не менее {min_photos}) или видео. "
            "Текст и другие файлы не принимаются."
        ),
        "media_not_enough": "⚠️ Необходимо отправить не менее {min_photos} фото или видео! Сейчас: {count} фото.",
        "phone_invalid": (
            "⚠️ Номер телефона указан неверно. Пожалуйста, введите в правильном формате.\n"
            "Например: +998 90 123 45 67"
        ),
        "ad_title": "📝 <b>Ваше объявление формируется</b>",
        "confirm_ask": "Данные верны? Подтвердите или измените 👇",
        "edit_menu": "✏️ <b>Выберите раздел, который хотите изменить:</b>",
        "final": (
            "✅ <b>Ваше объявление принято!</b>\n"
            "🎉 Ваше объявление успешно подтверждено и в настоящее время "
            "размещается в Telegram-канале KARKAZ.\n"
            "🏗️ KARKAZ — ваш надёжный партнёр в торговле строительными материалами! 🤝"
        ),
        "cancelled": "❌ Процесс отменён. Чтобы начать заново, нажмите /start.",
    },
}
 
LABELS = {
    "uz": {
        "activity": {"legal": "🏛️ Yuridik shaxs", "individual": "👤 Jismoniy shaxs"},
        "delivery": {
            "buyer": "🚛 Xaridor hisobidan",
            "included": "📦 Narxga kiritilgan",
            "contract": "🤝 Shartnoma asosida",
        },
        "region": {
            "tashkent_city": "Toshkent shahri",
            "tashkent_region": "Toshkent viloyati",
            "andijan": "Andijon viloyati",
            "fergana": "Farg'ona viloyati",
            "namangan": "Namangan viloyati",
            "samarkand": "Samarqand viloyati",
            "bukhara": "Buxoro viloyati",
            "navoi": "Navoiy viloyati",
            "jizzakh": "Jizzax viloyati",
            "syrdarya": "Sirdaryo viloyati",
            "kashkadarya": "Qashqadaryo viloyati",
            "surkhandarya": "Surxondaryo viloyati",
            "khorezm": "Xorazm viloyati",
            "karakalpakstan": "Qoraqalpog'iston Resp.",
        },
        "back": "↩️ Orqaga",
        "done": "✅ Tayyor",
        "confirm_yes": "✅ Ha, tasdiqlayman",
        "confirm_edit": "✏️ O'zgartirish kiritaman",
        "new_post": "📢 Yana e'lon joylash",
    },
    "ru": {
        "activity": {"legal": "🏛️ Юридическое лицо", "individual": "👤 Физическое лицо"},
        "delivery": {
            "buyer": "🚛 За счёт покупателя",
            "included": "📦 Включена в цену",
            "contract": "🤝 По договору",
        },
        "region": {
            "tashkent_city": "г. Ташкент",
            "tashkent_region": "Ташкентская обл.",
            "andijan": "Андижанская обл.",
            "fergana": "Ферганская обл.",
            "namangan": "Наманганская обл.",
            "samarkand": "Самаркандская обл.",
            "bukhara": "Бухарская обл.",
            "navoi": "Навоийская обл.",
            "jizzakh": "Джизакская обл.",
            "syrdarya": "Сырдарьинская обл.",
            "kashkadarya": "Кашкадарьинская обл.",
            "surkhandarya": "Сурхандарьинская обл.",
            "khorezm": "Хорезмская обл.",
            "karakalpakstan": "Каракалпакстан",
        },
        "back": "↩️ Назад",
        "done": "✅ Готово",
        "confirm_yes": "✅ Да, подтверждаю",
        "confirm_edit": "✏️ Внести изменения",
        "new_post": "📢 Разместить ещё объявление",
    },
}
 
SUMMARY = {
    "uz": {
        "activity": "🏢 Faoliyat turi",
        "phone": "📞 Telefon",
        "org": "🏢 Tashkilot",
        "description": "📝 Ma'lumot",
        "price": "🧱 Narxi",
        "certificate": "📜 Standart/sertifikat",
        "quantity": "📦 Miqdori",
        "delivery": "🚚 Yetkazib berish",
        "region": "📍 Hudud",
        "media": "📸 Rasm/video",
        "photo_attached": "📷 rasm biriktirilgan",
    },
    "ru": {
        "activity": "🏢 Вид деятельности",
        "phone": "📞 Телефон",
        "org": "🏢 Организация",
        "description": "📝 Описание",
        "price": "🧱 Цена",
        "certificate": "📜 Стандарт/сертификат",
        "quantity": "📦 Количество",
        "delivery": "🚚 Доставка",
        "region": "📍 Регион",
        "media": "📸 Фото/видео",
        "photo_attached": "📷 фото приложено",
    },
}
 
 
def T(lang: str, key: str, **kw) -> str:
    """Matnni oladi va umumiy cheklovlarni joyiga qo'yadi."""
    return TEXTS[lang][key].format(
        min=MIN_DESC_WORDS,
        max=MAX_DESC_WORDS,
        min_photos=MIN_PHOTOS,
        max_photos=MAX_PHOTOS,
        max_chars=MAX_SHORT_CHARS,
        **kw,
    )
 
 
# ---------------------------------------------------------------------------
# KLAVIATURALAR
# ---------------------------------------------------------------------------
def start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📢 E'lon joylash / Разместить объявление",
                callback_data="start_post",
            )]
        ]
    )
 
 
def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇺🇿 UZB tili", callback_data="lang:uz"),
                InlineKeyboardButton(text="🇷🇺 Rus tili / Русский", callback_data="lang:ru"),
            ]
        ]
    )
 
 
def options_kb(lang: str, group: str, prefix: str, columns: int = 1) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"{prefix}:{code}")
        for code, label in LABELS[lang][group].items()
    ]
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    return InlineKeyboardMarkup(inline_keyboard=rows)
 
 
def done_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=LABELS[lang]["done"], callback_data="media_done")]]
    )
 
 
def confirm_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=LABELS[lang]["confirm_yes"], callback_data="confirm:yes")],
            [InlineKeyboardButton(text=LABELS[lang]["confirm_edit"], callback_data="confirm:edit")],
        ]
    )
 
 
# tahrirlash menyusi: (callback kodi, holat, SUMMARY yorlig'i)
EDIT_FIELDS = [
    ("activity", Form.activity, "activity"),
    ("phone", Form.phone, "phone"),
    ("org_name", Form.org_name, "org"),
    ("description", Form.description, "description"),
    ("price", Form.price, "price"),
    ("certificate", Form.certificate, "certificate"),
    ("media", Form.media, "media"),
    ("quantity", Form.quantity, "quantity"),
    ("delivery", Form.delivery, "delivery"),
    ("region", Form.region, "region"),
]
EDIT_STEPS = {code: step for code, step, _ in EDIT_FIELDS}
 
 
def edit_kb(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=SUMMARY[lang][label], callback_data=f"edit:{code}")
        for code, _, label in EDIT_FIELDS
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text=LABELS[lang]["back"], callback_data="edit:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
 
 
def new_post_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=LABELS[lang]["new_post"], callback_data="start_post")]]
    )
 
 
# ---------------------------------------------------------------------------
# YORDAMCHI FUNKSIYALAR
# ---------------------------------------------------------------------------
_locks: dict = {}
 
 
def get_lock(user_id: int) -> asyncio.Lock:
    """Bir foydalanuvchining bir vaqtda kelgan xabarlari (masalan albom) bir-biriga xalaqit bermasligi uchun."""
    return _locks.setdefault(user_id, asyncio.Lock())
 
 
def esc(value) -> str:
    return html.escape(str(value or ""), quote=False)
 
 
def visible_len(text: str) -> int:
    """Telegram caption chegarasi teglarsiz ko'rinadigan belgilarni sanaydi."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", text)))
 
 
def count_words(text: str) -> int:
    return len(text.split())
 
 
def is_valid_phone(text: str) -> bool:
    if not re.fullmatch(r"[+\d\s()\-]+", text):
        return False
    digits = re.sub(r"\D", "", text)
    return 9 <= len(digits) <= 13
 
 
def split_text(text: str, limit: int = 3900) -> list:
    """Telegram 4096 belgi chegarasidan oshib ketmasligi uchun qatorlar bo'yicha bo'ladi."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks
 
 
async def mark_chosen(callback: CallbackQuery, label: str) -> None:
    """Bosilgan tugmalarni olib tashlab, tanlovni xabar tagiga yozib qo'yadi."""
    try:
        await callback.message.edit_text(
            f"{callback.message.html_text}\n\n✅ <b>{esc(label)}</b>",
            reply_markup=None,
        )
    except Exception as e:
        logger.debug("mark_chosen: %s", e)
 
 
async def remove_buttons(callback: CallbackQuery) -> None:
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.debug("remove_buttons: %s", e)
 
 
TEXT_KEYS = {
    Form.phone.state: "ask_phone",
    Form.org_name.state: "ask_org",
    Form.description.state: "ask_description",
    Form.price.state: "ask_price",
    Form.certificate.state: "ask_certificate",
    Form.media.state: "ask_media",
    Form.quantity.state: "ask_quantity",
}
 
 
async def ask(target: Message, state: FSMContext, step: State, lang: str) -> None:
    """Berilgan bosqichga o'tkazadi va shu bosqich savolini yuboradi."""
    await state.set_state(step)
    key = step.state
    if key == Form.language.state:
        await target.answer(ASK_LANGUAGE, reply_markup=language_kb())
    elif key == Form.activity.state:
        await target.answer(T(lang, "ask_activity"), reply_markup=options_kb(lang, "activity", "act"))
    elif key == Form.delivery.state:
        await target.answer(T(lang, "ask_delivery"), reply_markup=options_kb(lang, "delivery", "deliv"))
    elif key == Form.region.state:
        await target.answer(T(lang, "ask_region"), reply_markup=options_kb(lang, "region", "reg", columns=2))
    else:
        await target.answer(T(lang, TEXT_KEYS[key]))
 
 
async def advance(target: Message, state: FSMContext, next_step, lang: str) -> None:
    """Javob qabul qilingach: oddiy rejimda keyingi savolga, tahrirlash rejimida
    (yoki oxirgi savoldan keyin) yangilangan e'lonni ko'rsatishga o'tadi."""
    data = await state.get_data()
    if data.get("edit_mode") or next_step is None:
        await state.update_data(edit_mode=False)
        await show_confirmation(target, state, lang)
    else:
        await ask(target, state, next_step, lang)
 
 
def cert_summary(data: dict, lang: str) -> str:
    parts = []
    if data.get("cert_text"):
        parts.append(esc(data["cert_text"]))
    if data.get("cert_photo"):
        parts.append(SUMMARY[lang]["photo_attached"])
    return " + ".join(parts) or "—"
 
 
def ad_lines(data: dict, lang: str) -> list:
    """E'lon maydonlari (savollar tartibida). Maydon nomlari qalin (bold) yoziladi."""
    S, lab = SUMMARY[lang], LABELS[lang]
    return [
        f"<b>{S['activity']}:</b> {lab['activity'][data['activity']]}",
        f"<b>{S['phone']}:</b> {esc(data['phone'])}",
        f"<b>{S['org']}:</b> {esc(data['org_name'])}",
        f"<b>{S['description']}:</b> {esc(data['description'])}",
        f"<b>{S['price']}:</b> {esc(data['price'])}",
        f"<b>{S['certificate']}:</b> {cert_summary(data, lang)}",
        f"<b>{S['quantity']}:</b> {esc(data['quantity'])}",
        f"<b>{S['delivery']}:</b> {lab['delivery'][data['delivery']]}",
        f"<b>{S['region']}:</b> {lab['region'][data['region']]}",
    ]
 
 
def build_summary(data: dict, lang: str) -> str:
    """Foydalanuvchiga ko'rsatiladigan e'lon (tepada: 'E'loningiz shakllantirilmoqda')."""
    return "\n".join([T(lang, "ad_title"), ""] + ad_lines(data, lang))
 
 
def build_admin_text(data: dict, user) -> str:
    """Admin uchun ariza matni (doim o'zbek tilida)."""
    username = f"@{user.username}" if user.username else "username yo'q"
    return "\n".join(
        [
            "🆕 <b>YANGI E'LON</b>",
            f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  🌐 {data['lang'].upper()}",
            "",
        ]
        + ad_lines(data, "uz")
        + [
            "",
            f"👤 {esc(user.full_name)} | {esc(username)} | ID: <code>{user.id}</code>",
        ]
    )
 
 
async def send_media(chat_id: int, data: dict, caption: str = None) -> None:
    """Rasm/videolarni albom qilib yuboradi; caption birinchi elementga qo'yiladi."""
    items = [("photo", f) for f in data.get("photos", [])]
    if data.get("video"):
        items.append(("video", data["video"]))
    for i in range(0, len(items), 10):
        chunk = items[i:i + 10]
        cap = caption if i == 0 else None
        if len(chunk) == 1:
            kind, fid = chunk[0]
            if kind == "photo":
                await bot.send_photo(chat_id, fid, caption=cap)
            else:
                await bot.send_video(chat_id, fid, caption=cap)
        else:
            media = []
            for j, (kind, fid) in enumerate(chunk):
                c = cap if j == 0 else None
                cls = InputMediaPhoto if kind == "photo" else InputMediaVideo
                media.append(cls(media=fid, caption=c, parse_mode=ParseMode.HTML))
            await bot.send_media_group(chat_id, media)
 
 
async def send_ad(chat_id: int, text: str, data: dict) -> None:
    """E'lonni rasm/video BILAN BIRGA yuboradi.
    Matn 1024 belgidan oshmasa — rasm tagida (bitta xabar). Oshsa — albom, undan keyin matn."""
    has_media = bool(data.get("photos") or data.get("video"))
    if has_media and visible_len(text) <= CAPTION_LIMIT:
        await send_media(chat_id, data, caption=text)
        return
    if has_media:
        await send_media(chat_id, data)
    for chunk in split_text(text):
        await bot.send_message(chat_id, chunk)
 
 
async def deliver_to_admin(data: dict, user) -> None:
    """Arizani (rasm/video + matn birga, so'ng sertifikat rasmi) adminga yuboradi."""
    try:
        await send_ad(ADMIN_ID, build_admin_text(data, user), data)
        if data.get("cert_photo"):
            await bot.send_photo(ADMIN_ID, data["cert_photo"], caption="📜 Standart / sertifikat rasmi")
    except Exception as e:
        logger.error("Adminga yuborishda xatolik: %s", e)
 
 
async def save_to_sheet(data: dict, user) -> None:
    """Arizani Google Sheets jadvaliga yozadi (agar ulangan bo'lsa)."""
    if _sheet is None:
        return
    lab = LABELS["uz"]
    username = f"@{user.username}" if user.username else "username yo'q"
    cert = data.get("cert_text") or ("rasm" if data.get("cert_photo") else "")
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        data["lang"].upper(),
        lab["activity"][data["activity"]],
        data["phone"],
        data["org_name"],
        data["description"],
        data["price"],
        cert,
        len(data.get("photos", [])),
        "Ha" if data.get("video") else "Yo'q",
        data["quantity"],
        lab["delivery"][data["delivery"]],
        lab["region"][data["region"]],
        username,
        str(user.id),
    ]
    try:
        await asyncio.to_thread(_sheet.append_row, row, value_input_option="RAW")
    except Exception as e:
        logger.error("Google Sheetsga yozishda xatolik: %s", e)
 
 
async def show_confirmation(target: Message, state: FSMContext, lang: str) -> None:
    """E'lonni rasm/video bilan birga ko'rsatadi, so'ng tasdiqlash tugmalarini chiqaradi."""
    data = await state.get_data()
    await state.set_state(Form.confirm)
    await send_ad(target.chat.id, build_summary(data, lang), data)
    await target.answer(T(lang, "confirm_ask"), reply_markup=confirm_kb(lang))
 
 
# ---------------------------------------------------------------------------
# BUYRUQLAR: /start va /cancel (istalgan paytda ishlaydi)
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(WELCOME, reply_markup=start_kb())
 
 
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    lang = (await state.get_data()).get("lang", "uz")
    await state.clear()
    await message.answer(T(lang, "cancelled"), reply_markup=start_kb())
 
 
@router.callback_query(F.data == "start_post")
async def start_post(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await remove_buttons(callback)
    await ask(callback.message, state, Form.language, "uz")
    await callback.answer()
 
 
# ---------------------------------------------------------------------------
# TUGMALI BOSQICHLAR
# ---------------------------------------------------------------------------
@router.callback_query(Form.language, F.data.startswith("lang:"))
async def choose_language(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split(":", 1)[1]
    if lang not in TEXTS:
        await callback.answer()
        return
    await state.update_data(lang=lang)
    await mark_chosen(callback, "UZB tili" if lang == "uz" else "Rus tili / Русский")
    await ask(callback.message, state, Form.activity, lang)
    await callback.answer()
 
 
@router.callback_query(Form.activity, F.data.startswith("act:"))
async def choose_activity(callback: CallbackQuery, state: FSMContext):
    lang = (await state.get_data())["lang"]
    code = callback.data.split(":", 1)[1]
    if code not in LABELS[lang]["activity"]:
        await callback.answer()
        return
    await state.update_data(activity=code)
    await mark_chosen(callback, LABELS[lang]["activity"][code])
    await advance(callback.message, state, Form.phone, lang)
    await callback.answer()
 
 
@router.callback_query(Form.delivery, F.data.startswith("deliv:"))
async def choose_delivery(callback: CallbackQuery, state: FSMContext):
    lang = (await state.get_data())["lang"]
    code = callback.data.split(":", 1)[1]
    if code not in LABELS[lang]["delivery"]:
        await callback.answer()
        return
    await state.update_data(delivery=code)
    await mark_chosen(callback, LABELS[lang]["delivery"][code])
    await advance(callback.message, state, Form.region, lang)
    await callback.answer()
 
 
@router.callback_query(Form.region, F.data.startswith("reg:"))
async def choose_region(callback: CallbackQuery, state: FSMContext):
    lang = (await state.get_data())["lang"]
    code = callback.data.split(":", 1)[1]
    if code not in LABELS[lang]["region"]:
        await callback.answer()
        return
    await state.update_data(region=code)
    await mark_chosen(callback, LABELS[lang]["region"][code])
    await advance(callback.message, state, None, lang)
    await callback.answer()
 
 
# ---------------------------------------------------------------------------
# TELEFON (2-savol)
# ---------------------------------------------------------------------------
@router.message(Form.phone, F.contact)
async def get_phone_contact(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    await state.update_data(phone=message.contact.phone_number)
    await advance(message, state, Form.org_name, lang)
 
 
@router.message(Form.phone, F.text & ~F.text.startswith("/"))
async def get_phone(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    text = message.text.strip()
    if not is_valid_phone(text):
        await message.answer(T(lang, "phone_invalid"))
        return
    await state.update_data(phone=text)
    await advance(message, state, Form.org_name, lang)
 
 
# ---------------------------------------------------------------------------
# QISQA MATNLI BOSQICHLAR
# ---------------------------------------------------------------------------
TEXT_FILTER = F.text & ~F.text.startswith("/")
 
# holat -> (saqlanadigan maydon, keyingi bosqich; None = tasdiqlashga)
SHORT_TEXT_STEPS = {
    Form.org_name.state: ("org_name", Form.description),
    Form.price.state: ("price", Form.certificate),
    Form.quantity.state: ("quantity", Form.delivery),
}
 
 
@router.message(
    StateFilter(Form.org_name, Form.price, Form.quantity),
    TEXT_FILTER,
)
async def short_text_answer(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    text = re.sub(r"\s+", " ", message.text).strip()
    if len(text) < 2:
        await message.answer(T(lang, "text_too_short"))
        return
    if len(text) > MAX_SHORT_CHARS:
        await message.answer(T(lang, "text_too_long"))
        return
    field, next_step = SHORT_TEXT_STEPS[await state.get_state()]
    await state.update_data(**{field: text})
    await advance(message, state, next_step, lang)
 
 
@router.message(Form.description, TEXT_FILTER)
async def get_description(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    text = message.text.strip()
    words = count_words(text)
    if words < MIN_DESC_WORDS:
        await message.answer(T(lang, "desc_too_short", count=words))
        return
    if words > MAX_DESC_WORDS or len(text) > MAX_DESC_CHARS:
        await message.answer(T(lang, "desc_too_long", count=words))
        return
    await state.update_data(description=text)
    await advance(message, state, Form.price, lang)
 
 
# --- standart / sertifikat: matn YOKI rasm majburiy ---
@router.message(Form.certificate, TEXT_FILTER)
async def get_certificate_text(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    text = re.sub(r"\s+", " ", message.text).strip()
    if len(text) < 2:
        await message.answer(T(lang, "text_too_short"))
        return
    if len(text) > MAX_SHORT_CHARS:
        await message.answer(T(lang, "text_too_long"))
        return
    await state.update_data(cert_text=text, cert_photo=None)
    await advance(message, state, Form.media, lang)
 
 
@router.message(Form.certificate, F.photo)
async def get_certificate_photo(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    caption = re.sub(r"\s+", " ", message.caption or "").strip()[:MAX_SHORT_CHARS]
    await state.update_data(cert_photo=message.photo[-1].file_id, cert_text=caption or None)
    await advance(message, state, Form.media, lang)
 
 
@router.message(StateFilter(Form.certificate))
async def certificate_invalid(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    await message.answer(T(lang, "cert_invalid"))
 
 
# --- rasm (kamida MIN_PHOTOS ta) yoki video: majburiy ---
@router.message(Form.media, F.video)
async def get_video(message: Message, state: FSMContext):
    async with get_lock(message.from_user.id):
        data = await state.get_data()
        if await state.get_state() != Form.media.state:
            return
        lang = data["lang"]
        await state.update_data(video=message.video.file_id)
    await message.answer(T(lang, "media_video_ok"))
    await advance(message, state, Form.quantity, lang)
 
 
@router.message(Form.media, F.photo)
async def get_photo(message: Message, state: FSMContext):
    async with get_lock(message.from_user.id):
        data = await state.get_data()
        lang = data["lang"]
        photos = list(data.get("photos", []))
        if len(photos) < MAX_PHOTOS:
            photos.append(message.photo[-1].file_id)
        seq = data.get("media_seq", 0) + 1
        await state.update_data(photos=photos, media_seq=seq)
 
    # Albom yuborilganda har bir rasmga alohida javob bermaslik uchun biroz kutamiz:
    # faqat eng oxirgi kelgan rasm holat xabarini yuboradi.
    await asyncio.sleep(1.2)
    data = await state.get_data()
    if data.get("media_seq") != seq or await state.get_state() != Form.media.state:
        return
 
    count = len(data.get("photos", []))
    if count >= MIN_PHOTOS:
        text = T(lang, "media_enough", count=count)
        if count >= MAX_PHOTOS:
            text += "\n" + T(lang, "media_max")
        await message.answer(text, reply_markup=done_kb(lang))
    else:
        await message.answer(T(lang, "media_need_more", count=count, left=MIN_PHOTOS - count))
 
 
@router.callback_query(Form.media, F.data == "media_done")
async def media_done(callback: CallbackQuery, state: FSMContext):
    async with get_lock(callback.from_user.id):
        data = await state.get_data()
        if await state.get_state() != Form.media.state:
            await callback.answer()
            return
        lang = data["lang"]
        count = len(data.get("photos", []))
        if count < MIN_PHOTOS and not data.get("video"):
            await callback.answer(
                T(lang, "media_not_enough", count=count), show_alert=True
            )
            return
        await state.set_state(Form.quantity)  # ikki marta bosilishidan himoya
    await remove_buttons(callback)
    await advance(callback.message, state, Form.quantity, lang)
    await callback.answer()
 
 
@router.message(StateFilter(Form.media))
async def media_invalid(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    await message.answer(T(lang, "media_invalid"))
 
 
# ---------------------------------------------------------------------------
# TASDIQLASH
# ---------------------------------------------------------------------------
@router.callback_query(Form.confirm, F.data == "confirm:edit")
async def confirm_edit(callback: CallbackQuery, state: FSMContext):
    lang = (await state.get_data())["lang"]
    await remove_buttons(callback)
    await state.set_state(Form.edit_choice)
    await callback.message.answer(T(lang, "edit_menu"), reply_markup=edit_kb(lang))
    await callback.answer()
 
 
@router.callback_query(Form.edit_choice, F.data.startswith("edit:"))
async def edit_choose(callback: CallbackQuery, state: FSMContext):
    lang = (await state.get_data())["lang"]
    code = callback.data.split(":", 1)[1]
 
    if code == "back":  # hech narsani o'zgartirmasdan tasdiqlashga qaytish
        await remove_buttons(callback)
        await state.set_state(Form.confirm)
        await callback.message.answer(T(lang, "confirm_ask"), reply_markup=confirm_kb(lang))
        await callback.answer()
        return
 
    if code not in EDIT_STEPS:
        await callback.answer()
        return
 
    label_key = next(lbl for c, _, lbl in EDIT_FIELDS if c == code)
    await mark_chosen(callback, SUMMARY[lang][label_key])
 
    updates = {"edit_mode": True}
    if code == "media":  # rasm/video yangidan so'raladi
        updates.update(photos=[], video=None, media_seq=0)
    if code == "certificate":
        updates.update(cert_text=None, cert_photo=None)
    await state.update_data(**updates)
    await ask(callback.message, state, EDIT_STEPS[code], lang)
    await callback.answer()
 
 
@router.callback_query(Form.confirm, F.data == "confirm:yes")
async def confirm_yes(callback: CallbackQuery, state: FSMContext):
    async with get_lock(callback.from_user.id):
        if await state.get_state() != Form.confirm.state:
            await callback.answer()
            return
        data = await state.get_data()
        await state.clear()  # ikki marta bosilsa, ariza ikki marta ketmaydi
 
    lang = data["lang"]
    await remove_buttons(callback)
    await callback.message.answer(T(lang, "final"), reply_markup=new_post_kb(lang))
    await callback.answer()
 
    await deliver_to_admin(data, callback.from_user)
    await save_to_sheet(data, callback.from_user)
 
 
# ---------------------------------------------------------------------------
# TUGMA KUTILAYOTGAN BOSQICHLARDA MATN YOZILSA -> savolni qayta ko'rsatamiz
# ---------------------------------------------------------------------------
@router.message(StateFilter(Form.language, Form.activity, Form.delivery, Form.region))
async def button_expected(message: Message, state: FSMContext):
    current = await state.get_state()
    lang = (await state.get_data()).get("lang", "uz")
    step = {
        Form.language.state: Form.language,
        Form.activity.state: Form.activity,
        Form.delivery.state: Form.delivery,
        Form.region.state: Form.region,
    }[current]
    await ask(message, state, step, lang)
 
 
@router.message(StateFilter(Form.edit_choice))
async def edit_expected(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    await message.answer(T(lang, "edit_menu"), reply_markup=edit_kb(lang))
 
 
@router.message(StateFilter(Form.confirm))
async def confirm_expected(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    await message.answer(T(lang, "confirm_ask"), reply_markup=confirm_kb(lang))
 
 
# ---------------------------------------------------------------------------
# MATN KUTILAYOTGAN BOSQICHLARDA MATN BO'LMAGAN NARSA YUBORILSA
# ---------------------------------------------------------------------------
@router.message(
    StateFilter(
        Form.phone, Form.org_name, Form.description, Form.price,
        Form.quantity,
    )
)
async def text_expected(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    await message.answer(T(lang, "need_text"))
 
 
# Holatga mos kelmagan eski tugmalar bosilsa - jim "yuklanmoqda"ni to'xtatamiz
@router.callback_query()
async def stale_callback(callback: CallbackQuery):
    await callback.answer()
 
 
# Holatsiz (masalan bot qayta ishga tushgandan keyin) kelgan xabarlar
@router.message()
async def no_state_message(message: Message, state: FSMContext):
    await message.answer(WELCOME, reply_markup=start_kb())
 
 
# ---------------------------------------------------------------------------
# ISHGA TUSHIRISH
# ---------------------------------------------------------------------------
async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
 
 
if __name__ == "__main__":
    asyncio.run(main())
 
