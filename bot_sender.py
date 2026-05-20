import telebot
import functools
import threading
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

import db
from cfg import *
from ai_core import create_posts_per_article, revise_post

# ─── Инициализация ────────────────────────────────────────────────────────────

db.init_db()
bot = telebot.TeleBot(BOT_TOKEN)

# Посты ожидающие решения: {message_id: {"text": str, "topic": str}}
pending_posts: dict[int, dict] = {}

PAGE_SIZE = 5  # постов на странице архива


# ─── Утилиты ─────────────────────────────────────────────────────────────────

def admin_only(func):
    """Декоратор: пропускает вызов только если сообщение от ADMIN_ID."""
    @functools.wraps(func)
    def wrapper(message, *args, **kwargs):
        if message.from_user.id != ADMIN_ID:
            bot.send_message(message.chat.id, "⛔ У вас нет прав для этой команды.")
            return
        return func(message, *args, **kwargs)
    return wrapper


def make_review_keyboard(msg_id: int) -> InlineKeyboardMarkup:
    """Кнопки для поста на этапе проверки (2 ряда)."""
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"pub:{msg_id}"),
        InlineKeyboardButton("📁 В архив",      callback_data=f"arc:{msg_id}"),
    )
    kb.row(
        InlineKeyboardButton("✏️ Доработать",   callback_data=f"rev:{msg_id}"),
        InlineKeyboardButton("🗑 Удалить",       callback_data=f"del:{msg_id}"),
    )
    return kb


