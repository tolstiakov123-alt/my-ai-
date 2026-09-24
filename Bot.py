import os
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI
import httpx

# --- НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = "nvidia/nemotron-3.5-lightning:free"  # бесплатная модель

# --- КЛИЕНТ ДЛЯ ИИ ---
client = AsyncOpenAI(
    api_key=OPENROUTER_KEY,
    base_url="https://openrouter.ai/api/v1"
)

# --- БАЗА ДАННЫХ ДЛЯ ПАМЯТИ ---
DB_FILE = "chat_history.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  role TEXT,
                  content TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def save_message(user_id, role, content):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
              (user_id, role, content))
    conn.commit()
    conn.close()

def get_history(user_id, limit=30):
    """Возвращает последние N сообщений для контекста."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""SELECT role, content FROM messages
                 WHERE user_id = ?
                 ORDER BY id DESC LIMIT ?""", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    # Переворачиваем, чтобы хронология была верной
    return [{"role": r, "content": c} for r, c in reversed(rows)]

# --- ПОИСК В ИНТЕРНЕТЕ (простой, без ключей) ---
async def web_search(query: str) -> str:
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1},
                timeout=10.0
            )
            data = resp.json()
            if data.get("AbstractText"):
                return data["AbstractText"]
    except Exception:
        pass
    return ""

# --- ОБРАБОТЧИК СООБЩЕНИЙ ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    # Сохраняем сообщение пользователя
    save_message(user_id, "user", user_text)

    # Проверяем, не нужен ли поиск в интернете
    search_result = ""
    trigger_words = ["новости", "погода", "курс", "что случилось", "последние"]
    if any(w in user_text.lower() for w in trigger_words):
        search_result = await web_search(user_text)

    # Формируем контекст для ИИ
    history = get_history(user_id, limit=20)
    system_prompt = "Ты — личный ассистент. Отвечай кратко, по делу, помни контекст."
    if search_result:
        system_prompt += f"\n\nАктуальная информация из интернета: {search_result}"

    messages = [{"role": "system", "content": system_prompt}] + history

    # Запрос к ИИ
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=1000
        )
        ai_reply = response.choices[0].message.content
    except Exception as e:
        ai_reply = "Извини, произошла ошибка. Попробуй ещё раз."

    # Сохраняем ответ ИИ и отправляем
    save_message(user_id, "assistant", ai_reply)
    await update.message.reply_text(ai_reply)

# --- ЗАПУСК ---
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling()
