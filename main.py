import logging
import re
import asyncio
import os
import requests
from datetime import datetime
from PIL import Image, ImageChops, ImageStat
import cv2
import numpy as np
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler
from telethon import TelegramClient
from telethon.sessions import StringSession

# -------------------- إعدادات الحسابات --------------------
BOT_TOKEN = '8520440293:AAHxlEGixgF2uOdLAgbpB6S5uFWgXrwAHko'
CHANNEL_USERNAME = '@Serianumber99'
GROUP_ID = -1002588398038

# Telethon (صامت، يستخدم فقط لقراءة القناة وبناء الكاش)
API_ID = 26604893
API_HASH = 'b4dad6237531036f1a4bb2580e4985b1'
STRING_SESSION = '1BJWap1wBuzwi_AQfbsYmVPJS4VjOwS-QqQuPQFhgRHx2ZcA65CIwl0TGqPOZjGfFqCfCIs5ED2dYi1MpA3mweKcRXtKCCL94j_geb1d9l5a54JPAtRNTrRhm9wQxBCVOh0MF-u5avJWWU_YI1VwHUC8g4dOGlHwiu10lp0F9DsMpYzzdBS5DCjeEP2VllZfgnr1dSWBGYN_yp-jdZrlcxZRNHCwcs276Mu7U30qp9rj0sP31S4WBwZfP3U7FxLuEgj-ZVTVrnsCRGkGEM-4hQzyLqbPM9GpdPX0PuEtc-eqlUjn_e2uvASEAU6yuk98RfH1xgKT2pdbJvjY2HLVDo2O-ymQ-s0U='

OCR_API_KEY = 'K89276173888957'

# قائمة أسماء مستخدمين إضافيين (احتياطي)
ADMIN_USERNAMES = [
    "ahsvsjsv", "OQO_e1", "H4_OT", "Q_12_T", "h896556",
    "murtaza_said", "c1c_2", "BOTrika_22", "oaa_c", "mwsa_20",
    "feloo9", "yas_r7", "Hu2009", "PHT_10", "l_7yk", "levil_8"
]

# -------------------- الكاش (من القناة) --------------------
CACHE = {
    "users": {},   # {username: {"serial": serial, "date": datetime, "msg_id": int}}
    "serials": {}, # {serial: username}
    "loaded": False,
    "last_msg_id": 0
}

telethon_client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# -------------------- دوال فحص الميديا --------------------
def extract_frame_from_video(video_path: str, output_image_path: str) -> bool:
    """استخراج أول إطار من الفيديو باستخدام OpenCV"""
    try:
        cap = cv2.VideoCapture(video_path)
        ret, frame = cap.read()
        if ret:
            cv2.imwrite(output_image_path, frame)
            cap.release()
            return True
        cap.release()
        return False
    except Exception:
        return False

def get_tamper_score(image_path: str) -> float:
    try:
        original = Image.open(image_path).convert('RGB')
        resaved = 'temp_ela_check.jpg'
        original.save(resaved, 'JPEG', quality=90)
        resaved_img = Image.open(resaved)
        diff = ImageChops.difference(original, resaved_img)
        stat = ImageStat.Stat(diff)
        if os.path.exists(resaved):
            os.remove(resaved)
        return sum(stat.mean)
    except Exception:
        return 0.0

def get_ocr_text(image_path: str) -> str:
    try:
        with open(image_path, 'rb') as f:
            response = requests.post(
                'https://api.ocr.space/parse/image',
                files={image_path: f},
                data={'apikey': OCR_API_KEY, 'language': 'eng', 'isOverlayRequired': False},
                timeout=30
            )
        result = response.json()
        if result.get('ParsedResults'):
            return result['ParsedResults'][0].get('ParsedText', '').lower()
        return ""
    except Exception:
        return ""

