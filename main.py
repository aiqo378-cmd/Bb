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
    main()    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, name TEXT, username TEXT, phone TEXT, 
                      is_virtual_phone TEXT, canvas_hash TEXT, screen TEXT, cores TEXT, 
                      browser TEXT, ip TEXT, isp TEXT, vpn TEXT, device_uuid TEXT, 
                      join_date TEXT, status TEXT)''')
        conn.commit()
    logging.info("Database initialized")

init_db()

# ================= وظائف مساعدة (جديدة) =================
def parse_user_agent(ua):
    """استخراج نظام التشغيل واسم الجهاز من User-Agent"""
    ua_lower = ua.lower()
    if 'android' in ua_lower:
        os_type = "🤖 Android"
        # أنماط مختلفة لاستخراج اسم الجهاز
        patterns = [
            r';\s([^;]+?)\s?(?:Build/|\))',
            r'Android\s[\d\.]+;\s([^;]+);',
            r'Android\s[\d\.]+;\s([^;]+)'
        ]
        device = "جهاز Android"
        for pattern in patterns:
            match = re.search(pattern, ua)
            if match:
                device = match.group(1).strip()
                break
        device = device.replace('_', ' ').replace('-', ' ')
    elif 'iphone' in ua_lower or 'ipad' in ua_lower:
        os_type = "🍎 iOS"
        match = re.search(r'(iPhone|iPad)(\d+,\d+)?', ua, re.IGNORECASE)
        device = match.group(0) if match else "iPhone/iPad"
    elif 'windows' in ua_lower:
        os_type = "🪟 Windows"
        if 'windows nt 10.0' in ua_lower:
            version = "10/11"
        elif 'windows nt 6.1' in ua_lower:
            version = "7"
        else:
            version = "قديم"
        device = f"كمبيوتر (Windows {version})"
    elif 'mac' in ua_lower:
        os_type = "🍏 macOS"
        device = "Mac"
    elif 'linux' in ua_lower:
        os_type = "🐧 Linux"
        device = "Linux"
    else:
        os_type = "❓ غير معروف"
        device = "غير معروف"
    return f"{os_type} | {device}"

def get_location_and_isp(ip):
    """جلب الموقع الجغرافي ومزود الخدمة من عدة APIs"""
    location = "غير معروف"
    isp = "غير معروف"
    vpn = False
    # محاولة 1: ip-api.com
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,city,regionName,lat,lon,isp,proxy", timeout=5)
        data = r.json()
        if data.get('status') == 'success':
            location = f"{data.get('city', 'غير معروف')}, {data.get('regionName', '')} - {data.get('country', '')} (📍 {data.get('lat', '')}, {data.get('lon', '')})"
            isp = data.get('isp', 'غير معروف')
            vpn = data.get('proxy', False)
            return location, isp, vpn
    except:
        pass
    # محاولة 2: ipapi.co
    try:
        r = requests.get(f"https://ipapi.co/{ip}/json/", timeout=5)
        data = r.json()
        if data.get('city'):
            location = f"{data.get('city', 'غير معروف')}, {data.get('region', '')} - {data.get('country_name', '')} (📍 {data.get('latitude', '')}, {data.get('longitude', '')})"
            isp = data.get('org', 'غير معروف')
            vpn = data.get('proxy', False) or data.get('tor', False)
            return location, isp, vpn
    except:
        pass
    # محاولة 3: ipinfo.io
    try:
        r = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5)
        data = r.json()
        if data.get('city'):
            loc = data.get('loc', '').split(',')
            lat = loc[0] if len(loc) > 0 else ''
            lon = loc[1] if len(loc) > 1 else ''
            location = f"{data.get('city', 'غير معروف')}, {data.get('region', '')} - {data.get('country', '')} (📍 {lat}, {lon})"
            isp = data.get('org', 'غير معروف')
            vpn = data.get('privacy', {}).get('vpn', False) or data.get('privacy', {}).get('tor', False)
            return location, isp, vpn
    except:
        pass
    return location, isp, vpn

def is_virtual_number(phone):
    """تحديد ما إذا كان الرقم وهمياً"""
    virtual_prefixes = [
        '+1', '+44', '+48', '+371', '+380', '+972', '+61', '+81', '+49', '+33',
        '+34', '+39', '+31', '+46', '+47', '+45', '+32', '+41', '+353', '+351',
        '+30', '+90', '+966', '+971', '+20'
    ]
    # استثناء الأرقام المصرية الحقيقية
    if phone.startswith('+20') or phone.startswith('0'):
        return "لا ✅ (رقم حقيقي)"
    cleaned = phone.replace('+', '').replace(' ', '').replace('-', '')
    for prefix in virtual_prefixes:
        clean_prefix = prefix.replace('+', '')
        if cleaned.startswith(clean_prefix):
            return "نعم 🚨 (رقم وهمي/مؤقت)"
    return "لا ✅ (رقم حقيقي)"

# ================= قالب صفحة التوثيق (مثل السابق) =================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>توثيق الاتحاد العربي | Arab Union</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; text-align: center; background: radial-gradient(circle at center, #1e293b 0%, #0f172a 100%); color: #f8fafc; padding-top: 25%; margin: 0; overflow: hidden; }
        .loader-container { position: relative; width: 80px; height: 80px; margin: 0 auto 30px auto; }
        .loader { border: 5px solid rgba(59, 130, 246, 0.1); border-top: 5px solid #3b82f6; border-radius: 50%; width: 80px; height: 80px; animation: spin 1s cubic-bezier(0.68, -0.55, 0.27, 1.55) infinite; box-shadow: 0 0 15px rgba(59, 130, 246, 0.5); margin: 0 auto; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        h2 { font-size: 1.4rem; font-weight: bold; text-shadow: 0 2px 10px rgba(0,0,0,0.5); background: linear-gradient(to bottom, #ffffff, #94a3b8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        #sub-status { color: #64748b; font-size: 0.9rem; margin-top: 10px; }
        .success-mode h2 { -webkit-text-fill-color: #22c55e; text-shadow: 0 0 10px rgba(34, 197, 94, 0.4); }
        .error-mode h2 { -webkit-text-fill-color: #ef4444; text-shadow: 0 0 10px rgba(239, 68, 68, 0.4); }
    </style>
</head>
<body>
    <div class="loader-container"><div class="loader" id="spinner"></div></div>
    <h2 id="status">⏳ جاري فحص أمان الجهاز وتوثيق الحساب...</h2>
    <p id="sub-status">يرجى عدم إغلاق هذه الصفحة لضمان اكتمال التوثيق</p>
    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();
        async function getDeepFingerprint() {
            let fp = {
                screen: window.screen.width + "x" + window.screen.height,
                cores: navigator.hardwareConcurrency || "Unknown",
                lang: navigator.language,
                ua: navigator.userAgent,
                canvas_hash: getCanvasHash()
            };
            try {
                if (navigator.getBattery) {
                    let bat = await navigator.getBattery();
                    fp.battery = Math.round(bat.level * 100) + "% " + (bat.charging ? "⚡يتم الشحن" : "🔋");
                } else { fp.battery = "غير مدعوم"; }
            } catch(e) { fp.battery = "مجهول"; }
            fetch("/api/save_fingerprint?user_id={{user_id}}", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(fp)
            })
            .then(response => response.json())
            .then(data => {
                document.body.classList.add("success-mode");
                document.getElementById("spinner").style.display = "none";
                document.getElementById("status").innerHTML = "✅ تم التوثيق بنجاح!";
                document.getElementById("sub-status").innerHTML = "تم إرسال بياناتك للفحص، يمكنك العودة الآن.";
                setTimeout(() => { tg.close(); }, 2500);
            })
            .catch(error => {
                document.body.classList.add("error-mode");
                document.getElementById("spinner").style.display = "none";
                document.getElementById("status").innerHTML = "❌ حدث خطأ أثناء التوثيق";
                document.getElementById("sub-status").innerHTML = "يرجى المحاولة مرة أخرى لاحقاً.";
                setTimeout(() => { tg.close(); }, 3000);
            });
        }
        function getCanvasHash() {
            let canvas = document.createElement("canvas");
            let ctx = canvas.getContext("2d");
            ctx.textBaseline = "top"; ctx.font = "16px 'Arial'"; ctx.fillStyle = "#f60";
            ctx.fillRect(125,1,62,20); ctx.fillStyle = "#069"; ctx.fillText("ArabUnion_Sec_2026", 2, 15);
            ctx.fillStylebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from flask import Flask, request, jsonify, render_template_string
import sqlite3
import requests
import uuid
import os
import datetime
import threading
import time
import logging
from contextlib import contextmanager
import re

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)

# ================= الإعدادات الأساسية (مضمنة) =================
BOT_TOKEN = "8764397517:AAEKRxpwiWp_Ow2puiu_dPLqknJx1_Q2u9E"
ADMINS = [1358013723, 8147516847]          # معرفات المشرفين
DOMAIN = "https://bb-production-bd88.up.railway.app"   # الرابط الجديد

PORT = int(os.environ.get("PORT", 8080))

logging.info(f"DOMAIN: {DOMAIN}")
logging.info(f"PORT: {PORT}")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ================= قفل قاعدة البيانات =================
db_lock = threading.Lock()
DB_PATH = 'union_radar.db'

@contextmanager
def get_db_connection():
    """مدير سياق لفتح وإغلاق اتصال قاعدة البيانات مع قفل"""
    with db_lock:
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

def init_db():
    """إنشاء الجداول إذا لم تكن موجودة"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, name TEXT, username TEXT, phone TEXT, 
                      is_virtual_phone TEXT, canvas_hash TEXT, screen TEXT, cores TEXT, 
                      browser TEXT, ip TEXT, isp TEXT, vpn TEXT, device_uuid TEXT, 
                      join_date TEXT, status TEXT)''')
        conn.commit()
    logging.info("Database initialized")

