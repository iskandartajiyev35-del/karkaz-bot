"""
KARKAZ B2B Bot  (v2)
Qurilish materiallari e'lonlarini qabul qiluvchi Telegram bot.
 
Oqim:
/start -> [E'lon joylash] -> til -> faoliyat turi -> faoliyat sifati
-> tashkilot -> brend/marka -> batafsil ma'lumot (min. so'z)
-> narx -> standart/sertifikat (matn yoki rasm) -> rasm (min. 3) yoki video
-> miqdor -> yetkazib berish -> hudud -> telefon
-> tekshirish (tasdiqlash / o'zgartirish) -> adminga yuborish (+ Google Sheets)
 
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
    role = State()
    org_name = State()
    brand = State()
    description = State()
    price = State()
    certificate = State()
    media = State()
    quantity = State()
    delivery = State()
    region = State()
    phone = State()
    confirm = State()
 
 
# ---------------------------------------------------------------------------
# MATNLAR (UZ / RU)
# ---------------------------------------------------------------------------
WELCOME = (
    "🏗 <b>KARKAZ — B2B savdo platformasi</b>\n"
    "Qurilish va biznes uchun mahsulotlar bir joyda!\n"
    "📦 Mahsulotingizni tez va oson sotish uchun e'lon joylashtiring.\n\n"
    "🏗 <b>KARKAZ — B2B платформа для торговли</b>\n"
    "Товары для строительства и бизнеса в одном месте!\n"
    "📦 Разместите объявление, чтобы быстро и легко продать свой товар.\n\n"
    "☎️ +998 90 111 60 06\n\n"
    "👇"
)
 
ASK_LANGUAGE = (
    "🌐 <b>E'loningiz qaysi tilda bo'lishini xohlaysiz?</b>\n"
    "📢 Iltimos, e'loningiz uchun qulay bo'lgan tilni tanlang. Tanlangan til "
    "asosida e'loningizni joylashtirishni davom ettiramiz. 👇\n\n"
    "— — — — — — — —\n\n"
    "🌐 <b>На каком языке вы хотите разместить объявление?</b>\n"
    "📢 Пожалуйста, выберите удобный язык для вашего объявления. Мы продолжим "
    "размещение объявления на выбранном языке. 👇"
)
 
TEXTS = {
    "uz": {
        "ask_activity": (
            "🏢 <b>Iltimos, faoliyat turini tanlang!</b>\n"
            "🤝 KARKAZ platformasida e'lon joylashtirishni davom ettirish uchun "
            "quyidagi variantlardan birini tanlang:\n\n"
            "🏛️ <b>Yuridik shaxs</b> — korxona, firma yoki tashkilot nomidan "
            "faoliyat yurituvchi tadbirkor.\n"
            "👤 <b>Jismoniy shaxs</b> — o'z nomidan mahsulot sotuvchi yoki e'lon "
            "joylashtiruvchi shaxs."
        ),
        "ask_role": (
            "🏭 <b>Siz kim sifatida faoliyat yuritasiz?</b>\n"
            "📦 Mahsulotingizni KARKAZ platformasida joylashtirish uchun quyidagi "
            "variantlardan birini tanlang:\n\n"
            "🏭 <b>Ishlab chiqaruvchi</b> — mahsulotlarni o'zingiz ishlab chiqarasiz.\n"
            "🤝 <b>Diler</b> — ishlab chiqaruvchilardan yoki yetkazib beruvchilardan "
            "mahsulot olib, xaridorlarga sotasiz."
        ),
        "ask_org": (
            "🏢 <b>Tashkilotingiz nomini kiriting</b>\n\n"
            "Korxonangiz, kompaniyangiz yoki savdo faoliyatingiz nomini kiriting.\n"
            "Masalan: “Tashkent Build Trade” MChJ"
        ),
        "ask_brand": (
            "🏷️ <b>Mahsulotning brendi va markasini kiriting</b>\n"
            "📌 Qurilish materialining ishlab chiqaruvchi brendi, markasi va "
            "modelini ko'rsating.\n"
            "Misol: M400 markali sement, ishlab chiqaruvchi — Qizilqumsement."
        ),
        "ask_description": (
            "📝 <b>Mahsulot haqida batafsil ma'lumot kiriting</b>\n"
            "📦 Mahsulotning nima uchun ishlatilishi, o'lchami, tarkibi va texnik "
            "xususiyatlari haqida kamida {min} ta, ko'pi bilan {max} ta so'z bilan "
            "ma'lumot bering.\n"
            "ℹ️ Ma'lumot aniq va tushunarli bo'lishi kerak. Bu xaridorlarga "
            "mahsulotni yaxshiroq tushunish va to'g'ri tanlashga yordam beradi."
        ),
        "ask_price": (
            "🧱 <b>Qurilish materialining narxini kiriting</b>\n"
            "Sotuvga qo'yilayotgan mahsulotning narxini va o'lchov birligini ko'rsating.\n"
            "Masalan: 1 tonna sement — 850 000 so'm yoki 1 dona g'isht — 1 200 so'm."
        ),
        "ask_certificate": (
            "📜 <b>Mahsulotning standart yoki sertifikat raqamini kiriting</b>\n"
            "🏗️ Mahsulotingizga tegishli standart (GOST, O'z DSt va boshqalar) yoki "
            "muvofiqlik sertifikati raqamini kiriting.\n"
            "📝 Misol: GOST 31108-2020 yoki sertifikat raqami: UZ.SMT.12345.\n"
            "ℹ️ Agar mahsulotda sertifikat yoki standart mavjud bo'lmasa, "
            "«Mavjud emas» deb yozishingiz mumkin.\n\n"
            "📷 Raqamni matn ko'rinishida yozishingiz yoki sertifikat rasmini "
            "yuborishingiz mumkin."
        ),
        "ask_media": (
            "📸 <b>Mahsulotingizning rasmlarini yoki videosini yuklang</b>\n"
            "🏗️ Xaridorlar mahsulotingizni yaxshiroq ko'rishlari uchun uning "
            "sifatli va aniq tasvirlarini yuboring.\n"
            "📷 <b>Rasm:</b> kamida {min_photos} ta mahsulot rasmi yuborilishi shart.\n"
            "🎥 <b>Video:</b> xohlasangiz, rasmlar o'rniga mahsulotingiz aks etgan "
            "videoni yuborishingiz mumkin.\n"
            "⚠️ Rasmlar yoki video aniq, sifatli va aynan sotilayotgan mahsulotga "
            "tegishli bo'lishi kerak.\n\n"
            "👇 Rasmlarni yuboring (hammasini yuborgach «Tayyor» tugmasi chiqadi) "
            "yoki bitta video yuboring."
        ),
        "ask_quantity": (
            "📦 <b>Mahsulotingizdan qancha miqdorda mavjud?</b>\n"
            "🏗️ Sotuvga taklif qilayotgan qurilish materialingizning hozirgi mavjud "
            "miqdorini va o'lchov birligini kiriting.\n"
            "📝 Misol: 50 tonna sement, 10 000 dona g'isht yoki 2 500 m² penoplast.\n"
            "ℹ️ Iltimos, xaridorlar uchun aniq va dolzarb miqdorni ko'rsating."
        ),
        "ask_delivery": (
            "🚚 <b>Yetkazib berish xizmati qanday amalga oshiriladi?</b>\n"
            "📦 Xaridor mahsulotni qanday usulda yetkazib olishini tanlang. Iltimos, "
            "buyurtma bo'yicha yetkazib berish shartlariga mos variantni belgilang."
        ),
        "ask_region": (
            "📍 <b>Mahsulotingiz joylashgan hududni kiriting</b>\n"
            "🏗️ Mahsulotingiz ayni vaqtda qaysi viloyat, shahar yoki tumanda "
            "joylashganini ko'rsating. Bu xaridorlarga mahsulotning joylashuvini "
            "aniqlash va yetkazib berishni rejalashtirishda yordam beradi.\n"
            "📝 Misol: Toshkent shahri, Chilonzor tumani yoki Toshkent viloyati, "
            "Zangiota tumani.\n"
            "👇 Iltimos, mahsulotingiz joylashgan hududni aniq kiriting."
        ),
        "ask_phone": (
            "📞 <b>Bog'lanish uchun telefon raqamingizni kiriting</b>\n"
            "Xaridorlar siz bilan bog'lanishi uchun faol telefon raqamingizni yozing.\n"
            "Masalan: +998 90 123 45 67"
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
        "need_button": "👆 Iltimos, quyidagi tugmalardan birini tanlang:",
        # --- tasdiqlash ---
        "confirm_header": (
            "✅ <b>E'loningiz qabul qilindi!</b>\n"
            "🎉 KARKAZ platformasiga e'lon joylashtirish jarayoni yakunlandi. "
            "E'loningiz moderator tomonidan ko'rib chiqilmoqda.\n"
            "🔎 Moderator e'loningizni tekshiradi va belgilangan talablarga "
            "muvofiqligini baholaydi. Tasdiqlanganidan so'ng e'loningiz platformada "
            "joylashtiriladi.\n"
            "📋 Kiritilgan ma'lumotlarni tekshirib chiqing. Barchasi to'g'ri bo'lsa, "
            "tasdiqlang yoki kerakli o'zgartirishlarni kiriting."
        ),
        "edit_restart": "✏️ Yaxshi, ma'lumotlarni boshidan qayta kiritamiz.",
        "final": (
            "✅ <b>E'loningiz qabul qilindi!</b>\n"
            "🎉 E'loningiz muvaffaqiyatli tasdiqlandi va hozirda KARKAZ Telegram "
            "kanaliga joylashtirilmoqda.\n"
            "🏗️ KARKAZ — qurilish materiallari savdosida ishonchli hamkoringiz! 🤝"
        ),
        "cancelled": "❌ Jarayon bekor qilindi. Qaytadan boshlash uchun /start bosing.",
    },
    "ru": {
        "ask_activity": (
            "🏢 <b>Пожалуйста, выберите вид деятельности!</b>\n"
            "🤝 Чтобы продолжить размещение объявления на платформе KARKAZ, "
            "выберите один из вариантов:\n\n"
            "🏛️ <b>Юридическое лицо</b> — предприниматель, действующий от имени "
            "предприятия, фирмы или организации.\n"
            "👤 <b>Физическое лицо</b> — лицо, продающее товар или размещающее "
            "объявление от своего имени."
        ),
        "ask_role": (
            "🏭 <b>В каком качестве вы осуществляете деятельность?</b>\n"
            "📦 Чтобы разместить товар на платформе KARKAZ, выберите один из "
            "вариантов:\n\n"
            "🏭 <b>Производитель</b> — вы самостоятельно производите товар.\n"
            "🤝 <b>Дилер</b> — вы приобретаете товар у производителей или "
            "поставщиков и продаёте покупателям."
        ),
        "ask_org": (
            "🏢 <b>Введите название вашей организации</b>\n\n"
            "Укажите название вашего предприятия, компании или торговой деятельности.\n"
            "Например: ООО «Tashkent Build Trade»"
        ),
        "ask_brand": (
            "🏷️ <b>Укажите бренд и марку товара</b>\n"
            "📌 Укажите бренд производителя, марку и модель строительного материала.\n"
            "Пример: цемент марки М400, производитель — Qizilqumsement."
        ),
        "ask_description": (
            "📝 <b>Введите подробную информацию о товаре</b>\n"
            "📦 Опишите, для чего используется товар, его размеры, состав и "
            "технические характеристики — не менее {min} и не более {max} слов.\n"
            "ℹ️ Информация должна быть точной и понятной. Это поможет покупателям "
            "лучше понять товар и сделать правильный выбор."
        ),
        "ask_price": (
            "🧱 <b>Укажите цену строительного материала</b>\n"
            "Укажите цену выставляемого на продажу товара и единицу измерения.\n"
            "Например: 1 тонна цемента — 850 000 сум или 1 штука кирпича — 1 200 сум."
        ),
        "ask_certificate": (
            "📜 <b>Укажите номер стандарта или сертификата товара</b>\n"
            "🏗️ Укажите номер стандарта (ГОСТ, O'z DSt и др.) или сертификата "
            "соответствия на ваш товар.\n"
            "📝 Пример: ГОСТ 31108-2020 или номер сертификата: UZ.SMT.12345.\n"
            "ℹ️ Если на товар нет сертификата или стандарта, напишите «Отсутствует».\n\n"
            "📷 Вы можете написать номер текстом или отправить фото сертификата."
        ),
        "ask_media": (
            "📸 <b>Загрузите фото или видео вашего товара</b>\n"
            "🏗️ Чтобы покупатели лучше рассмотрели ваш товар, отправьте "
            "качественные и чёткие изображения.\n"
            "📷 <b>Фото:</b> необходимо отправить не менее {min_photos} фотографий товара.\n"
            "🎥 <b>Видео:</b> при желании вместо фото вы можете отправить видео с "
            "вашим товаром.\n"
            "⚠️ Фото или видео должны быть чёткими, качественными и относиться "
            "именно к продаваемому товару.\n\n"
            "👇 Отправьте фото (после отправки всех появится кнопка «Готово») или "
            "отправьте одно видео."
        ),
        "ask_quantity": (
            "📦 <b>Какое количество товара у вас в наличии?</b>\n"
            "🏗️ Укажите текущее наличное количество предлагаемого к продаже "
            "строительного материала и единицу измерения.\n"
            "📝 Пример: 50 тонн цемента, 10 000 штук кирпича или 2 500 м² пеноплэкса.\n"
            "ℹ️ Пожалуйста, укажите точное и актуальное количество для покупателей."
        ),
        "ask_delivery": (
            "🚚 <b>Как осуществляется доставка?</b>\n"
            "📦 Выберите, каким способом покупатель получит товар. Пожалуйста, "
            "отметьте вариант, соответствующий условиям доставки по заказу."
        ),
        "ask_region": (
            "📍 <b>Укажите регион, где находится ваш товар</b>\n"
            "🏗️ Укажите, в какой области, городе или районе сейчас находится ваш "
            "товар. Это поможет покупателям определить местонахождение товара и "
            "спланировать доставку.\n"
            "📝 Пример: город Ташкент, Чиланзарский район или Ташкентская область, "
            "Зангиатинский район.\n"
            "👇 Пожалуйста, точно укажите регион, где находится ваш товар."
        ),
        "ask_phone": (
            "📞 <b>Введите номер телефона для связи</b>\n"
            "Укажите ваш действующий номер телефона, чтобы покупатели могли с вами "
            "связаться.\n"
            "Например: +998 90 123 45 67"
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
        "need_button": "👆 Пожалуйста, выберите один из вариантов ниже:",
        "confirm_header": (
            "✅ <b>Ваше объявление принято!</b>\n"
            "🎉 Процесс размещения объявления на платформе KARKAZ завершён. Ваше "
            "объявление рассматривается модератором.\n"
            "🔎 Модератор проверит ваше объявление и оценит его соответствие "
            "установленным требованиям. После одобрения объявление будет размещено "
            "на платформе.\n"
            "📋 Проверьте введённые данные. Если всё верно — подтвердите или внесите "
            "необходимые изменения."
        ),
        "edit_restart": "✏️ Хорошо, введём данные заново.",
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
        "role": {"producer": "🏭 Ishlab chiqaruvchi", "dealer": "🤝 Diler"},
        "delivery": {
            "buyer": "🚛 Xaridor hisobidan",
            "included": "📦 Narxga kiritilgan",
            "contract": "🤝 Shartnoma asosida",
        },
        "done": "✅ Tayyor",
        "confirm_yes": "✅ Ha, tasdiqlayman",
        "confirm_edit": "✏️ O'zgartirish kiritaman",
        "new_post": "📢 Yana e'lon joylash",
    },
    "ru": {
        "activity": {"legal": "🏛️ Юридическое лицо", "individual": "👤 Физическое лицо"},
        "role": {"producer": "🏭 Производитель", "dealer": "🤝 Дилер"},
        "delivery": {
            "buyer": "🚛 За счёт покупателя",
            "included": "📦 Включена в цену",
            "contract": "🤝 По договору",
        },
        "done": "✅ Готово",
        "confirm_yes": "✅ Да, подтверждаю",
        "confirm_edit": "✏️ Внести изменения",
        "new_post": "📢 Разместить ещё объявление",
    },
}
 
SUMMARY = {
    "uz": {
        "title": "📋 <b>Sizning e'loningiz:</b>",
        "activity": "🏢 Faoliyat turi",
        "role": "🏭 Faoliyat sifati",
        "org": "🏢 Tashkilot",
        "brand": "🏷️ Brend va marka",
        "description": "📝 Ma'lumot",
        "price": "🧱 Narxi",
        "certificate": "📜 Standart/sertifikat",
        "media": "📸 Rasm/video",
        "quantity": "📦 Miqdori",
        "delivery": "🚚 Yetkazib berish",
        "region": "📍 Hudud",
        "phone": "📞 Telefon",
        "photo_attached": "📷 rasm biriktirilgan",
        "photos": "{n} ta rasm",
        "video": "video",
    },
    "ru": {
        "title": "📋 <b>Ваше объявление:</b>",
        "activity": "🏢 Вид деятельности",
        "role": "🏭 Статус",
        "org": "🏢 Организация",
        "brand": "🏷️ Бренд и марка",
        "description": "📝 Описание",
        "price": "🧱 Цена",
        "certificate": "📜 Стандарт/сертификат",
        "media": "📸 Фото/видео",
        "quantity": "📦 Количество",
        "delivery": "🚚 Доставка",
        "region": "📍 Регион",
        "phone": "📞 Телефон",
        "photo_attached": "📷 фото приложено",
        "photos": "{n} фото",
        "video": "видео",
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
 
 
def options_kb(lang: str, group: str, prefix: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"{prefix}:{code}")]
        for code, label in LABELS[lang][group].items()
    ]
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
 
 
async def send_long(send, text: str, reply_markup=None) -> None:
    chunks = split_text(text)
    for i, chunk in enumerate(chunks):
        await send(chunk, reply_markup=reply_markup if i == len(chunks) - 1 else None)
 
 
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
    Form.org_name.state: "ask_org",
    Form.brand.state: "ask_brand",
    Form.description.state: "ask_description",
    Form.price.state: "ask_price",
    Form.certificate.state: "ask_certificate",
    Form.media.state: "ask_media",
    Form.quantity.state: "ask_quantity",
    Form.region.state: "ask_region",
    Form.phone.state: "ask_phone",
}
 
 
async def ask(target: Message, state: FSMContext, step: State, lang: str) -> None:
    """Berilgan bosqichga o'tkazadi va shu bosqich savolini yuboradi."""
    await state.set_state(step)
    key = step.state
    if key == Form.language.state:
        await target.answer(ASK_LANGUAGE, reply_markup=language_kb())
    elif key == Form.activity.state:
        await target.answer(T(lang, "ask_activity"), reply_markup=options_kb(lang, "activity", "act"))
    elif key == Form.role.state:
        await target.answer(T(lang, "ask_role"), reply_markup=options_kb(lang, "role", "role"))
    elif key == Form.delivery.state:
        await target.answer(T(lang, "ask_delivery"), reply_markup=options_kb(lang, "delivery", "deliv"))
    else:
        await target.answer(T(lang, TEXT_KEYS[key]))
 
 