async def check_media_authenticity(file_path: str, expected_serial: str, is_video: bool = False) -> str:
    if is_video:
        frame_path = "temp_video_frame.jpg"
        if not extract_frame_from_video(file_path, frame_path):
            return "⚠️ **فيديو:** تعذر استخراج إطار للفحص (تأكد من مكتبة opencv-python-headless)"
        image_path = frame_path
    else:
        image_path = file_path

    tamper = get_tamper_score(image_path)
    ocr_text = get_ocr_text(image_path).replace(" ", "")

    if is_video and os.path.exists(frame_path):
        os.remove(frame_path)

    if tamper > 15:
        return "⚠️ **مونتاج / فوتوشوب:** تم كشف تلاعب في الميديا!"
    elif expected_serial.lower() not in ocr_text:
        return f"❌ **رقم غير مطابق:** السيريال `{expected_serial}` غير موجود في الميديا!"
    else:
        return "✅ **حقيقي:** الميديا سليمة والرقم مطابق."

# -------------------- دوال فحص التشابه (LCS) --------------------
def longest_consecutive_substring(s1: str, s2: str) -> int:
    m = [[0] * (len(s2) + 1) for _ in range(len(s1) + 1)]
    longest = 0
    for i in range(1, len(s1) + 1):
        for j in range(1, len(s2) + 1):
            if s1[i-1] == s2[j-1]:
                m[i][j] = m[i-1][j-1] + 1
                longest = max(longest, m[i][j])
            else:
                m[i][j] = 0
    return longest

def longest_common_subsequence(s1: str, s2: str) -> int:
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i-1] == s2[j-1]:
                dp[i][j] = dp[i-1][j-1] + 1
            else:
                dp[i][j] = max(dp[i-1][j], dp[i][j-1])
    return dp[m][n]

def check_serial_similarity(new_serial: str, max_warnings=5) -> tuple:
    """تعيد (قائمة التحذيرات المختصرة، العدد الإجمالي)"""
    warnings = []
    total = 0
    new_serial_lower = new_serial.lower()
    for old_serial, old_user in CACHE["serials"].items():
        old_serial_lower = old_serial.lower()
        if new_serial_lower == old_serial_lower:
            total += 1
            if len(warnings) < max_warnings:
                warnings.append(f"⚠️ **تطابق تام** مع `{old_serial}` لـ @{old_user}")
            continue
        consecutive = longest_consecutive_substring(new_serial_lower, old_serial_lower)
        lcs_len = longest_common_subsequence(new_serial_lower, old_serial_lower)
        if consecutive >= 3:
            total += 1
            if len(warnings) < max_warnings:
                warnings.append(f"⚠️ **تشابه متتالي** ({consecutive} حروف) مع `{old_serial}` لـ @{old_user}")
        elif lcs_len >= 5:
            total += 1
            if len(warnings) < max_warnings:
                warnings.append(f"⚠️ **تشابه غير متتالي** ({lcs_len} حروف) مع `{old_serial}` لـ @{old_user}")
    return warnings, total

# -------------------- بناء الكاش باستخدام Telethon --------------------
async def build_cache_with_telethon():
    if CACHE["loaded"]:
        return
    print("⏳ جاري فهرسة جميع رسائل القناة عبر Telethon...")
    count = 0
    last_id = 0
    try:
        async for message in telethon_client.iter_messages(CHANNEL_USERNAME, reverse=True):
            last_id = message.id
            text = (message.text or "").lower()
            date = message.date.replace(tzinfo=None)
            # البحث عن صيغ مثل [@user | serial] أو @user | serial
            matches = re.findall(r'@([\w\d_]+)\s*[|/-]\s*([\w\d_/]+)', text)
            for user, serial in matches:
                user_full = f"@{user}"
                CACHE["users"][user_full] = {"serial": serial, "date": date, "msg_id": message.id}
                CACHE["serials"][serial] = user_full
                count += 1
            await asyncio.sleep(0.05)
    except Exception as e:
        logging.error(f"خطأ في جلب الرسائل: {e}")
    CACHE["loaded"] = True
    CACHE["last_msg_id"] = last_id
    print(f"✅ تم تحميل الكاش: {count} لاعب من {last_id} رسالة.")