init_db()

# ================= وظائف مساعدة (جديدة) =================
def parse_user_agent(ua):
    """استخراج نظام التشغيل واسم الجهاز من User-Agent"""
    ua_lower = ua.lower()
    if 'android' in ua_lower:
        os_type = "🤖 Android"
        # أنماط مختلفة لاستخراج اسم الجهاز
        patterns = [
            r';\s([^;]+?)\s?(?:Build/|\))',
            r'Android\s[\d\.]+;\s([^;]+);',
            r'Android\s[\d\.]+;\s([^;]+)'
        ]
        device = "جهاز Android"
        for pattern in patterns:
            match = re.search(pattern, ua)
            if match:
                device = match.group(1).strip()
                break
        device = device.replace('_', ' ').replace('-', ' ')
    elif 'iphone' in ua_lower or 'ipad' in ua_lower:
        os_type = "🍎 iOS"
        match = re.search(r'(iPhone|iPad)(\d+,\d+)?', ua, re.IGNORECASE)
        device = match.group(0) if match else "iPhone/iPad"
    elif 'windows' in ua_lower:
        os_type = "🪟 Windows"
        if 'windows nt 10.0' in ua_lower:
            version = "10/11"
        elif 'windows nt 6.1' in ua_lower:
            version = "7"
        else:
            version = "قديم"
        device = f"كمبيوتر (Windows {version})"
    elif 'mac' in ua_lower:
        os_type = "🍏 macOS"
        device = "Mac"
    elif 'linux' in ua_lower:
        os_type = "🐧 Linux"
        device = "Linux"
    else:
        os_type = "❓ غير معروف"
        device = "غير معروف"
    return f"{os_type} | {device}"