def media_summary(data: dict, lang: str) -> str:
    S = SUMMARY[lang]
    parts = []
    if data.get("photos"):
        parts.append(S["photos"].format(n=len(data["photos"])))
    if data.get("video"):
        parts.append(S["video"])
    return " + ".join(parts) or "—"
 
 
def cert_summary(data: dict, lang: str) -> str:
    parts = []
    if data.get("cert_text"):
        parts.append(esc(data["cert_text"]))
    if data.get("cert_photo"):
        parts.append(SUMMARY[lang]["photo_attached"])
    return " + ".join(parts) or "—"
 
 
def build_summary(data: dict, lang: str) -> str:
    S, lab = SUMMARY[lang], LABELS[lang]
    return "\n".join(
        [
            S["title"],
            "",
            f"{S['activity']}: {lab['activity'][data['activity']]}",
            f"{S['role']}: {lab['role'][data['role']]}",
            f"{S['org']}: {esc(data['org_name'])}",
            f"{S['brand']}: {esc(data['brand'])}",
            f"{S['description']}: {esc(data['description'])}",
            f"{S['price']}: {esc(data['price'])}",
            f"{S['certificate']}: {cert_summary(data, lang)}",
            f"{S['media']}: {media_summary(data, lang)}",
            f"{S['quantity']}: {esc(data['quantity'])}",
            f"{S['delivery']}: {lab['delivery'][data['delivery']]}",
            f"{S['region']}: {esc(data['region'])}",
            f"{S['phone']}: {esc(data['phone'])}",
        ]
    )
 
 