async def periodic_cache_updater():
    while True:
        await asyncio.sleep(60)
        if not CACHE["loaded"]:
            continue
        try:
            last_id = CACHE["last_msg_id"]
            new_msgs = []
            async for msg in telethon_client.iter_messages(CHANNEL_USERNAME, min_id=last_id, reverse=True):
                if msg.id > last_id:
                    new_msgs.append(msg)
            if new_msgs:
                print(f"🔄 تحديث الكاش: {len(new_msgs)} رسائل جديدة")
                for msg in new_msgs:
                    text = (msg.text or "").lower()
                    date = msg.date.replace(tzinfo=None)
                    matches = re.findall(r'@([\w\d_]+)\s*[|/-]\s*([\w\d_/]+)', text)
                    for user, serial in matches:
                        user_full = f"@{user}"
                        CACHE["users"][user_full] = {"serial": serial, "date": date, "msg_id": msg.id}
                        CACHE["serials"][serial] = user_full
                    if msg.id > CACHE["last_msg_id"]:
                        CACHE["last_msg_id"] = msg.id
                print("✅ تم تحديث الكاش.")
        except Exception as e:
            logging.error(f"خطأ في التحديث الدوري: {e}")

# -------------------- دوال البوت (python-telegram-bot) --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 بوت الفحص الذكي جاهز!\nأرسل صورة أو فيديو مع كابشن:\n`@username | serial`")