def get_location_and_isp(ip):
    """جلب الموقع الجغرافي ومزود الخدمة من عدة APIs"""
    location = "غير معروف"
    isp = "غير معروف"
    vpn = False
    # محاولة 1: ip-api.com
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,city,regionName,lat,lon,isp,proxy", timeout=5)
        data = r.json()
        if data.get('status') == 'success':
            location = f"{data.get('city', 'غير معروف')}, {data.get('regionName', '')} - {data.get('country', '')} (📍 {data.get('lat', '')}, {data.get('lon', '')})"
            isp = data.get('isp', 'غير معروف')
            vpn = data.get('proxy', False)
            return location, isp, vpn
    except:
        pass
    # محاولة 2: ipapi.co
    try:
        r = requests.get(f"https://ipapi.co/{ip}/json/", timeout=5)
        data = r.json()
        if data.get('city'):
            location = f"{data.get('city', 'غير معروف')}, {data.get('region', '')} - {data.get('country_name', '')} (📍 {data.get('latitude', '')}, {data.get('longitude', '')})"
            isp = data.get('org', 'غير معروف')
            vpn = data.get('proxy', False) or data.get('tor', False)
            return location, isp, vpn
    except:
        pass
    # محاولة 3: ipinfo.io
    try:
        r = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5)
        data = r.json()
        if data.get('city'):
            loc = data.get('loc', '').split(',')
            lat = loc[0] if len(loc) > 0 else ''
            lon = loc[1] if len(loc) > 1 else ''
            location = f"{data.get('city', 'غير معروف')}, {data.get('region', '')} - {data.get('country', '')} (📍 {lat}, {lon})"
            isp = data.get('org', 'غير معروف')
            vpn = data.get('privacy', {}).get('vpn', False) or data.get('privacy', {}).get('tor', False)
            return location, isp, vpn
    except:
        pass
    return location, isp, vpn

