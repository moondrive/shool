import telebot
import functools
import threading
from cfg import *
from ai_core import create_autonomous_post

bot = telebot.TeleBot(BOT_TOKEN)


def admin_only(func):
    """Декоратор: пропускает вызов только если сообщение от ADMIN_ID"""
    @functools.wraps(func)
    def wrapper(message, *args, **kwargs):
        if message.from_user.id != ADMIN_ID:
            bot.send_message(message.chat.id, "⛔ У вас нет прав для этой команды.")
            return
        return func(message, *args, **kwargs)
    return wrapper


@bot.message_handler(commands=['post'])
@admin_only
def start_post(message):
    msg = bot.send_message(message.chat.id, "📨 Пришлите сообщение (текст, фото, видео...), которое нужно опубликовать в канале:")
    bot.register_next_step_handler(msg, send_to_channel)


def send_to_channel(message):
    try:
        bot.copy_message(chat_id=CHANNEL_ID, from_chat_id=message.chat.id, message_id=message.message_id)
        bot.send_message(message.chat.id, "Опубликовано в канале!")
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка при отправке: {e}")


@bot.message_handler(commands=['ai_post'])
@admin_only
def ai_post_handler(message):
    """
    Команда /ai_post <тема>.
    Запускает автономную AI-цепочку и публикует результат в канале.
    """
    # Извлекаем тему из сообщения (всё после /ai_post)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id,
                         "Укажи тему!\n"
                         "Пример: `/ai_post Нейросети`",
                         parse_mode="Markdown")
        return

    topic = parts[1].strip()
    status_msg = bot.send_message(
        message.chat.id,
        f"Генерирую пост на тему «{topic}»...\n"
        "Это займёт 20-40 секунд."
    )

    def generate_and_send():
        """Генерация в отдельном потоке, чтобы не блокировать бота."""
        try:
            post_text = create_autonomous_post(topic)

            # Отправляем в канал
            bot.send_message(CHANNEL_ID, post_text)

            # Уведомляем админа
            bot.edit_message_text(
                f"Пост на тему «{topic}» опубликован в канале!",
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id
            )
        except Exception as e:
            bot.edit_message_text(
                f"Ошибка генерации: {e}",
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id
            )

    # Запускаем в фоне
    thread = threading.Thread(target=generate_and_send, daemon=True)
    thread.start()


if __name__ == '__main__':
    print("Бот-отправитель запущен...")
    bot.infinity_polling()