def make_archive_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Кнопки для поста из архива (2 ряда)."""
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"apub:{post_id}"),
        InlineKeyboardButton("✏️ Доработать",   callback_data=f"arev:{post_id}"),
    )
    kb.row(
        InlineKeyboardButton("🗑 Удалить из архива", callback_data=f"adel:{post_id}"),
    )
    return kb


def make_pagination_keyboard(offset: int, total: int) -> InlineKeyboardMarkup | None:
    """Кнопки листания архива. None если страница одна."""
    has_prev = offset > 0
    has_next = offset + PAGE_SIZE < total
    if not has_prev and not has_next:
        return None
    kb = InlineKeyboardMarkup()
    row = []
    if has_prev:
        row.append(InlineKeyboardButton("◀️ Назад", callback_data=f"apage:{offset - PAGE_SIZE}"))
    if has_next:
        row.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"apage:{offset + PAGE_SIZE}"))
    kb.row(*row)
    return kb


def send_archive_page(chat_id: int, admin_id: int, offset: int) -> None:
    """Отправляет страницу архива: шапку + посты + пагинацию."""
    total = db.count_archived(admin_id)
    if total == 0:
        bot.send_message(chat_id, "📭 Архив пуст.")
        return

    posts      = db.get_archived_posts(admin_id, limit=PAGE_SIZE, offset=offset)
    page_num   = offset // PAGE_SIZE + 1
    page_total = (total + PAGE_SIZE - 1) // PAGE_SIZE

    bot.send_message(
        chat_id,
        f"📁 <b>Архив</b> — {total} постов  |  стр. {page_num}/{page_total}",
        parse_mode="HTML",
    )
    for post in posts:
        header = f"<i>🗂 {post['topic']} · {post['created_at']}</i>\n\n" if post["topic"] else ""
        bot.send_message(
            chat_id,
            header + post["post_text"],
            parse_mode="HTML",
            reply_markup=make_archive_keyboard(post["id"]),
        )

    nav_kb = make_pagination_keyboard(offset, total)
    if nav_kb:
        bot.send_message(chat_id, "─────", reply_markup=nav_kb)


def _send_revised(chat_id: int, revised_text: str, topic: str,
                  original_msg_id: int | None = None) -> None:
    """
    Отправляет доработанный пост с полными кнопками проверки.
    Убирает кнопки у оригинального сообщения, если указан original_msg_id.
    """
    if original_msg_id:
        try:
            bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=original_msg_id,
                reply_markup=None,
            )
        except Exception:
            pass

    sent = bot.send_message(chat_id, revised_text, parse_mode="HTML")
    pending_posts[sent.message_id] = {"text": revised_text, "topic": topic}
    bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=sent.message_id,
        reply_markup=make_review_keyboard(sent.message_id),
    )


# ─── Ручная публикация (/post) ────────────────────────────────────────────────

@bot.message_handler(commands=["post"])
@admin_only
def start_post(message):
    msg = bot.send_message(
        message.chat.id,
        "📨 Пришлите сообщение (текст, фото, видео...), которое нужно опубликовать в канале:",
    )
    bot.register_next_step_handler(msg, send_to_channel)


def send_to_channel(message):
    try:
        bot.copy_message(
            chat_id=CHANNEL_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        bot.send_message(message.chat.id, "✅ Опубликовано в канале!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка при отправке: {e}")


# ─── AI-публикация (/ai_post) ─────────────────────────────────────────────────

@bot.message_handler(commands=["ai_post"])
@admin_only
def ai_post_handler(message):
    """Команда /ai_post <тема> — генерирует посты по всем найденным статьям."""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(
            message.chat.id,
            "Укажи тему!\nПример: `/ai_post Нейросети`",
            parse_mode="Markdown",
        )
        return

    topic = parts[1].strip()
    status_msg = bot.send_message(
        message.chat.id,
        f"🔄 Ищу статьи и генерирую посты на тему <b>«{topic}»</b>...\n"
        "Это займёт 30–90 секунд.",
        parse_mode="HTML",
    )

    def generate_and_send():
        try:
            posts = create_posts_per_article(topic)
            if not posts:
                bot.edit_message_text(
                    "❌ Не удалось найти статьи или сгенерировать посты.",
                    chat_id=status_msg.chat.id,
                    message_id=status_msg.message_id,
                )
                return

            bot.edit_message_text(
                f"✅ Готово! Сгенерировано <b>{len(posts)}</b> постов.\n"
                "Выбери, что делать с каждым:",
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
                parse_mode="HTML",
            )
            for post_text in posts:
                if not post_text or post_text.startswith("❌"):
                    continue
                sent = bot.send_message(ADMIN_ID, post_text, parse_mode="HTML")
                pending_posts[sent.message_id] = {"text": post_text, "topic": topic}
                bot.edit_message_reply_markup(
                    chat_id=ADMIN_ID,
                    message_id=sent.message_id,
                    reply_markup=make_review_keyboard(sent.message_id),
                )
        except Exception as e:
            bot.edit_message_text(
                f"❌ Ошибка генерации: {e}",
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
            )

    threading.Thread(target=generate_and_send, daemon=True).start()


# ─── Просмотр архива (/drafts) ────────────────────────────────────────────────

@bot.message_handler(commands=["drafts"])
@admin_only
def drafts_handler(message):
    """Показывает первую страницу архива отложенных постов."""
    send_archive_page(message.chat.id, message.from_user.id, offset=0)


# ─── Кнопки — проверка поста ─────────────────────────────────────────────────

@bot.callback_query_handler(
    func=lambda call: call.data.startswith(("pub:", "arc:", "rev:", "del:"))
)
def handle_review_action(call):
    """✅ / 📁 / ✏️ / 🗑 — на этапе проверки поста."""
    action, msg_id_str = call.data.split(":", 1)
    msg_id = int(msg_id_str)
    entry  = pending_posts.get(msg_id)

    if not entry:
        bot.answer_callback_query(call.id, "⚠️ Пост уже обработан.", show_alert=True)
        return

    post_text = entry["text"]
    topic     = entry["topic"]

    # ── Опубликовать ──────────────────────────────────────────────────────────
    if action == "pub":
        try:
            bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None,
            )
            bot.send_message(
                call.message.chat.id, "✅ Опубликовано в канале!",
                reply_to_message_id=call.message.message_id,
            )
            bot.answer_callback_query(call.id, "✅ Опубликовано!")
            del pending_posts[msg_id]
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Ошибка: {e}", show_alert=True)

    # ── В архив ───────────────────────────────────────────────────────────────
    elif action == "arc":
        db.archive_post(call.from_user.id, post_text, topic)
        total = db.count_archived(call.from_user.id)
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=None,
        )
        bot.send_message(
            call.message.chat.id,
            f"📁 Сохранено в архив. Всего в архиве: <b>{total}</b> постов.\nОткрыть: /drafts",
            parse_mode="HTML",
            reply_to_message_id=call.message.message_id,
        )
        bot.answer_callback_query(call.id, "📁 Добавлено в архив")
        del pending_posts[msg_id]

    # ── Доработать ────────────────────────────────────────────────────────────
    elif action == "rev":
        bot.answer_callback_query(call.id)
        prompt_msg = bot.send_message(
            call.message.chat.id,
            "✏️ <b>Напиши комментарий для доработки:</b>\n"
            "<i>Например: «сделай короче», «добавь иронии», «убери спойлер», «смени тон»</i>",
            parse_mode="HTML",
            reply_to_message_id=call.message.message_id,
        )
        bot.register_next_step_handler(
            prompt_msg,
            process_revision_comment,
            {
                "source":          "review",
                "msg_id":          msg_id,
                "original_msg_id": call.message.message_id,
                "post_text":       post_text,
                "topic":           topic,
                "chat_id":         call.message.chat.id,
            },
        )

    # ── Удалить ───────────────────────────────────────────────────────────────
    elif action == "del":
        del pending_posts[msg_id]
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None,
            )
        bot.answer_callback_query(call.id, "🗑 Удалено")


# ─── Кнопки — архив ──────────────────────────────────────────────────────────

@bot.callback_query_handler(
    func=lambda call: call.data.startswith(("apub:", "arev:", "adel:", "apage:"))
)
def handle_archive_action(call):
    """✅ / ✏️ / 🗑 / листание — в архиве."""
    action, value = call.data.split(":", 1)
    admin_id = call.from_user.id

    # ── Опубликовать из архива ────────────────────────────────────────────────
    if action == "apub":
        post = db.get_post_by_id(int(value), admin_id)
        if not post:
            bot.answer_callback_query(call.id, "⚠️ Пост не найден.", show_alert=True)
            return
        try:
            bot.send_message(CHANNEL_ID, post["post_text"], parse_mode="HTML")
            db.delete_post(post["id"], admin_id)
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None,
            )
            bot.send_message(
                call.message.chat.id, "✅ Пост из архива опубликован в канале!",
                reply_to_message_id=call.message.message_id,
            )
            bot.answer_callback_query(call.id, "✅ Опубликовано!")
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Ошибка: {e}", show_alert=True)

    # ── Доработать из архива ──────────────────────────────────────────────────
    elif action == "arev":
        post = db.get_post_by_id(int(value), admin_id)
        if not post:
            bot.answer_callback_query(call.id, "⚠️ Пост не найден.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        prompt_msg = bot.send_message(
            call.message.chat.id,
            "✏️ <b>Напиши комментарий для доработки:</b>\n"
            "<i>Например: «сделай короче», «добавь иронии», «смени тон»</i>",
            parse_mode="HTML",
            reply_to_message_id=call.message.message_id,
        )
        bot.register_next_step_handler(
            prompt_msg,
            process_revision_comment,
            {
                "source":          "archive",
                "post_id":         post["id"],
                "original_msg_id": call.message.message_id,
                "post_text":       post["post_text"],
                "topic":           post["topic"],
                "chat_id":         call.message.chat.id,
            },
        )

    # ── Удалить из архива ─────────────────────────────────────────────────────
    elif action == "adel":
        deleted = db.delete_post(int(value), admin_id)
        if deleted:
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=None,
                )
            bot.answer_callback_query(call.id, "🗑 Удалено из архива")
        else:
            bot.answer_callback_query(call.id, "⚠️ Пост не найден.", show_alert=True)

    # ── Листание архива ───────────────────────────────────────────────────────
    elif action == "apage":
        try:
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None,
            )
        except Exception:
            pass
        send_archive_page(call.message.chat.id, admin_id, offset=int(value))
        bot.answer_callback_query(call.id)


# ─── Доработка поста по комментарию ─────────────────────────────────────────

def process_revision_comment(message, context: dict) -> None:
    """
    Вызывается после того, как пользователь отправил комментарий с правками.
    Запускает AI-доработку в отдельном потоке.
    """
    comment = (message.text or "").strip()
    if not comment:
        bot.send_message(message.chat.id, "❌ Пустой комментарий — отмена доработки.")
        return

    status_msg = bot.send_message(
        message.chat.id,
        f"⏳ Дорабатываю пост по комментарию: <i>«{comment}»</i>",
        parse_mode="HTML",
    )

    def do_revision():
        try:
            revised = revise_post(context["post_text"], comment)

            # Удаляем статус-сообщение
            try:
                bot.delete_message(message.chat.id, status_msg.message_id)
            except Exception:
                pass

            # Если доработка из архива — удаляем старую запись из БД
            if context["source"] == "archive":
                db.delete_post(context["post_id"], message.from_user.id)

            # Если доработка из проверки — убираем pending для старого поста
            if context["source"] == "review":
                pending_posts.pop(context.get("msg_id"), None)

            # Отправляем доработанный пост с полными кнопками проверки
            _send_revised(
                chat_id=context["chat_id"],
                revised_text=revised,
                topic=context["topic"],
                original_msg_id=context["original_msg_id"],
            )

        except Exception as e:
            bot.edit_message_text(
                f"❌ Ошибка доработки: {e}",
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
            )

    threading.Thread(target=do_revision, daemon=True).start()


# ─── Запуск ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Бот-отправитель запущен...")
    bot.infinity_polling()