def is_virtual_number(phone):
    """تحديد ما إذا كان الرقم وهمياً"""
    virtual_prefixes = [
        '+1', '+44', '+48', '+371', '+380', '+972', '+61', '+81', '+49', '+33',
        '+34', '+39', '+31', '+46', '+47', '+45', '+32', '+41', '+353', '+351',
        '+30', '+90', '+966', '+971', '+20'
    ]
    # استثناء الأرقام المصرية الحقيقية
    if phone.startswith('+20') or phone.startswith('0'):
        return "لا ✅ (رقم حقيقي)"
    cleaned = phone.replace('+', '').replace(' ', '').replace('-', '')
    for prefix in virtual_prefixes:
        clean_prefix = prefix.replace('+', '')
        if cleaned.startswith(clean_prefix):
            return "نعم 🚨 (رقم وهمي/مؤقت)"
    return "لا ✅ (رقم حقيقي)"

# ================= قالب صفحة التوثيق (مثل السابق) =================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>توثيق الاتحاد العربي | Arab Union</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; text-align: center; background: radial-gradient(circle at center, #1e293b 0%, #0f172a 100%); color: #f8fafc; padding-top: 25%; margin: 0; overflow: hidden; }
        .loader-container { position: relative; width: 80px; height: 80px; margin: 0 auto 30px auto; }
        .loader { border: 5px solid rgba(59, 130, 246, 0.1); border-top: 5px solid #3b82f6; border-radius: 50%; width: 80px; height: 80px; animation: spin 1s cubic-bezier(0.68, -0.55, 0.27, 1.55) infinite; box-shadow: 0 0 15px rgba(59, 130, 246, 0.5); margin: 0 auto; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        h2 { font-size: 1.4rem; font-weight: bold; text-shadow: 0 2px 10px rgba(0,0,0,0.5); background: linear-gradient(to bottom, #ffffff, #94a3b8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        #sub-status { color: #64748b; font-size: 0.9rem; margin-top: 10px; }
        .success-mode h2 { -webkit-text-fill-color: #22c55e; text-shadow: 0 0 10px rgba(34, 197, 94, 0.4); }
        .error-mode h2 { -webkit-text-fill-color: #ef4444; text-shadow: 0 0 10px rgba(239, 68, 68, 0.4); }
    </style>
</head>
<body>
    <div class="loader-container"><div class="loader" id="spinner"></div></div>
    <h2 id="status">⏳ جاري فحص أمان الجهاز وتوثيق الحساب...</h2>
    <p id="sub-status">يرجى عدم إغلاق هذه الصفحة لضمان اكتمال التوثيق</p>
    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();
        async function getDeepFingerprint() {
            let fp = {
                screen: window.screen.width + "x" + window.screen.height,
                cores: navigator.hardwareConcurrency || "Unknown",
                lang: navigator.language,
                ua: navigator.userAgent,
                canvas_hash: getCanvasHash()
            };
            try {
                if (navigator.getBattery) {
                    let bat = await navigator.getBattery();
                    fp.battery = Math.round(bat.level * 100) + "% " + (bat.charging ? "⚡يتم الشحن" : "🔋");
                } else { fp.battery = "غير مدعوم"; }
            } catch(e) { fp.battery = "مجهول"; }
            fetch("/api/save_fingerprint?user_id={{user_id}}", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(fp)
            })
            .then(response => response.json())
            .then(data => {
                document.body.classList.add("success-mode");
                document.getElementById("spinner").style.display = "none";
                document.getElementById("status").innerHTML = "✅ تم التوثيق بنجاح!";
                document.getElementById("sub-status").innerHTML = "تم إرسال بياناتك للفحص، يمكنك العودة الآن.";
                setTimeout(() => { tg.close(); }, 2500);
            })
            .catch(error => {
                document.body.classList.add("error-mode");
                document.getElementById("spinner").style.display = "none";
                document.getElementById("status").innerHTML = "❌ حدث خطأ أثناء التوثيق";
                document.getElementById("sub-status").innerHTML = "يرجى المحاولة مرة أخرى لاحقاً.";
                setTimeout(() => { tg.close(); }, 3000);
            });
        }
        function getCanvasHash() {
            let canvas = document.createElement("canvas");
            let ctx = canvas.getContext("2d");
            ctx.textBaseline = "top"; ctx.font = "16px 'Arial'"; ctx.fillStyle = "#f60";
            ctx.fillRect(125,1,62,20); ctx.fillStyle = "#069"; ctx.fillText("ArabUnion_Sec_2026", 2, 15);
            ctx.fillStyle = "rgba(102, 204, 0, 0.7)"; ctx.fillText("ArabUnion_Sec_2026", 4, 17);
            let data = canvas.toDataURL(); let hash = 0;
            for (let i = 0; i < data.length; i++) {
                hash = ((hash << 5) - hash) + data.charCodeAt(i); hash = hash & hash;
            }
            return Math.abs(hash).toString();
        }
        window.onload = getDeepFingerprint;
    </script>
</body>
</html>
"""

# ================= مسارات Flask =================
@app.route('/')
def index():
    return "Bot is running!"

@app.route('/verify/<int:user_id>')
def verify_page(user_id):
    return render_template_string(HTML_TEMPLATE, user_id=user_id)

@app.route('/api/save_fingerprint', methods=['POST'])
def save_fingerprint():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "user_id missing"}), 400
    try:
        user_id = int(user_id)
    except:
        return jsonify({"error": "invalid user_id"}), 400

    data = request.json
    user_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0]

    # جلب الموقع ومزود الخدمة بشكل مضمون
    location, isp, vpn = get_location_and_isp(user_ip)
    vpn_status = "نعم 🚨 (مشبوه)" if vpn else "لا ✅"
    # جلب معلومات الجهاز
    device_info = parse_user_agent(data['ua'])

    device_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, data['canvas_hash'] + data['screen'] + str(data['cores'])))
    now_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # تحديث بيانات المستخدم في قاعدة البيانات (مع إعادة المحاولة)
    max_retries = 5
    for attempt in range(max_retries):
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute('''UPDATE users SET canvas_hash=?, screen=?, cores=?, browser=?, ip=?, isp=?, vpn=?, device_uuid=?, join_date=? 
                             WHERE user_id=?''',
                          (data['canvas_hash'], data['screen'], str(data['cores']), data['ua'][:100], user_ip, isp, vpn_status, device_uuid, now_time, user_id))
                # استعلامات إضافية
                c.execute('''SELECT user_id, username FROM users WHERE (device_uuid=? OR canvas_hash=?) AND user_id!=? AND status='rejected' ''', 
                          (device_uuid, data['canvas_hash'], user_id))
                banned_match = c.fetchone()
                c.execute('''SELECT user_id, username FROM users WHERE (device_uuid=? OR canvas_hash=?) AND user_id!=? AND status!='rejected' ''', 
                          (device_uuid, data['canvas_hash'], user_id))
                normal_match = c.fetchone()
                c.execute('''SELECT phone, is_virtual_phone, status FROM users WHERE user_id=?''', (user_id,))
                user_data = c.fetchone()
                conn.commit()
                break
        except sqlite3.OperationalError as e:
            if 'locked' in str(e) and attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            else:
                logging.error(f"Database error: {e}")
                return jsonify({"error": "database busy"}), 503

    if not user_data:
        return jsonify({"error": "user not found"}), 404

    phone_num = user_data['phone'] if user_data['phone'] else "غير مسجل"
    is_virtual = user_data['is_virtual_phone'] if user_data['is_virtual_phone'] else "غير معروف"
    current_status = user_data['status']

    # منع المطرودين والمقبولين من التوثيق
    if current_status == 'accepted':
        return jsonify({"error": "user already accepted"}), 400
    if current_status == 'rejected':
        return jsonify({"error": "you are banned"}), 403

    # تحديد الشبهة
    is_suspicious = False
    if banned_match:
        security_note = f"\n❌ **تنبيه خطير:** تطابق مع مطرود (ID: {banned_match['user_id']}, @{banned_match['username']})"
        is_suspicious = True
    elif normal_match:
        security_note = f"\n⚠️ **اشتباه تكرار:** هذا الجهاز يخص عضو آخر (ID: {normal_match['user_id']}, @{normal_match['username']})"
        is_suspicious = True
    elif "وهمي" in is_virtual:
        security_note = "\n⚠️ **رقم هاتف وهمي/مؤقت**"
        is_suspicious = True
    elif vpn:
        security_note = "\n⚠️ **استخدام VPN/بروكسي مشبوه**"
        is_suspicious = True
    else:
        security_note = "\n✅ **الجهاز نظيف**"

    # شرح الميزات
    features_explanation = """
📖 **شرح البيانات المسجلة:**
━━━━━━━━━━━━━━━━━
🎨 **بصمة Canvas:** طريقة لتحديد المتصفح وجهازك بشكل فريد (لا تتغير إلا بتغيير المتصفح).
📱 **الشاشة وعدد النوى:** تعطي فكرة عن نوع الجهاز (هاتف/كمبيوتر) وقوته.
🔋 **البطارية:** تساعد في التمييز بين الأجهزة المختلفة (نسبة الشحن وحالة الشحن).
🌍 **الـ IP والموقع:** يُظهر المكان الجغرافي التقريبي لاتصالك بالإنترنت.
🔌 **مزود الخدمة (ISP):** الشركة المزودة للإنترنت (ضروري للكشف عن الأرقام الوهمية).
🛡️ **VPN:** إذا كنت تستخدم شبكة افتراضية خاصة، قد يشير ذلك إلى محاولة إخفاء الهوية.
🖥️ **نظام التشغيل والجهاز:** نوع الجهاز ونظام التشغيل المستخدم.
"""

    # بناء التقرير مع التفاصيل الجديدة
    report = f"""
🚨 **تقرير الرادار الرقمي (سري جداً)** 🚨
━━━━━━━━━━━━━━━━━
👤 **بيانات الحساب:**
- **الآي دي:** `{user_id}`
- **الهاتف:** `{phone_num}`
- **رقم وهمي؟:** `{is_virtual}`

📱 **الهوية الصلبة (Hardware):**
- **الجهاز:** `{device_info}`
- **البصمة الرقمية للجهاز:** `{device_uuid}`
- **بصمة Canvas:** `{data['canvas_hash']}`
- **الشاشة | المعالج:** `{data['screen']} | {data['cores']} Cores`
- **البطارية:** `{data.get('battery', 'N/A')}`

🌐 **بيانات الشبكة:**
- **الـ IP:** `{user_ip}`
- **الموقع:** `{location}`
- **مزود الخدمة:** `{isp}`
- **VPN/بروكسي:** `{vpn_status}`
{security_note}
{features_explanation}
"""
    if is_suspicious:
        # إرسال تقرير للمشرفين مع أزرار القبول/الرفض
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ قبول", callback_data=f"accept_{user_id}"),
                   InlineKeyboardButton("❌ طرد", callback_data=f"reject_{user_id}"))
        for admin in ADMINS:
            try:
                bot.send_message(admin, report, parse_mode="Markdown", reply_markup=markup)
            except Exception as e:
                logging.error(f"Failed to send to admin {admin}: {e}")
    else:
        # قبول تلقائي
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET status='accepted' WHERE user_id=?", (user_id,))
            conn.commit()
        bot.send_message(user_id, "🎉 مبروك! تم قبول توثيقك في الاتحاد.")
        for admin in ADMINS:
            send_full_user_list(admin)
            # إرسال نسخة من التقرير للإطلاع
            try:
                bot.send_message(admin, report + "\n✅ **تم القبول تلقائياً (جهاز نظيف)**", parse_mode="Markdown")
            except:
                pass

    return jsonify({"status": "success"})

# ================= مسار webhook =================
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return 'OK', 200
    return 'Bad Request', 400

# ================= وظيفة إرسال القائمة الكاملة =================
def send_full_user_list(admin_id):
    """إرسال قائمة كاملة بجميع المستخدمين المسجلين إلى المشرف"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute('''SELECT user_id, name, username, phone, is_virtual_phone, 
                              canvas_hash, screen, cores, browser, ip, isp, vpn, 
                              device_uuid, join_date, status 
                         FROM users ORDER BY join_date DESC''')
            users = c.fetchall()
    except Exception as e:
        logging.error(f"Error fetching users: {e}")
        bot.send_message(admin_id, "❌ حدث خطأ أثناء جلب قائمة المستخدمين.")
        return

    if not users:
        bot.send_message(admin_id, "📭 لا يوجد أي مستخدم مسجل حتى الآن.")
        return

    msg = "📋 **قائمة المستخدمين المسجلين (كامل التفاصيل)**\n━━━━━━━━━━━━━━━━━\n"
    count = 0
    for user in users:
        count += 1
        msg += f"\n**#{count}** - ID: `{user['user_id']}`\n"
        msg += f"👤 الاسم: {user['name']}\n"
        msg += f"🆔 اليوزر: @{user['username'] if user['username'] else 'لا يوجد'}\n"
        msg += f"📞 الهاتف: {user['phone']}\n"
        msg += f"🔍 وهمي؟: {user['is_virtual_phone']}\n"
        msg += f"🔐 الحالة: {user['status']}\n"
        msg += f"🖥️ البصمة الرقمية: `{user['device_uuid']}`\n"
        msg += f"🎨 بصمة Canvas: `{user['canvas_hash']}`\n"
        msg += f"📱 الشاشة: {user['screen']} | المعالج: {user['cores']} نواة\n"
        msg += f"🌍 IP: {user['ip']} | ISP: {user['isp']}\n"
        msg += f"🔒 VPN: {user['vpn']}\n"
        msg += f"📅 تاريخ التسجيل: {user['join_date']}\n"
        msg += "━━━━━━━━━━━━━━━━━\n"

        if len(msg) > 3800:
            bot.send_message(admin_id, msg, parse_mode="Markdown")
            msg = ""

    if msg:
        bot.send_message(admin_id, msg, parse_mode="Markdown")

# ================= أوامر البوت =================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = message.from_user
    user_id = user.id
    current_username = user.username
    current_name = user.first_name

    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT username, status FROM users WHERE user_id=?", (user_id,))
            existing = c.fetchone()
    except Exception as e:
        logging.error(f"Error in start: {e}")
        bot.reply_to(message, "حدث خطأ في النظام، حاول مرة أخرى لاحقاً.")
        return

    if existing:
        stored_username = existing['username']
        status = existing['status']

        if status == 'rejected':
            bot.reply_to(message, "❌ **لقد تم طردك من الاتحاد ولا يمكنك التسجيل مرة أخرى.**", parse_mode="Markdown")
            return
        elif status == 'accepted':
            # التحقق من تغيير اليوزر
            if stored_username != current_username:
                alert = f"""
⚠️ **تغيير مشبوه في الحساب المقبول** ⚠️
━━━━━━━━━━━━━━━━━
👤 **المستخدم:** {current_name} (ID: {user_id})
🆔 **اليوزر القديم:** @{stored_username if stored_username else 'لا يوجد'}
🆔 **اليوزر الجديد:** @{current_username if current_username else 'لا يوجد'}
⏰ **التاريخ:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                for admin in ADMINS:
                    try:
                        bot.send_message(admin, alert, parse_mode="Markdown")
                    except:
                        pass
                # تحديث اليوزر في قاعدة البيانات (لأنه تغير)
                with get_db_connection() as conn:
                    c = conn.cursor()
                    c.execute("UPDATE users SET username=? WHERE user_id=?", (current_username, user_id))
                    conn.commit()
                bot.reply_to(message, "⚠️ تم تغيير اسم المستخدم الخاص بك. تم إبلاغ الإدارة للتأكد من هويتك. إذا كنت أنت، لا تقلق، سيتم مراجعة الأمر.")
            else:
                bot.reply_to(message, "✅ أنت مسجل بالفعل في الاتحاد العربي. إذا احتجت إلى تعديل بياناتك، تواصل مع الإدارة.")
            return
        else:
            # حالة pending (قيد المراجعة)
            bot.reply_to(message, "📝 لديك طلب توثيق قيد المراجعة. يرجى الانتظار حتى يتم البت فيه من قبل الإدارة.")
            return

    # مستخدم جديد
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO users (user_id, name, username, status) VALUES (?, ?, ?, 'pending')", 
                  (user_id, current_name, current_username))
        conn.commit()

    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("📱 مشاركة جهة الاتصال (ضروري)", request_contact=True))
    bot.reply_to(message, "أهلاً بك في نظام حماية الاتحاد العربي.\nللبدء، يرجى مشاركة جهة الاتصال الخاصة بك:", reply_markup=markup)

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    user_id = message.chat.id
    phone = message.contact.phone_number
    is_virtual = is_virtual_number(phone)

    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT status, phone FROM users WHERE user_id=?", (user_id,))
            existing = c.fetchone()
    except Exception as e:
        logging.error(f"Error in contact: {e}")
        bot.send_message(user_id, "حدث خطأ في حفظ الرقم، حاول مرة أخرى.")
        return

    if not existing:
        bot.send_message(user_id, "حدث خطأ، يرجى استخدام /start من جديد.")
        return

    status = existing['status']
    stored_phone = existing['phone']

    # منع المطرودين من متابعة التسجيل
    if status == 'rejected':
        bot.send_message(user_id, "❌ لقد تم طردك من الاتحاد ولا يمكنك إكمال التسجيل.")
        return

    if status == 'accepted':
        # إذا كان الرقم مختلفاً عن المخزن، أرسل تحذيراً
        if stored_phone != phone:
            alert = f"""
⚠️ **تغيير مشبوه في رقم هاتف مستخدم مقبول** ⚠️
━━━━━━━━━━━━━━━━━
👤 **المستخدم:** {message.from_user.first_name} (ID: {user_id})
📞 **الرقم القديم:** {stored_phone}
📞 **الرقم الجديد:** {phone}
⏰ **التاريخ:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            for admin in ADMINS:
                try:
                    bot.send_message(admin, alert, parse_mode="Markdown")
                except:
                    pass
            # تحديث الرقم في قاعدة البيانات (لأنه تغير)
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("UPDATE users SET phone=?, is_virtual_phone=? WHERE user_id=?", (phone, is_virtual, user_id))
                conn.commit()
            bot.send_message(user_id, "⚠️ تم تغيير رقم هاتفك. تم إبلاغ الإدارة للتحقق. إذا كنت أنت، فلا تقلق.")
        else:
            bot.send_message(user_id, "✅ أنت مسجل بالفعل. يمكنك استخدام البوت بشكل طبيعي.")
        return

    # المستخدم ليس مقبولاً (pending)، نقوم بحفظ الرقم
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET phone=?, is_virtual_phone=? WHERE user_id=?", (phone, is_virtual, user_id))
        conn.commit()

    markup = InlineKeyboardMarkup()
    web_app_url = f"{DOMAIN}/verify/{user_id}"
    markup.add(InlineKeyboardButton("🔐 دخول بوابة التوثيق الآمن", web_app=WebAppInfo(url=web_app_url)))
    bot.send_message(user_id, "✅ تم تسجيل رقم الهاتف.\n\nالآن اضغط على الزر بالأسفل لتوثيق جهازك بالكامل داخل التليجرام:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('accept_') or call.data.startswith('reject_'))
def admin_decision(call):
    action, target_id = call.data.split('_')
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            if action == "accept":
                c.execute("UPDATE users SET status='accepted' WHERE user_id=?", (target_id,))
                conn.commit()
                bot.send_message(target_id, "🎉 مبروك! تم قبول توثيقك في الاتحاد.")
                for admin in ADMINS:
                    send_full_user_list(admin)
                try:
                    bot.edit_message_text(f"{call.message.text}\n\n**القرار النهائي:** تم القبول ✅", 
                                          call.message.chat.id, call.message.message_id)
                except:
                    pass
            else:
                c.execute("UPDATE users SET status='rejected' WHERE user_id=?", (target_id,))
                conn.commit()
                bot.send_message(target_id, "❌ نعتذر، تم رفض طلب توثيقك.")
                try:
                    bot.edit_message_text(f"{call.message.text}\n\n**القرار النهائي:** تم الطرد ❌", 
                                          call.message.chat.id, call.message.message_id)
                except:
                    pass
    except Exception as e:
        logging.error(f"Error in decision: {e}")
        bot.answer_callback_query(call.id, "حدث خطأ أثناء تنفيذ القرار.")
        return

    bot.answer_callback_query(call.id, "تم تنفيذ القرار")

# ================= إعداد webhook =================
def setup_webhook():
    time.sleep(3)
    webhook_url = f"{DOMAIN}/webhook"
    try:
        bot.delete_webhook()
        bot.set_webhook(url=webhook_url)
        logging.info(f"✅ Webhook set to {webhook_url}")
    except Exception as e:
        logging.error(f"❌ Failed to set webhook: {e}")

# ================= نقطة الدخول =================
if DOMAIN != "https://your-app.up.railway.app" or os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    logging.info("Production mode detected, starting webhook setup...")
    threading.Thread(target=setup_webhook, daemon=True).start()
else:
    logging.info("Running locally with polling...")
    try:
        bot.delete_webhook()
    except:
        pass
    bot.infinity_polling(skip_pending=True)
