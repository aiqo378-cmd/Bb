import logging
import re
import asyncio
import os
import requests
import cv2  # مكتبة معالجة الفيديوهات
from datetime import datetime
from PIL import Image, ImageChops, ImageStat

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler, Application

from telethon import TelegramClient
from telethon.sessions import StringSession

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING) 

# الإعدادات الأساسية للبوت
TOKEN = '8520440293:AAHxlEGixgF2uOdLAgbpB6S5uFWgXrwAHko'
CHANNEL_USERNAME = '@Serianumber99' 
LIST_MESSAGE_ID = 219 
GROUP_ID = -1002588398038 
OCR_API_KEY = 'K89276173888957'

# إعدادات حساب Telethon (الجلسة الصامتة)
API_ID = 26604893 
API_HASH = 'b4dad6237531036f1a4bb2580e4985b1'
STRING_SESSION = '1BJWap1wBuzwi_AQfbsYmVPJS4VjOwS-QqQuPQFhgRHx2ZcA65CIwl0TGqPOZjGfFqCfCIs5ED2dYi1MpA3mweKcRXtKCCL94j_geb1d9l5a54JPAtRNTrRhm9wQxBCVOh0MF-u5avJWWU_YI1VwHUC8g4dOGlHwiu10lp0F9DsMpYzzdBS5DCjeEP2VllZfgnr1dSWBGYN_yp-jdZrlcxZRNHCwcs276Mu7U30qp9rj0sP31S4WBwZfP3U7FxLuEgj-ZVTVrnsCRGkGEM-4hQzyLqbPM9GpdPX0PuEtc-eqlUjn_e2uvASEAU6yuk98RfH1xgKT2pdbJvjY2HLVDo2O-ymQ-s0U='

t_client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

CACHE = {
    "users": {},   
    "serials": {}, 
    "loaded": False
}

# ----------------- دوال الذكاء الاصطناعي والتشابه -----------------

def get_ocr_text(image_path):
    try:
        payload = {'apikey': OCR_API_KEY, 'language': 'eng', 'isOverlayRequired': False}
        with open(image_path, 'rb') as f:
            r = requests.post('https://api.ocr.space/parse/image', files={image_path: f}, data=payload, timeout=15)
        result = r.json()
        return result.get('ParsedResults')[0].get('ParsedText').lower()
    except Exception:
        return ""

def get_tamper_score(image_path):
    try:
        original = Image.open(image_path).convert('RGB')
        resaved = 'temp_check.jpg'
        original.save(resaved, 'JPEG', quality=90)
        resaved_img = Image.open(resaved)
        diff = ImageChops.difference(original, resaved_img)
        stat = ImageStat.Stat(diff)
        if os.path.exists(resaved): os.remove(resaved)
        return sum(stat.mean)
    except Exception:
        return 0

def process_video_ai(video_path):
    """استخراج إطارات من الفيديو لفحص المونتاج وقراءة النص"""
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened(): return 0, ""
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames == 0: return 0, ""
            
        # أخذ لقطة من منتصف الفيديو لضمان وضوح الشاشة
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
        ret, frame = cap.read()
        ocr_text = ""
        max_tamper = 0
        
        if ret:
            temp_frame = "temp_vid_frame.jpg"
            cv2.imwrite(temp_frame, frame)
            ocr_text = get_ocr_text(temp_frame)
            max_tamper = get_tamper_score(temp_frame)
            if os.path.exists(temp_frame): os.remove(temp_frame)
            
        cap.release()
        return max_tamper, ocr_text
    except Exception as e:
        logging.error(f"Video AI Error: {e}")
        return 0, ""

def get_longest_common_substring(s1, s2):
    m = [[0] * (1 + len(s2)) for _ in range(1 + len(s1))]
    longest = 0
    for x in range(1, 1 + len(s1)):
        for y in range(1, 1 + len(s2)):
            if s1[x - 1] == s2[y - 1]:
                m[x][y] = m[x - 1][y - 1] + 1
                longest = max(longest, m[x][y])
            else:
                m[x][y] = 0
    return longest

def get_lcs_length(s1, s2):
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i-1] == s2[j-1]:
                dp[i][j] = dp[i-1][j-1] + 1
            else:
                dp[i][j] = max(dp[i-1][j], dp[i][j-1])
    return dp[m][n]

# ----------------- دوال البوت الأساسية -----------------

