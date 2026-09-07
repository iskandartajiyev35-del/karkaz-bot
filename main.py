"""
KARKAZ B2B Bot
Tadbirkorlardan mahsulot e'lonlarini qabul qiluvchi Telegram bot.

Ishlash tartibi:
/start -> til tanlash -> tashkilot nomi -> mahsulot ma'lumotlari
-> video -> telefon -> tasdiqlash xabarlari -> admin ga yuborish
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ---------------------------------------------------------------------------
# SOZLAMALAR (Railway'da Variables bo'limidan kiritiladi, kodga yozilmaydi!)
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")  # sizning shaxsiy Telegram ID raqamingiz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi! Railway'ning Variables bo'limiga qo'shing.")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID topilmadi! Railway'ning Variables bo'limiga qo'shing.")

ADMIN_ID = int(ADMIN_ID)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# ---------------------------------------------------------------------------
# HOLATLAR (FSM) - suhbat qaysi bosqichda ekanini kuzatib boradi
# ---------------------------------------------------------------------------
class Form(StatesGroup):
    org_name = State()
    location = State()
    product_name = State()
    size = State()
    expiry = State()
    video = State()
    phone = State()


# ---------------------------------------------------------------------------
# TILLAR
# ---------------------------------------------------------------------------
TEXTS = {
    "uz": {
        "choose_lang": "Assalomu alaykum! 👋\nIltimos, tilni tanlang:",
        "ask_org": "🏢 Tashkilotingiz nomi:",
        "product_header": "📦 Mahsulot haqida ma'lumot kiriting",
        "ask_location": "📍 Mahsulot qayerda joylashgan?",
        "ask_name": "🏷 Mahsulot nomi:",
        "ask_size": "📏 Mahsulot hajmi / o'lchami:",
        "ask_expiry": "📅 Amal qilish muddati:",
        "video_request": (
            "🎥 Mahsulotingiz haqida video yuboring\n"
            "📌 Videoni yuqori sifatda yuborishingizni so'raymiz.\n"
            "✅ Tavsiya etiladigan sifat: 1080p (Full HD) yoki undan yuqori\n"
            "📱 Video aniq, yorug' va mahsulot yaxshi ko'rinadigan bo'lishi kerak.\n"
            "👇 Mahsulot videosini yuboring"
        ),
        "video_invalid": "⚠️ Iltimos, video formatida yuboring (rasm yoki matn emas).",
        "phone_request": (
            "📞 Bog'lanish uchun telefon raqamingizni qoldiring\n"
            "Mahsulotingiz bo'yicha xaridorlar siz bilan bog'lanishi uchun "
            "amaldagi telefon raqamingizni kiriting.\n"
            "📱 Telefon raqamingiz:\n"
            "<code>+998 __ ___ __ __</code>\n\n"
            "❓ Savol yoki qo'shimcha ma'lumot kerakmi?\n"
            "☎️ Murojaat uchun: +998 90 111 60 06"
        ),
        "success": (
            "✅ Arizangiz muvaffaqiyatli qabul qilindi!\n"
            "📋 Siz taqdim etgan ma'lumotlar hozirda ko'rib chiqilmoqda.\n"
            "⏳ Ma'lumotlar tekshirilgach, mutaxassislarimiz siz bilan telefon "
            "orqali bog'lanishadi.\n"
            "📞 Iltimos, telefon raqamingiz doimo aloqada bo'lishini ta'minlang.\n"
            "🙏 Murojaatingiz uchun rahmat!\n"
            "🤝 Siz bilan hamkorlik qilishdan mamnunmiz."
        ),
        "review": (
            "⚠️ Diqqat!\n"
            "📋 E'loningiz hozirda ko'rib chiqilmoqda.\n"
            "💰 Shu bilan birga, mahsulotingiz uchun narx hisoblanmoqda.\n"
            "⏳ Tekshiruv va hisob-kitob yakunlangach, mahsulotingizga yakuniy "
            "narx belgilanadi.\n"
            "📞 Natija bo'yicha siz bilan bog'lanamiz.\n"
            "🙏 Sabringiz va hamkorligingiz uchun rahmat!"
        ),
        "cancelled": "❌ Jarayon bekor qilindi. Qaytadan boshlash uchun /start bosing.",
    },
    "ru": {
        "choose_lang": "Здравствуйте! 👋\nПожалуйста, выберите язык:",
        "ask_org": "🏢 Название вашей организации:",
        "product_header": "📦 Введите информацию о товаре",
        "ask_location": "📍 Где находится товар?",
        "ask_name": "🏷 Название товара:",
        "ask_size": "📏 Размер / объём товара:",
        "ask_expiry": "📅 Срок годности / действия:",
        "video_request": (
            "🎥 Отправьте видео о вашем товаре\n"
            "📌 Просим отправить видео в хорошем качестве.\n"
            "✅ Рекомендуемое качество: 1080p (Full HD) и выше\n"
            "📱 Видео должно быть чётким, светлым, товар должен быть хорошо виден.\n"
            "👇 Отправьте видео товара"
        ),
        "video_invalid": "⚠️ Пожалуйста, отправьте именно видео (не фото и не текст).",
        "phone_request": (
            "📞 Оставьте номер телефона для связи\n"
            "Чтобы покупатели могли связаться с вами по поводу товара, укажите "
            "действующий номер телефона.\n"
            "📱 Ваш номер телефона:\n"
            "<code>+998 __ ___ __ __</code>\n\n"
            "❓ Есть вопросы или нужна доп. информация?\n"
            "☎️ Для обращения: +998 90 111 60 06"
        ),
        "success": (
            "✅ Ваша заявка успешно принята!\n"
            "📋 Предоставленные вами данные сейчас рассматриваются.\n"
            "⏳ После проверки данных наши специалисты свяжутся с вами по телефону.\n"
            "📞 Пожалуйста, обеспечьте доступность вашего номера телефона.\n"
            "🙏 Спасибо за обращение!\n"
            "🤝 Мы рады сотрудничеству с вами."
        ),
        "review": (
            "⚠️ Внимание!\n"
            "📋 Ваше объявление сейчас рассматривается.\n"
            "💰 Одновременно рассчитывается цена на ваш товар.\n"
            "⏳ После завершения проверки и расчёта будет установлена итоговая "
            "цена на ваш товар.\n"
            "📞 Мы свяжемся с вами по результатам.\n"
            "🙏 Спасибо за терпение и сотрудничество!"
        ),
        "cancelled": "❌ Процесс отменён. Чтобы начать заново, нажмите /start.",
    },
}


def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇺🇿 O'zbek tili", callback_data="lang_uz"),
                InlineKeyboardButton(text="🇷🇺 Русский язык", callback_data="lang_ru"),
            ]
        ]
    )


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Assalomu alaykum! 👋 / Здравствуйте! 👋\nTilni tanlang / Выберите язык:",
        reply_markup=lang_keyboard(),
    )


# ---------------------------------------------------------------------------
# /cancel - istalgan bosqichda jarayonni bekor qilish
# ---------------------------------------------------------------------------
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.clear()
    await message.answer(TEXTS[lang]["cancelled"])


# ---------------------------------------------------------------------------
# Til tanlash
# ---------------------------------------------------------------------------
@router.callback_query(F.data.in_({"lang_uz", "lang_ru"}))
async def choose_language(callback: CallbackQuery, state: FSMContext):
    lang = "uz" if callback.data == "lang_uz" else "ru"
    await state.update_data(lang=lang)
    await state.set_state(Form.org_name)

    await callback.message.edit_text(TEXTS[lang]["choose_lang"].split("\n")[0])
    await callback.message.answer(TEXTS[lang]["ask_org"])
    await callback.answer()


# ---------------------------------------------------------------------------
# Tashkilot nomi -> mahsulot bloki boshlanadi
# ---------------------------------------------------------------------------
@router.message(Form.org_name)
async def get_org_name(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(org_name=message.text)
    await state.set_state(Form.location)

    await message.answer(TEXTS[lang]["product_header"])
    await message.answer(TEXTS[lang]["ask_location"])


@router.message(Form.location)
async def get_location(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(location=message.text)
    await state.set_state(Form.product_name)
    await message.answer(TEXTS[lang]["ask_name"])


@router.message(Form.product_name)
async def get_product_name(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(product_name=message.text)
    await state.set_state(Form.size)
    await message.answer(TEXTS[lang]["ask_size"])


@router.message(Form.size)
async def get_size(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(size=message.text)
    await state.set_state(Form.expiry)
    await message.answer(TEXTS[lang]["ask_expiry"])


@router.message(Form.expiry)
async def get_expiry(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(expiry=message.text)
    await state.set_state(Form.video)
    await message.answer(TEXTS[lang]["video_request"])


# ---------------------------------------------------------------------------
# Video qabul qilish
# ---------------------------------------------------------------------------
@router.message(Form.video, F.video)
async def get_video(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(video_file_id=message.video.file_id)
    await state.set_state(Form.phone)
    await message.answer(TEXTS[lang]["phone_request"])


@router.message(Form.video)
async def get_video_invalid(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await message.answer(TEXTS[lang]["video_invalid"])


# ---------------------------------------------------------------------------
# Telefon raqami -> yakunlash
# ---------------------------------------------------------------------------
@router.message(Form.phone, F.contact)
async def get_phone_contact(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await finish_application(message, state)


@router.message(Form.phone, F.text)
async def get_phone_text(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await finish_application(message, state)


async def finish_application(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data["lang"]

    # Foydalanuvchiga ketma-ket ikkita xabar
    await message.answer(TEXTS[lang]["success"])
    await message.answer(TEXTS[lang]["review"])

    # Adminga to'liq ma'lumotni yuborish
    user = message.from_user
    username = f"@{user.username}" if user.username else "username yo'q"
    caption = (
        "🆕 <b>Yangi ariza!</b>\n\n"
        f"🏢 Tashkilot: {data.get('org_name')}\n"
        f"📍 Joylashuv: {data.get('location')}\n"
        f"🏷 Mahsulot: {data.get('product_name')}\n"
        f"📏 Hajmi: {data.get('size')}\n"
        f"📅 Muddati: {data.get('expiry')}\n"
        f"📞 Telefon: {data.get('phone')}\n\n"
        f"👤 Foydalanuvchi: {username} (ID: <code>{user.id}</code>)\n"
        f"🌐 Til: {lang.upper()}"
    )

    video_file_id = data.get("video_file_id")
    try:
        if video_file_id:
            await bot.send_video(ADMIN_ID, video_file_id, caption=caption)
        else:
            await bot.send_message(ADMIN_ID, caption)
    except Exception as e:  # admin bilan bot suhbati boshlanmagan bo'lishi mumkin
        logger.error("Adminga yuborishda xatolik: %s", e)

    await state.clear()


# ---------------------------------------------------------------------------
# ISHGA TUSHIRISH
# ---------------------------------------------------------------------------
async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