def build_admin_text(data: dict, user) -> str:
    """Admin uchun ariza matni (doim o'zbek tilida)."""
    S, lab = SUMMARY["uz"], LABELS["uz"]
    username = f"@{user.username}" if user.username else "username yo'q"
    return "\n".join(
        [
            "🆕 <b>YANGI E'LON</b>",
            f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"🌐 E'lon tili: {data['lang'].upper()}",
            "",
            f"{S['activity']}: {lab['activity'][data['activity']]}",
            f"{S['role']}: {lab['role'][data['role']]}",
            f"{S['org']}: {esc(data['org_name'])}",
            f"{S['brand']}: {esc(data['brand'])}",
            f"{S['description']}: {esc(data['description'])}",
            f"{S['price']}: {esc(data['price'])}",
            f"{S['certificate']}: {cert_summary(data, 'uz')}",
            f"{S['media']}: {media_summary(data, 'uz')}",
            f"{S['quantity']}: {esc(data['quantity'])}",
            f"{S['delivery']}: {lab['delivery'][data['delivery']]}",
            f"{S['region']}: {esc(data['region'])}",
            f"{S['phone']}: {esc(data['phone'])}",
            "",
            f"👤 Yuboruvchi: {esc(user.full_name)} | {esc(username)} | ID: <code>{user.id}</code>",
        ]
    )
 
 