async def build_cache_silently():
    """استخدام جلسة تيليثون لجلب الأرشيف بصمت تام بدون توجيه رسائل"""
    if CACHE["loaded"]: return
    print("⏳ الجلسة الصامتة: جاري قراءة القائمة وتحديث قاعدة البيانات...")
    try:
        # جلب الرسالة المحددة من القناة مباشرة
        message = await t_client.get_messages(CHANNEL_USERNAME, ids=LIST_MESSAGE_ID)
        if message and message.text:
            lines = message.text.split('\n')
            count = 0
            for line in lines:
                user_match = re.search(r"@[\w\d_]+", line)
                serial_match = re.search(r"\|\s*([a-zA-Z0-9]{5,})", line)
                
                if user_match and serial_match:
                    u = user_match.group(0).lower()
                    s = serial_match.group(1).lower()
                    CACHE["users"][u] = {"serial": s, "date": message.date.replace(tzinfo=None), "msg_id": LIST_MESSAGE_ID}
                    CACHE["serials"][s] = u
                    count += 1
            CACHE["loaded"] = True
            print(f"✅ تم تحديث الكاش بصمت: {count} لاعب مفهرس.")
    except Exception as e:
        print(f"❌ خطأ في الجلسة الصامتة: {e}")

async def post_init(application: Application):
    await t_client.connect() # ربط حساب التيليثون
    asyncio.create_task(build_cache_silently())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 بوت الفحص الذكي (المدعوم بالذكاء الاصطناعي للفيديوهات والصور) جاهز!")

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CACHE["loaded"]:
        await update.message.reply_text("⏳ جاري تهيئة الذكاء الاصطناعي والجلسة.. جرب بعد ثوانٍ.")
        return

    if not update.message.caption: return
    
    raw_input = update.message.caption.strip()
    match = re.match(r"^(@[\w\d_]+)\s*[|/-]?\s*([\w\d_/]+)$", raw_input)
    
    if not match:
        await update.message.reply_text("❌ تنسيق خاطئ! أرسل: `@يوزر | السيريال` مع الصورة أو الفيديو.")
        return

    new_user = match.group(1).lower()
    new_serial = match.group(2).lower()
    
    action_type = "NEW"
    found_info = "✅ لاعب جديد بالكامل."

    user_data = CACHE["users"].get(new_user)
    serial_owner = CACHE["serials"].get(new_serial)

    if user_data and user_data['serial'] == new_serial:
        await update.message.reply_text("⚠️ هذا اللاعب مسجل مسبقاً بنفس البيانات.")
        return

    if user_data: 
        if user_data['serial'] != new_serial:
            diff = datetime.utcnow() - user_data['date']
            if diff.days < 15:
                days_left = 15 - diff.days
                await update.message.reply_text(f"❌ لا يمكنك تغيير التسلسلي إلا كل 15 يوم.\n⏳ متبقي: {days_left} يوم.")
                return
            action_type = "CHANGE_SERIAL"
            found_info = f"🔄 تغيير تسلسلي (مرّ أكثر من 15 يوم)."
    elif serial_owner: 
        action_type = "CHANGE_USER"
        found_info = f"🔄 تغيير يوزر لنفس الجهاز."

    loading_msg = await update.message.reply_text("✅ تم الاستلام.. 🤖 جاري فحص (التشابه + التلاعب) يرجى الانتظار...")

    is_photo = bool(update.message.photo)
    file_obj = await update.message.photo[-1].get_file() if is_photo else await update.message.video.get_file()
    temp_path = f"temp_media_{update.message.chat_id}.{'jpg' if is_photo else 'mp4'}"
    await file_obj.download_to_drive(temp_path)

    # 1. فحص الذكاء الاصطناعي للصور والفيديوهات
    if is_photo:
        tamper_score = get_tamper_score(temp_path)
        ocr_text = get_ocr_text(temp_path)
    else:
        tamper_score, ocr_text = process_video_ai(temp_path)

    if tamper_score > 15:
        ai_status = "⚠️ **مونتاج / تلاعب:** تم كشف تعديل أو فوتوشوب في المرفق!"
    elif new_serial not in ocr_text.replace(" ", ""):
        ai_status = f"❌ **غلط تماماً:** الرقم المكتوب غير موجود في (الصورة/الفيديو)!"
    else:
        ai_status = "✅ **حقيقي:** المرفق سليم والرقم مطابق تماماً."

    if os.path.exists(temp_path): os.remove(temp_path)

    # 2. فحص التشابه المتقدم للتسلسلي
    similarity_warnings = []
    for old_serial, old_user in CACHE["serials"].items():
        if old_serial == new_serial: continue 
        consecutive = get_longest_common_substring(new_serial, old_serial)
        non_consecutive = get_lcs_length(new_serial, old_serial)
        
        if consecutive >= 3:
            similarity_warnings.append(f"⚠️ `@{old_user}`: متشابه מתتالي ({consecutive} أحرف)")
        elif non_consecutive >= 5:
            similarity_warnings.append(f"⚠️ `@{old_user}`: متشابه متقاطع ({non_consecutive} أحرف)")
            
    sim_text = "✅ لا يوجد تشابه خطير" if not similarity_warnings else "\n".join(similarity_warnings[:5])

    # إعداد الإرسال للجروب
    keyboard = [[
        InlineKeyboardButton("✅ قبول", callback_data=f"ok_{update.message.chat_id}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"no_{update.message.chat_id}")
    ]]
    
    context.bot_data[f"data_{update.message.chat_id}"] = {"u": new_user, "s": new_serial, "type": action_type}

    final_caption = (
        f"📝 **طلب فحص جديد:**\n{found_info}\n"
        f"👤 اليوزر: {new_user}\n"
        f"🔢 السيريال: `{new_serial}`\n"
        f"🆔 ID: `{update.message.chat_id}`\n\n"
        f"**🤖 فحص الذكاء الاصطناعي:**\n{ai_status}\n\n"
        f"**🔍 فحص التشابه المتقدم:**\n{sim_text}"
    )

    await loading_msg.delete()

    if is_photo:
        await context.bot.send_photo(chat_id=GROUP_ID, photo=update.message.photo[-1].file_id, caption=final_caption, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_video(chat_id=GROUP_ID, video=update.message.video.file_id, caption=final_caption, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    action, uid = data[0], data[1]
    user_info = context.bot_data.get(f"data_{uid}")

    if not user_info:
        await query.answer("بيانات الطلب منتهية.", show_alert=True)
        return

    if action == "ok":
        success = await process_update(context, uid, user_info)
        if success:
            await query.message.delete()
            await context.bot.send_message(chat_id=GROUP_ID, text=f"✅ تم تنفيذ طلب {user_info['u']} بواسطة @{query.from_user.username}")
    elif action == "no":
        await context.bot.send_message(chat_id=GROUP_ID, text=f"الرد على هذه الرسالة بسبب الرفض لـ `{uid}`:", reply_markup=ForceReply(selective=True))
        await query.answer("أدخل سبب الرفض")

async def process_update(context, uid, info):
    try:
        # استخدام الجلسة لجلب الرسالة بصمت بدلاً من توجيهها
        message = await t_client.get_messages(CHANNEL_USERNAME, ids=LIST_MESSAGE_ID)
        lines = message.text.split('\n')

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
            # تعديل الرسالة مباشرة عبر البوت
            await context.bot.edit_message_text(chat_id=CHANNEL_USERNAME, message_id=LIST_MESSAGE_ID, text=new_text)
            
            CACHE["users"][target_u] = {"serial": target_s, "date": datetime.utcnow(), "msg_id": LIST_MESSAGE_ID}
            CACHE["serials"][target_s] = target_u
            await context.bot.send_message(chat_id=int(uid), text="✅ تم قبول طلبك وتحديث بياناتك في القائمة!")
            return True
    except Exception as e:
        logging.error(f"Error in process: {e}")
    return False

async def handle_reject_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != GROUP_ID or not update.message.reply_to_message: return
    if "سبب الرفض" in update.message.reply_to_message.text:
        match = re.search(r"`(\d+)`", update.message.reply_to_message.text)
        if match:
            uid = match.group(1)
            reason = update.message.text
            await context.bot.send_message(chat_id=int(uid), text=f"❌ تم رفض طلبك.\n**السبب:** {reason}")
            await update.message.reply_text("✅ تم إبلاغ اللاعب بالرفض.")

def main():
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.CAPTION, handle_registration))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, handle_reject_reply))
    
    print("🤖 البوت يعمل الآن.. يتم استخدام الجلسة في الخلفية بصمت تام.")
    app.run_polling()

if __name__ == '__main__':
    main()
