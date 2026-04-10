import logging
import re
import asyncio
import os
import requests
import subprocess
from datetime import datetime
from PIL import Image, ImageChops, ImageStat
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler, Application

# -------------------- الإعدادات الأساسية --------------------
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = '8520440293:AAHxlEGixgF2uOdLAgbpB6S5uFWgXrwAHko'
CHANNEL_USERNAME = '@Serianumber99'
GROUP_ID = -1002588398038

ADMIN_USERNAMES = [
    "ahsvsjsv", "OQO_e1", "H4_OT", "Q_12_T", "h896556",
    "murtaza_said", "c1c_2", "BOTrika_22", "oaa_c", "mwsa_20",
    "feloo9", "yas_r7", "Hu2009", "PHT_10", "l_7yk", "levil_8"
]

OCR_API_KEY = 'K89276173888957'

CACHE = {
    "users": {},   # {username: {"serial": serial, "date": datetime, "msg_id": int}}
    "serials": {}, # {serial: username}
    "loaded": False,
    "last_checked_msg_id": 0
}

# -------------------- دوال فحص الصور والفيديو --------------------
def extract_frame_from_video(video_path: str, output_image_path: str) -> bool:
    """استخراج أول إطار من الفيديو باستخدام ffmpeg (يجب تثبيته على السيرفر)"""
    try:
        cmd = ['ffmpeg', '-i', video_path, '-frames:v', '1', output_image_path, '-y']
        subprocess.run(cmd, check=True, capture_output=True)
        return os.path.exists(output_image_path)
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
    """فحص الصورة أو الفيديو (باستخراج إطار أول)"""
    if is_video:
        frame_path = "temp_video_frame.jpg"
        if not extract_frame_from_video(file_path, frame_path):
            return "⚠️ **فيديو:** تعذر استخراج إطار للفحص (يجب تثبيت ffmpeg على السيرفر)"
        image_path = frame_path
    else:
        image_path = file_path

    if not image_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tiff')):
        return "⚠️ **صورة غير مدعومة**"

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

def check_serial_similarity(new_serial: str) -> list:
    warnings = []
    new_serial_lower = new_serial.lower()
    for old_serial, old_user in CACHE["serials"].items():
        old_serial_lower = old_serial.lower()
        if new_serial_lower == old_serial_lower:
            warnings.append(f"⚠️ **تطابق تام** مع السيريال `{old_serial}` الخاص بـ @{old_user}")
            continue
        consecutive = longest_consecutive_substring(new_serial_lower, old_serial_lower)
        lcs_len = longest_common_subsequence(new_serial_lower, old_serial_lower)
        if consecutive >= 3:
            warnings.append(f"⚠️ **تشابه متتالي** ({consecutive} حروف) مع `{old_serial}` الخاص بـ @{old_user}")
        elif lcs_len >= 5:
            warnings.append(f"⚠️ **تشابه غير متتالي** ({lcs_len} حروف) مع `{old_serial}` الخاص بـ @{old_user}")
    return warnings

# -------------------- بناء الكاش من كل رسائل القناة --------------------
async def build_full_cache(bot):
    """يجلب كل رسائل القناة من 1 إلى آخر معرف ويبني الكاش"""
    if CACHE["loaded"]:
        return

    print("⏳ جاري فهرسة جميع رسائل القناة...")
    # الحصول على آخر معرف رسالة في القناة
    try:
        chat = await bot.get_chat(CHANNEL_USERNAME)
        # لا يمكن معرفة آخر message_id مباشرة، لذا نرسل رسالة اختبار ثم نحذفها
        test_msg = await bot.send_message(CHANNEL_USERNAME, ".")
        last_id = test_msg.message_id
        await bot.delete_message(CHANNEL_USERNAME, last_id)
        last_id -= 1  # آخر رسالة حقيقية
    except Exception as e:
        logging.error(f"فشل الحصول على آخر ID: {e}")
        last_id = 500  # افتراضي

    count = 0
    # المرور من 1 إلى last_id
    for msg_id in range(1, last_id + 1):
        try:
            msg = await bot.forward_message(chat_id=GROUP_ID, from_chat_id=CHANNEL_USERNAME, message_id=msg_id)
            text = (msg.text or msg.caption or "").lower()
            date = (msg.forward_date or msg.date).replace(tzinfo=None)

            # استخراج الأزواج بالصيغة [@user | serial] أو @user | serial
            pattern = r'@([\w\d_]+)\s*[|/-]\s*([\w\d_/]+)'
            matches = re.findall(pattern, text)
            for user, serial in matches:
                user_full = f"@{user}"
                CACHE["users"][user_full] = {"serial": serial, "date": date, "msg_id": msg_id}
                CACHE["serials"][serial] = user_full
                count += 1

            await bot.delete_message(chat_id=GROUP_ID, message_id=msg.message_id)
            await asyncio.sleep(0.05)
        except Exception:
            continue

    CACHE["loaded"] = True
    CACHE["last_checked_msg_id"] = last_id
    print(f"✅ تم تحميل الكاش: {count} لاعب مفهرس من {last_id} رسالة.")

