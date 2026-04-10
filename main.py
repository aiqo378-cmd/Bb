import logging
import re
import asyncio
import os
import requests
from datetime import datetime
from PIL import Image, ImageChops, ImageStat
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler, Application

# -------------------- الإعدادات الأساسية --------------------
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = '8520440293:AAHxlEGixgF2uOdLAgbpB6S5uFWgXrwAHko'
CHANNEL_USERNAME = '@Serianumber99'
LIST_MESSAGE_ID = 219                     # تم التعديل من 216 إلى 219
GROUP_ID = -1002588398038

ADMIN_USERNAMES = [
    "ahsvsjsv", "OQO_e1", "H4_OT", "Q_12_T", "h896556",
    "murtaza_said", "c1c_2", "BOTrika_22", "oaa_c", "mwsa_20",
    "feloo9", "yas_r7", "Hu2009", "PHT_10", "l_7yk", "levil_8"
]

OCR_API_KEY = 'K89276173888957'   # مفتاح OCR.space

CACHE = {
    "users": {},   # {username: {"serial": serial, "date": datetime, "msg_id": int}}
    "serials": {}, # {serial: username}
    "loaded": False
}

# -------------------- دوال فحص الصور --------------------
def get_tamper_score(image_path: str) -> float:
    """كشف المونتاج باستخدام Error Level Analysis (ELA)"""
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
    """استخراج النص من الصورة عبر OCR.space"""
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

async def check_media_authenticity(file_path: str, expected_serial: str) -> str:
    """
    فحص الصورة (أو الفيديو – يكتفي بالصورة المصغرة للفيديو).
    تعيد نص الحالة: ✅ حقيقي / ❌ رقم غير مطابق / ⚠️ مونتاج
    """
    # إذا كان الفيديو، نأخذ أول إطار له (يتطلب opencv أو استخراج صورة مصغرة)
    # للتبسيط: نكتفي بفحص الصور فقط، والفيديو يرسل بدون فحص آلي
    if not file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tiff')):
        return "⚠️ **فيديو:** لم يتم الفحص الآلي (يُفضل الفحص اليدوي)"

    tamper = get_tamper_score(file_path)
    ocr_text = get_ocr_text(file_path).replace(" ", "")

    if tamper > 15:
        return "⚠️ **مونتاج / فوتوشوب:** تم كشف تلاعب في الصورة!"
    elif expected_serial.lower() not in ocr_text:
        return f"❌ **رقم غير مطابق:** السيريال `{expected_serial}` غير موجود في الصورة!"
    else:
        return "✅ **حقيقي:** الصورة سليمة والرقم مطابق."

# -------------------- دوال فحص التشابه (LCS) --------------------
def longest_consecutive_substring(s1: str, s2: str) -> int:
    """أطول سلسلة متتالية مشتركة"""
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
    """أطول سلسلة غير متتالية مشتركة (LCS)"""
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
    """
    فحص التشابه بين السيريال الجديد وجميع السيريالات المخزنة.
    تعيد قائمة بالتحذيرات (نصوص).
    """
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

# -------------------- بناء الكاش (الأرشيف) --------------------
async def build_cache(bot):
    if CACHE["loaded"]:
        return
    count = 0
    print("⏳ بدأت عملية فحص الأرشيف...")
    for msg_id in range(1, LIST_MESSAGE_ID + 1):
        try:
            msg = await bot.forward_message(chat_id=GROUP_ID, from_chat_id=CHANNEL_USERNAME, message_id=msg_id)
            text = (msg.text or msg.caption or "").lower()
            date = (msg.forward_date or msg.date).replace(tzinfo=None)

            user_match = re.search(r"@[\w\d_]+", text)
            serial_match = re.search(r"([a-z0-9]{5,})", text)

            if user_match and serial_match:
                u = user_match.group(0)
                s = serial_match.group(0)
                CACHE["users"][u] = {"serial": s, "date": date, "msg_id": msg_id}
                CACHE["serials"][s] = u
                count += 1

            await bot.delete_message(chat_id=GROUP_ID, message_id=msg.message_id)
            await asyncio.sleep(0.05)
        except Exception:
            continue
    CACHE["loaded"] = True
    print(f"✅ تم تحميل الكاش: {count} لاعب مفهرس.")

async def post_init(application: Application):
    asyncio.create_task(build_cache(application.bot))

# -------------------- أوامر البوت --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 بوت الفحص الذكي جاهز للعمل!\nأرسل صورة أو فيديو مع كابشن بالشكل:\n`@username | serial`")