async def deliver_to_admin(data: dict, user) -> None:
    """Arizani (matn + rasm/video + sertifikat rasmi) adminga yuboradi."""
    try:
        await send_long(
            lambda text, reply_markup=None: bot.send_message(ADMIN_ID, text),
            build_admin_text(data, user),
        )
 
        photos = data.get("photos", [])
        for i in range(0, len(photos), 10):
            chunk = photos[i:i + 10]
            if len(chunk) == 1:
                await bot.send_photo(ADMIN_ID, chunk[0])
            else:
                await bot.send_media_group(ADMIN_ID, [InputMediaPhoto(media=f) for f in chunk])
 
        if data.get("video"):
            await bot.send_video(ADMIN_ID, data["video"], caption="🎥 Video")
 
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
        lab["role"][data["role"]],
        data["org_name"],
        data["brand"],
        data["description"],
        data["price"],
        cert,
        len(data.get("photos", [])),
        "Ha" if data.get("video") else "Yo'q",
        data["quantity"],
        lab["delivery"][data["delivery"]],
        data["region"],
        data["phone"],
        username,
        str(user.id),
    ]
    try:
        await asyncio.to_thread(_sheet.append_row, row, value_input_option="RAW")
    except Exception as e:
        logger.error("Google Sheetsga yozishda xatolik: %s", e)
 
 
