import logging
import re
import asyncio
import os
import requests
from datetime import datetime
from PIL import Image, ImageChops, ImageStat
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler, CallbackQueryHandler, Application

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING) 

# الإعدادات الأساسية
TOKEN = '8520440293:AAHxlEGixgF2uOdLAgbpB6S5uFWgXrwAHko'
CHANNEL_USERNAME = '@Serianumber99' 
LIST_MESSAGE_ID = 219 # تم التعديل إلى 219 بناءً على طلبك
GROUP_ID = -1002588398038 
OCR_API_KEY = 'K89276173888957' # مفتاح OCR المجاني

CACHE = {
    "users": {},   
    "serials": {}, 
    "loaded": False
}

# ----------------- دوال الذكاء الاصطناعي والتشابه -----------------

def get_ocr_text(image_path):
    """إرسال الصورة لـ API لقراءتها"""
    try:
        payload = {
            'apikey': OCR_API_KEY,
            'language': 'eng',
            'isOverlayRequired': False,
        }
        with open(image_path, 'rb') as f:
            r = requests.post('https://api.ocr.space/parse/image', files={image_path: f}, data=payload, timeout=15)
        result = r.json()
        return result.get('ParsedResults')[0].get('ParsedText').lower()
    except Exception as e:
        logging.error(f"OCR Error: {e}")
        return ""

def get_tamper_score(image_path):
    """كشف المونتاج (ELA)"""
    try:
        original = Image.open(image_path).convert('RGB')
        resaved = 'temp_check.jpg'
        original.save(resaved, 'JPEG', quality=90)
        resaved_img = Image.open(resaved)
        diff = ImageChops.difference(original, resaved_img)
        stat = ImageStat.Stat(diff)
        if os.path.exists(resaved): os.remove(resaved)
        return sum(stat.mean)
    except Exception as e:
        logging.error(f"Tamper Check Error: {e}")
        return 0

def get_longest_common_substring(s1, s2):
    """حساب أطول سلسلة تطابق متتالية"""
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
    """حساب أطول سلسلة تطابق غير متتالية"""
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

async def build_cache(bot):
    if CACHE["loaded"]: return
    count = 0
    print("⏳ بدأت عملية فحص الأرشيف...")
    for msg_id in range(1, LIST_MESSAGE_ID + 1):
        try:
            msg = await bot.forward_message(chat_id=GROUP_ID, from_chat_id=CHANNEL_USERNAME, message_id=msg_id)
            text = (msg.text or msg.caption or "").lower()
            date = (msg.forward_date or msg.date).replace(tzinfo=None)
            
            user_match = re.search(r"@[\w\d_]+", text)
            serial_match = re.search(r"([a-z0-9]{5,})", text) 
            
            if user_match:
                u = user_match.group(0)
                s = serial_match.group(0) if serial_match else "unknown"
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 بوت الفحص الذكي جاهز للعمل!")

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CACHE["loaded"]:
        await update.message.reply_text("⏳ جاري تحديث بيانات الأرشيف.. حاول بعد لحظات.")
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

    # التحقق من 15 يوم
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

    await update.message.reply_text("✅ تم استلام طلبك، يتم فحصه عبر الذكاء الاصطناعي...")

    # تنزيل الميديا للفحص
    is_photo = bool(update.message.photo)
    file_obj = await update.message.photo[-1].get_file() if is_photo else await update.message.video.get_file()
    temp_path = f"temp_{update.message.chat_id}.{'jpg' if is_photo else 'mp4'}"
    await file_obj.download_to_drive(temp_path)

    # 1. فحص الذكاء الاصطناعي (متاح للصور فقط)
    ai_status = "📹 **فيديو:** لا يدعم الفحص التلقائي للنص والمونتاج."
    if is_photo:
        tamper_score = get_tamper_score(temp_path)
        ocr_text = get_ocr_text(temp_path)
        
        if tamper_score > 15:
            ai_status = "⚠️ **مونتاج / فوتوشوب:** تم كشف تلاعب في الصورة!"
        elif new_serial not in ocr_text.replace(" ", ""):
            ai_status = f"❌ **غلط تماماً:** الرقم المكتوب غير موجود في الصورة!"
        else:
            ai_status = "✅ **حقيقي:** الصورة سليمة والرقم مطابق."

    if os.path.exists(temp_path):
        os.remove(temp_path)

    # 2. فحص التشابه المتقدم
    similarity_warnings = []
    for old_serial, old_user in CACHE["serials"].items():
        if old_serial == new_serial: continue 
        consecutive = get_longest_common_substring(new_serial, old_serial)
        non_consecutive = get_lcs_length(new_serial, old_serial)
        
        if consecutive >= 3:
            similarity_warnings.append(f"- `@{old_user}`: متشابه متتالي ({consecutive} أحرف)")
        elif non_consecutive >= 5:
            similarity_warnings.append(f"- `@{old_user}`: متشابه متقاطع ({non_consecutive} أحرف)")
            
    sim_text = "✅ لا يوجد تشابه خطير" if not similarity_warnings else "\n".join(similarity_warnings[:5]) # عرض أول 5 تحذيرات فقط

    # إعداد رسالة الأدمن
    keyboard = [[
        InlineKeyboardButton("✅ قبول", callback_data=f"ok_{update.message.chat_id}"),
        InlineKeyboardButton("❌ رفض", callback_data=f"no_{update.message.chat_id}")
    ]]
    
    context.bot_data[f"data_{update.message.chat_id}"] = {"u": new_user, "s": new_serial, "type": action_type}

    final_caption = (
        f"📝 **طلب فحص:**\n{found_info}\n"
        f"👤 اليوزر: {new_user}\n"
        f"🔢 السيريال: {new_serial}\n"
        f"🆔 ID: `{update.message.chat_id}`\n\n"
        f"**🤖 فحص الذكاء الاصطناعي:**\n{ai_status}\n\n"
        f"**🔍 فحص التشابه المتقدم:**\n{sim_text}"
    )

    # إرسال الصورة أو الفيديو للجروب
    if is_photo:
        await context.bot.send_photo(
            chat_id=GROUP_ID,
            photo=update.message.photo[-1].file_id,
            caption=final_caption,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await context.bot.send_video(
            chat_id=GROUP_ID,
            video=update.message.video.file_id,
            caption=final_caption,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # تمت إزالة قيد الـ ADMIN_USERNAMES للجميع في الجروب
    
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
            await context.bot.send_message(chat_id=GROUP_ID, text=f"✅ تم تنفيذ طلب {user_info['u']} بواسطة @{query.from_user.username}")
    elif action == "no":
        await context.bot.send_message(chat_id=GROUP_ID, text=f"الرد على هذه الرسالة بسبب الرفض لـ `{uid}`:", reply_markup=ForceReply(selective=True))
        await query.answer("أدخل سبب الرفض")

async def process_update(context, uid, info):
    try:
        channel_msg = await context.bot.forward_message(chat_id=GROUP_ID, from_chat_id=CHANNEL_USERNAME, message_id=LIST_MESSAGE_ID)
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
    
    # التعديل: قبول الصور أو الفيديوهات بشرط وجود كابشن (النص)
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.CAPTION, handle_registration))
    
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, handle_reject_reply))
    
    print("🤖 البوت يعمل الآن بكامل مميزات الذكاء الاصطناعي...")
    app.run_polling()

if __name__ == '__main__':
    main()