async def is_admin(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """التحقق إذا كان المستخدم أدمن في مجموعة الإدارة أو ضمن قائمة ADMIN_USERNAMES"""
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ('administrator', 'creator'):
            return True
    except Exception:
        pass
    # التحقق من قائمة أسماء المستخدمين الثابتة
    user = await context.bot.get_chat(user_id)
    if user.username and user.username.lower() in [u.lower() for u in ADMIN_USERNAMES]:
        return True
    return False

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CACHE["loaded"]:
        await update.message.reply_text("⏳ جاري تحديث بيانات الأرشيف.. حاول بعد لحظات.")
        return

    # التأكد من وجود وسائط (صورة أو فيديو) وكابشن
    if not (update.message.photo or update.message.video) or not update.message.caption:
        await update.message.reply_text("❌ يجب إرفاق صورة أو فيديو مع كابشن يحتوي على `@user | serial`")
        return

    raw_input = update.message.caption.strip()
    match = re.match(r"^(@[\w\d_]+)\s*[|/-]?\s*([\w\d_/]+)$", raw_input)
    if not match:
        await update.message.reply_text("❌ تنسيق خاطئ! أرسل: `@يوزر | السيريال` مع الصورة أو الفيديو.")
        return

    new_user = match.group(1).lower()
    new_serial = match.group(2).lower()

    # التحقق من وجود السيريال أو اليوزر مسبقاً (قواعد التحديث كل 15 يوم)
    user_data = CACHE["users"].get(new_user)
    serial_owner = CACHE["serials"].get(new_serial)

    if user_data and user_data['serial'] == new_serial:
        await update.message.reply_text("⚠️ هذا اللاعب مسجل مسبقاً بنفس البيانات.")
        return

    action_type = "NEW"
    extra_info = "✅ لاعب جديد بالكامل."

    if user_data:
        diff = datetime.utcnow() - user_data['date']
        if diff.days < 15:
            days_left = 15 - diff.days
            await update.message.reply_text(f"❌ لا يمكنك تغيير التسلسلي إلا كل 15 يوم.\n⏳ متبقي: {days_left} يوم.")
            return
        action_type = "CHANGE_SERIAL"
        extra_info = f"🔄 تغيير تسلسلي (مرّ أكثر من 15 يوم)."
    elif serial_owner:
        action_type = "CHANGE_USER"
        extra_info = f"🔄 تغيير يوزر لنفس الجهاز."

    # تحميل الوسائط وفحصها
    status_msg = "جارٍ فحص الميديا..."
    progress_msg = await update.message.reply_text(status_msg)

    media_file = None
    if update.message.photo:
        media_file = await update.message.photo[-1].get_file()
    elif update.message.video:
        media_file = await update.message.video.get_file()

    if not media_file:
        await progress_msg.edit_text("❌ حدث خطأ في تحميل الملف.")
        return

    file_path = f"temp_{update.message.chat_id}.jpg" if update.message.photo else f"temp_{update.message.chat_id}.mp4"
    await media_file.download_to_drive(file_path)

    # فحص الصورة (إذا كانت صورة) وإلا نضع رسالة تحذير للفيديو
    if update.message.photo:
        authenticity = await check_media_authenticity(file_path, new_serial)
    else:
        authenticity = "⚠️ **فيديو:** لم يتم الفحص الآلي (يُفضل الفحص اليدوي)"

    # فحص التشابه مع السيريالات المخزنة
    similarity_warnings = check_serial_similarity(new_serial)
    similarity_text = "\n".join(similarity_warnings) if similarity_warnings else "✅ لا يوجد تشابه مع أي سيريال مسجل."

    # حذف الملف المؤقت
    try:
        os.remove(file_path)
    except:
        pass

    await progress_msg.delete()

    # إرسال الطلب للمشرفين مع نتيجة الفحص
    keyboard = [[
        InlineKeyboardButton("✅ قبول", callback_data=f"ok_{update.message.chat_id}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"no_{update.message.chat_id}")
    ]]

    caption = (
        f"📝 **طلب فحص:**\n{extra_info}\n"
        f"👤 اليوزر: {new_user}\n🔢 السيريال: {new_serial}\n"
        f"🆔 ID: `{update.message.chat_id}`\n\n"
        f"🔍 **نتيجة فحص الميديا:**\n{authenticity}\n\n"
        f"🔁 **فحص التشابه:**\n{similarity_text}"
    )

    # إرسال الوسائط إلى مجموعة الإدارة مع الكابشن والأزرار
    if update.message.photo:
        await context.bot.send_photo(
            chat_id=GROUP_ID,
            photo=update.message.photo[-1].file_id,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif update.message.video:
        await context.bot.send_video(
            chat_id=GROUP_ID,
            video=update.message.video.file_id,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    await update.message.reply_text("✅ تم إرسال طلبك للمراجعة، سيتم إعلامك بعد القبول أو الرفض.")

    # حفظ بيانات الطلب مؤقتاً للردود
    context.bot_data[f"data_{update.message.chat_id}"] = {
        "u": new_user, "s": new_serial, "type": action_type,
        "media_type": "photo" if update.message.photo else "video"
    }

# -------------------- معالجة القبول والرفض --------------------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not await is_admin(user_id, GROUP_ID, context):
        await query.answer("ليس لديك صلاحية!", show_alert=True)
        return

    data = query.data.split("_")
    action, uid = data[0], data[1]
    user_info = context.bot_data.get(f"data_{uid}")

    if not user_info:
        await query.answer("بيانات الطلب منتهية.")
        return

    if action == "ok":
        success = await process_update(context, uid, user_info)
        if success:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=f"✅ تم تنفيذ طلب {user_info['u']} بواسطة @{query.from_user.username}"
            )
    elif action == "no":
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=f"الرد على هذه الرسالة بسبب الرفض لـ `{uid}`:",
            reply_markup=ForceReply(selective=True)
        )
        await query.answer("أدخل سبب الرفض")

async def process_update(context, uid, info):
    """تحديث القائمة (الرسالة 219) والكاش عند القبول"""
    try:
        channel_msg = await context.bot.forward_message(
            chat_id=GROUP_ID, from_chat_id=CHANNEL_USERNAME, message_id=LIST_MESSAGE_ID
        )
        lines = channel_msg.text.split('\n')
        await context.bot.delete_message(chat_id=GROUP_ID, message_id=channel_msg.message_id)

        updated = False
        target_u = info['u']
        target_s = info['s']

        for i, line in enumerate(lines):
            if info['type'] == "CHANGE_SERIAL" and target_u in line.lower():
                lines[i] = re.sub(r"\[.*\]", f"[ {target_u} | {target_s} ]", line)
                updated = True
                break
            elif info['type'] == "CHANGE_USER" and target_s in line.lower():
                lines[i] = re.sub(r"\[.*\]", f"[ {target_u} | {target_s} ]", line)
                updated = True
                break
            elif info['type'] == "NEW" and ("[" in line and "]" in line):
                content = re.search(r"\[(.*?)\]", line).group(1).strip()
                if not content:
                    lines[i] = re.sub(r"\[.*\]", f"[ {target_u} | {target_s} ]", line)
                    updated = True
                    break

        if updated:
            new_text = "\n".join(lines)
            await context.bot.edit_message_text(
                chat_id=CHANNEL_USERNAME, message_id=LIST_MESSAGE_ID, text=new_text
            )
            # تحديث الكاش
            CACHE["users"][target_u] = {"serial": target_s, "date": datetime.utcnow(), "msg_id": LIST_MESSAGE_ID}
            CACHE["serials"][target_s] = target_u
            await context.bot.send_message(chat_id=int(uid), text="✅ تم قبول طلبك وتحديث بياناتك في القائمة!")
            return True
    except Exception as e:
        logging.error(f"Error in process_update: {e}")
    return False

async def handle_reject_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != GROUP_ID or not update.message.reply_to_message:
        return
    if "سبب الرفض" in update.message.reply_to_message.text:
        match = re.search(r"`(\d+)`", update.message.reply_to_message.text)
        if match:
            uid = match.group(1)
            reason = update.message.text
            await context.bot.send_message(
                chat_id=int(uid),
                text=f"❌ تم رفض طلبك.\n**السبب:** {reason}"
            )
            await update.message.reply_text("✅ تم إبلاغ اللاعب بالرفض.")

# -------------------- تشغيل البوت --------------------
def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    # قبول الصور والفيديوهات مع كابشن
    app.add_handler(MessageHandler(
        (filters.PHOTO | filters.VIDEO) & filters.CAPTION,
        handle_registration
    ))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, handle_reject_reply))

    print("🤖 البوت يعمل الآن مع دعم الصور والفيديو وفحص التشابه والمونتاج...")
    app.run_polling()

if __name__ == '__main__':
    main()
