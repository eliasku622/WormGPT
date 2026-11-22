import os
import requests
import json
import time
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# === Config / Env ===
CONFIG_FILE = "wormgpt_config.json"
PROMPT_FILE = "system-prompt.txt"
USER_LANG_FILE = "user_langs.json"

MODEL_CONFIG = {
    "name": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "base_url": "https://openrouter.ai/api/v1",
    "key": os.getenv("OPENROUTER_KEY"),
}

SITE_URL = "https://github.com/jailideaid/WormGPT"
SITE_NAME = "WormGPT CLI [ Dangerous And Unsafe ⚠️ ]"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# === Anti-Flood ===
LAST_MESSAGE_TIME = {}
FLOOD_DELAY = 3


# === Load base system prompt ===
if os.path.exists(PROMPT_FILE):
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        BASE_PROMPT = f.read()
else:
    BASE_PROMPT = "You are WormGPT running on Telegram."

# === Memory System ===
MEMORY_FILE = "chat_memory.json"

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_memory(data):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Failed to save memory:", e)

CHAT_MEMORY = load_memory()


def add_to_history(user_id: str, role: str, content: str):
    if user_id not in CHAT_MEMORY:
        CHAT_MEMORY[user_id] = []

    CHAT_MEMORY[user_id].append({"role": role, "content": content})

    # Limit 20 pesan saja biar ga boros token
    if len(CHAT_MEMORY[user_id]) > 20:
        CHAT_MEMORY[user_id] = CHAT_MEMORY[user_id][-20:]

    save_memory(CHAT_MEMORY)

# === Ensure user language storage exists ===
USER_LANGS = {}
if Path(USER_LANG_FILE).exists():
    try:
        with open(USER_LANG_FILE, "r", encoding="utf-8") as f:
            USER_LANGS = json.load(f)
    except:
        USER_LANGS = {}


def save_user_langs():
    try:
        with open(USER_LANG_FILE, "w", encoding="utf-8") as f:
            json.dump(USER_LANGS, f, indent=2)
    except Exception as e:
        print("Failed to save user langs:", e)


# === Build multilingual system prompt ===
def make_system_prompt(lang_code: str) -> str:
    language_instructions = {
        "ar": (
            "Always answer in Arabic. Understand Modern Standard Arabic and Arabic "
            "dialects, including Syrian and Levantine. Match the user's dialect "
            "naturally when possible."
        ),
        "en": "Always answer in English.",
        "id": "Selalu jawab dalam Bahasa Indonesia.",
    }
    language_instruction = language_instructions.get(
        lang_code, language_instructions["id"]
    )

    return (
        BASE_PROMPT
        + "\n\n"
        + language_instruction
        + "\nBe helpful, clear, and accurate. Do not provide instructions that "
          "facilitate harm or illegal activity."
    )


# === /start handler ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_user = await context.bot.get_me()
    context.bot_data["username"] = bot_user.username  # ✅ FIX no attribute error

    keyboard = [
        [
            InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
        ],
        [
            InlineKeyboardButton("🇮🇩 Indonesian", callback_data="lang_id"),
            InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"),
        ]
    ]

    msg = (
        f"👋 Welcome {SITE_NAME}\n"
        f"\n"
        f"🤖 Model AI : DeepSeekV3\n"
        f"🌐 Repo : {SITE_URL}\n"
        f"\n"
        f"Please choose your language / Silakan pilih bahasa:"
    )

    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))


# === Language Callback ===
async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)

    if query.data == "lang_ar":
        USER_LANGS[user_id] = "ar"
        save_user_langs()
        await query.edit_message_text("✅ تم اختيار اللغة العربية.")
    elif query.data == "lang_id":
        USER_LANGS[user_id] = "id"
        save_user_langs()
        await query.edit_message_text("✅ Bahasa Indonesia dipilih.")
    elif query.data == "lang_en":
        USER_LANGS[user_id] = "en"
        save_user_langs()
        await query.edit_message_text("✅ English selected.")
    else:
        await query.edit_message_text("Error. Use /start again.")


# === Get Language ===
def get_user_lang(user_id: int) -> str:
    return USER_LANGS.get(str(user_id), "id")


# === Message Handler ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot_data.get("username", "")
    user_id = update.message.from_user.id
    user_msg = update.message.text or ""
    chat_type = update.message.chat.type

    # === Anti Flood ===
    now = time.time()
    last = LAST_MESSAGE_TIME.get(user_id, 0)

    if now - last < FLOOD_DELAY:
        await update.message.reply_text("⏳ Slowmode active (3 sec). Please wait...")
        return

    LAST_MESSAGE_TIME[user_id] = now

    # === Must mention bot in group ===
    if chat_type in ["group", "supergroup"]:
        if not user_msg.startswith("/") and f"@{bot_username}" not in user_msg:
            return  # ignore

    # === Build system prompt ===
    lang = get_user_lang(user_id)
    system_prompt = make_system_prompt(lang)

    payload = {
        "model": MODEL_CONFIG["name"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
    }

    headers = {
        "Authorization": f"Bearer {MODEL_CONFIG['key']}",
        "Content-Type": "application/json",
    }

    try:
        await update.message.chat.send_action("typing")
    except:
        pass

    try:
        res = requests.post(
            f"{MODEL_CONFIG['base_url']}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )

        if res.status_code != 200:
            reply = f"⚠️ API ERROR {res.status_code}\n{res.text}"
        else:
            data = res.json()
            reply = data["choices"][0]["message"]["content"]

    except Exception as e:
        reply = f"❌ Request failed: {e}"

    await update.message.reply_text(reply)


# === /setlang command ===
async def setlang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        return await update.message.reply_text("Usage: /setlang ar | id | en")

    user_id = str(update.message.from_user.id)
    code = args[0].lower()

    if code not in ("ar", "id", "en"):
        return await update.message.reply_text("Unknown language. Use ar, id, or en.")

    USER_LANGS[user_id] = code
    save_user_langs()
    await update.message.reply_text(f"✅ Language set: {code}")


# === Build App ===
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))
app.add_handler(CommandHandler("setlang", setlang_cmd))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# === Run Bot ===
def run_bot():
    print("🚀 WormGPT Bot Running... (DeepSeek)")
    app.run_polling()