async def periodic_channel_updater(app: Application):
    """تحديث الكاش كل 60 ثانية بقراءة الرسائل الجديدة"""
    while True:
        await asyncio.sleep(60)
        if not CACHE["loaded"]:
            continue
        try:
            chat = await app.bot.get_chat(CHANNEL_USERNAME)
            test_msg = await app.bot.send_message(CHANNEL_USERNAME, ".")
            current_last = test_msg.message_id - 1
            await app.bot.delete_message(CHANNEL_USERNAME, test_msg.message_id)

            last_checked = CACHE["last_checked_msg_id"]
            if current_last > last_checked:
                print(f"🔄 تحديث الكاش: رسائل جديدة من {last_checked+1} إلى {current_last}")
                for msg_id in range(last_checked + 1, current_last + 1):
                    try:
                        msg = await app.bot.forward_message(chat_id=GROUP_ID, from_chat_id=CHANNEL_USERNAME, message_id=msg_id)
                        text = (msg.text or msg.caption or "").lower()
                        date = (msg.forward_date or msg.date).replace(tzinfo=None)
                        matches = re.findall(r'@([\w\d_]+)\s*[|/-]\s*([\w\d_/]+)', text)
                        for user, serial in matches:
                            user_full = f"@{user}"
                            CACHE["users"][user_full] = {"serial": serial, "date": date, "msg_id": msg_id}
                            CACHE["serials"][serial] = user_full
                        await app.bot.delete_message(chat_id=GROUP_ID, message_id=msg.message_id)
                        await asyncio.sleep(0.05)
                    except Exception:
                        continue
                CACHE["last_checked_msg_id"] = current_last
                print("✅ تم تحديث الكاش.")
        except Exception as e:
            logging.error(f"خطأ في تحديث الكاش الدوري: {e}")

async def post_init(application: Application):
    asyncio.create_task(build_full_cache(application.bot))
    asyncio.create_task(periodic_channel_updater(application))

# -------------------- أوامر البوت --------------------
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

    # تحميل الميديا
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
    similarity_warnings = check_serial_similarity(new_serial)
    similarity_text = "\n".join(similarity_warnings) if similarity_warnings else "✅ لا يوجد تشابه مع أي سيريال مسجل."

    # حذف الملف المؤقت
    try:
        os.remove(file_path)
    except:
        pass

    await progress.delete()

    # إرسال الطلب للمشرفين
    keyboard = [[
        InlineKeyboardButton("✅ قبول", callback_data=f"ok_{update.message.chat_id}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"no_{update.message.chat_id}")
    ]]

    caption = (
        f"📝 **طلب فحص:**\n{extra_info}\n"
        f"👤 اليوزر: {new_user}\n🔢 السيريال: {new_serial}\n"
        f"🆔 ID: `{update.message.chat_id}`\n\n"
        f"🔍 **فحص الميديا:**\n{authenticity}\n\n"
        f"🔁 **فحص التشابه:**\n{similarity_text}"
    )

    if update.message.photo:
        await context.bot.send_photo(GROUP_ID, update.message.photo[-1].file_id, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_video(GROUP_ID, update.message.video.file_id, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard))

    await update.message.reply_text("✅ تم إرسال طلبك للمراجعة.")
    context.bot_data[f"data_{update.message.chat_id}"] = {"u": new_user, "s": new_serial, "type": action_type}

# -------------------- معالجة القبول والرفض --------------------
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
        # إضافة أو تحديث في الكاش (يتم تعديل الرسالة الأصلية في القناة)
        # لتبسيط الكود سنقوم بإضافة الزوج إلى الكاش فقط (دون تعديل الرسالة القديمة)
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

# -------------------- تشغيل البوت --------------------
def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.CAPTION, handle_registration))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, handle_reject_reply))
    print("🤖 البوت يعمل مع فحص كامل للقناة والفيديو والتشابه...")
    app.run_polling()

if __name__ == '__main__':
    main()