async def is_admin(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ('administrator', 'creator'):
            return True
    except Exception:
        pass
    user = await context.bot.get_chat(user_id)
    if user.username and user.username.lower() in [u.lower() for u in ADMIN_USERNAMES]:
        return True
    return False

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CACHE["loaded"]:
        await update.message.reply_text("⏳ جاري تحديث الأرشيف، حاول بعد لحظات.")
        return

    if not (update.message.photo or update.message.video) or not update.message.caption:
        await update.message.reply_text("❌ أرفق صورة أو فيديو مع كابشن: `@user | serial`")
        return

    raw_input = update.message.caption.strip()
    match = re.match(r"^(@[\w\d_]+)\s*[|/-]?\s*([\w\d_/]+)$", raw_input)
    if not match:
        await update.message.reply_text("❌ تنسيق خاطئ! مثال: `@ahmed | ABC123`")
        return

    new_user = match.group(1).lower()
    new_serial = match.group(2).lower()

    user_data = CACHE["users"].get(new_user)
    serial_owner = CACHE["serials"].get(new_serial)

    if user_data and user_data['serial'] == new_serial:
        await update.message.reply_text("⚠️ هذا اللاعب مسجل مسبقاً بنفس البيانات.")
        return

    action_type = "NEW"
    extra_info = "✅ لاعب جديد."

    if user_data:
        diff = datetime.utcnow() - user_data['date']
        if diff.days < 15:
            days_left = 15 - diff.days
            await update.message.reply_text(f"❌ تغيير التسلسلي كل 15 يوم فقط. متبقي {days_left} يوم.")
            return
        action_type = "CHANGE_SERIAL"
        extra_info = "🔄 تغيير تسلسلي (بعد 15 يوم)."
    elif serial_owner:
        action_type = "CHANGE_USER"
        extra_info = "🔄 تغيير يوزر لنفس الجهاز."

    progress = await update.message.reply_text("📥 جاري تحميل الميديا وفحصها...")
    media_file = None
    is_video = False
    if update.message.photo:
        media_file = await update.message.photo[-1].get_file()
    elif update.message.video:
        media_file = await update.message.video.get_file()
        is_video = True

    if not media_file:
        await progress.edit_text("❌ خطأ في تحميل الملف.")
        return

    ext = "mp4" if is_video else "jpg"
    file_path = f"temp_{update.message.chat_id}.{ext}"
    await media_file.download_to_drive(file_path)

    # فحص الميديا
    authenticity = await check_media_authenticity(file_path, new_serial, is_video)
    # فحص التشابه
    warnings, total_similar = check_serial_similarity(new_serial, max_warnings=5)
    similarity_text = "\n".join(warnings)
    if total_similar > len(warnings):
        similarity_text += f"\n⚠️ **و {total_similar - len(warnings)} تحذيرات أخرى**"
    if not warnings:
        similarity_text = "✅ لا يوجد تشابه مع أي سيريال مسجل."

    try:
        os.remove(file_path)
    except:
        pass

    await progress.delete()

    keyboard = [[
        InlineKeyboardButton("✅ قبول", callback_data=f"ok_{update.message.chat_id}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"no_{update.message.chat_id}")
    ]]

    caption = (
        f"📝 **طلب فحص:**\n{extra_info}\n"
        f"👤 اليوزر: {new_user}\n🔢 السيريال: {new_serial}\n"
        f"🆔 ID: `{update.message.chat_id}`\n\n"
        f"🔍 **فحص الميديا:**\n{authenticity}\n\n"
        f"🔁 **فحص التشابه (إجمالي {total_similar}):**\n{similarity_text}"
    )

    # إرسال الطلب إلى مجموعة الإدارة
    if update.message.photo:
        await context.bot.send_photo(GROUP_ID, update.message.photo[-1].file_id, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_video(GROUP_ID, update.message.video.file_id, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard))

    await update.message.reply_text("✅ تم إرسال طلبك للمراجعة.")
    context.bot_data[f"data_{update.message.chat_id}"] = {"u": new_user, "s": new_serial, "type": action_type}

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await is_admin(query.from_user.id, GROUP_ID, context):
        await query.answer("ليس لديك صلاحية!", show_alert=True)
        return

    action, uid = query.data.split("_")
    user_info = context.bot_data.get(f"data_{uid}")
    if not user_info:
        await query.answer("بيانات الطلب منتهية.")
        return

    if action == "ok":
        # تحديث الكاش وإضافة الزوج الجديد (بدون تعديل رسالة القناة، فقط الكاش)
        CACHE["users"][user_info['u']] = {"serial": user_info['s'], "date": datetime.utcnow(), "msg_id": 0}
        CACHE["serials"][user_info['s']] = user_info['u']
        await query.message.delete()
        await context.bot.send_message(GROUP_ID, f"✅ تم قبول {user_info['u']} بواسطة @{query.from_user.username}")
        await context.bot.send_message(int(uid), "✅ تم قبول طلبك وتحديث بياناتك.")
    elif action == "no":
        await context.bot.send_message(GROUP_ID, f"الرد على هذه الرسالة بسبب الرفض لـ `{uid}`:", reply_markup=ForceReply(selective=True))
        await query.answer("أدخل سبب الرفض")

async def handle_reject_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != GROUP_ID or not update.message.reply_to_message:
        return
    if "سبب الرفض" in update.message.reply_to_message.text:
        match = re.search(r"`(\d+)`", update.message.reply_to_message.text)
        if match:
            uid = match.group(1)
            await context.bot.send_message(int(uid), f"❌ تم رفض طلبك.\n**السبب:** {update.message.text}")
            await update.message.reply_text("✅ تم إبلاغ اللاعب.")

# -------------------- بدء التشغيل --------------------
async def main():
    # بدء Telethon (صامت)
    await telethon_client.start()
    print("✅ Telethon connected (silent mode)")

    # بناء الكاش من القناة
    await build_cache_with_telethon()
    asyncio.create_task(periodic_cache_updater())

    # بدء بوت Telegram
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.CAPTION, handle_registration))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, handle_reject_reply))

    print("🤖 البوت يعمل مع Telethon (تشابه + فيديو)...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