async def show_confirmation(target: Message, state: FSMContext, lang: str) -> None:
    data = await state.get_data()
    await state.set_state(Form.confirm)
    await target.answer(T(lang, "confirm_header"))
    await send_long(target.answer, build_summary(data, lang), reply_markup=confirm_kb(lang))
 
 
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
    await ask(callback.message, state, Form.role, lang)
    await callback.answer()
 
 
@router.callback_query(Form.role, F.data.startswith("role:"))
async def choose_role(callback: CallbackQuery, state: FSMContext):
    lang = (await state.get_data())["lang"]
    code = callback.data.split(":", 1)[1]
    if code not in LABELS[lang]["role"]:
        await callback.answer()
        return
    await state.update_data(role=code)
    await mark_chosen(callback, LABELS[lang]["role"][code])
    await ask(callback.message, state, Form.org_name, lang)
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
    await ask(callback.message, state, Form.region, lang)
    await callback.answer()
 
 
# ---------------------------------------------------------------------------
# MATNLI BOSQICHLAR
# ---------------------------------------------------------------------------
TEXT_FILTER = F.text & ~F.text.startswith("/")
 
# holat -> (saqlanadigan maydon, keyingi bosqich)
SHORT_TEXT_STEPS = {
    Form.org_name.state: ("org_name", Form.brand),
    Form.brand.state: ("brand", Form.description),
    Form.price.state: ("price", Form.certificate),
    Form.quantity.state: ("quantity", Form.delivery),
    Form.region.state: ("region", Form.phone),
}
 
 
@router.message(
    StateFilter(Form.org_name, Form.brand, Form.price, Form.quantity, Form.region),
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
    await ask(message, state, next_step, lang)
 
 
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
    await ask(message, state, Form.price, lang)
 
 
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
    await ask(message, state, Form.media, lang)
 
 
@router.message(Form.certificate, F.photo)
async def get_certificate_photo(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    caption = re.sub(r"\s+", " ", message.caption or "").strip()[:MAX_SHORT_CHARS]
    await state.update_data(cert_photo=message.photo[-1].file_id, cert_text=caption or None)
    await ask(message, state, Form.media, lang)
 
 
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
    await ask(message, state, Form.quantity, lang)
 
 
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
    await ask(callback.message, state, Form.quantity, lang)
    await callback.answer()
 
 
@router.message(StateFilter(Form.media))
async def media_invalid(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    await message.answer(T(lang, "media_invalid"))
 
 
# --- telefon ---
@router.message(Form.phone, F.contact)
async def get_phone_contact(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    await state.update_data(phone=message.contact.phone_number)
    await show_confirmation(message, state, lang)
 
 
@router.message(Form.phone, TEXT_FILTER)
async def get_phone(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    text = message.text.strip()
    if not is_valid_phone(text):
        await message.answer(T(lang, "phone_invalid"))
        return
    await state.update_data(phone=text)
    await show_confirmation(message, state, lang)
 
 
# ---------------------------------------------------------------------------
# TASDIQLASH
# ---------------------------------------------------------------------------
@router.callback_query(Form.confirm, F.data == "confirm:edit")
async def confirm_edit(callback: CallbackQuery, state: FSMContext):
    lang = (await state.get_data())["lang"]
    await state.set_data({"lang": lang})  # tilni saqlab, qolganini tozalaymiz
    await remove_buttons(callback)
    await callback.message.answer(T(lang, "edit_restart"))
    await ask(callback.message, state, Form.activity, lang)
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
@router.message(StateFilter(Form.language, Form.activity, Form.role, Form.delivery))
async def button_expected(message: Message, state: FSMContext):
    current = await state.get_state()
    lang = (await state.get_data()).get("lang", "uz")
    step = {
        Form.language.state: Form.language,
        Form.activity.state: Form.activity,
        Form.role.state: Form.role,
        Form.delivery.state: Form.delivery,
    }[current]
    await ask(message, state, step, lang)
 
 
@router.message(StateFilter(Form.confirm))
async def confirm_expected(message: Message, state: FSMContext):
    lang = (await state.get_data())["lang"]
    await message.answer(T(lang, "need_button"))
    await send_long(message.answer, build_summary(await state.get_data(), lang), reply_markup=confirm_kb(lang))
 
 
# ---------------------------------------------------------------------------
# MATN KUTILAYOTGAN BOSQICHLARDA MATN BO'LMAGAN NARSA YUBORILSA
# ---------------------------------------------------------------------------
@router.message(
    StateFilter(
        Form.org_name, Form.brand, Form.description, Form.price,
        Form.quantity, Form.region, Form.phone,
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
 
