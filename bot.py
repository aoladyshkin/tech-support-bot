
import logging
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeChat

# Загружаем переменные окружения из .env файла
load_dotenv()
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Переменные состояния (в реальном приложении лучше использовать БД)
# Словарь для хранения активных диалогов: {user_id: admin_id}
active_chats = {}
# Обратный словарь для удобства: {admin_id: user_id}
admin_to_user = {}

# Загрузка конфигурации
try:
    BOT_TOKEN = os.environ["BOT_TOKEN"]
    ADMIN_IDS_RAW = os.environ["ADMIN_USER_IDS"]
    ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS_RAW.split(",")]
    if not ADMIN_IDS:
        raise ValueError("Список ADMIN_USER_IDS не может быть пустым.")
except (KeyError, ValueError) as e:
    raise ValueError(f"Ошибка в переменных окружения: {e}. Убедитесь, что BOT_TOKEN и ADMIN_USER_IDS заданы корректно.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет приветственное сообщение при команде /start."""
    await update.message.reply_text(
        "Здравствуйте! Это бот технической поддержки. "
        "Опишите вашу проблему, и мы постараемся помочь."
    )

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает сообщения от пользователя."""
    user = update.message.from_user
    user_id = user.id

    # Если пользователь уже в активном диалоге, просто пересылаем сообщение админу
    if user_id in active_chats:
        admin_id = active_chats[user_id]
        await context.bot.forward_message(
            chat_id=admin_id,
            from_chat_id=user_id,
            message_id=update.message.message_id
        )
        return

    # Создание нового тикета и рассылка всем админам
    text = f"Новый тикет от пользователя {user.full_name} (ID: {user_id})."
    
    keyboard = [
        [InlineKeyboardButton("Ответить на тикет", callback_data=f"start_chat_{user_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    for admin_id in ADMIN_IDS:
        try:
            # Отправляем информацию о тикете
            await context.bot.send_message(chat_id=admin_id, text=text)
            # Пересылаем исходное сообщение
            await context.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=user_id,
                message_id=update.message.message_id
            )
            # Отправляем кнопку для ответа
            await context.bot.send_message(chat_id=admin_id, text="Нажмите, чтобы начать диалог:", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение админу {admin_id}: {e}")

    await update.message.reply_text("Ваше сообщение отправлено администраторам. Ожидайте ответа.")


async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает сообщения от админа."""
    admin_id = update.message.from_user.id

    # Проверяем, есть ли у админа активный диалог
    if admin_id in admin_to_user:
        user_id = admin_to_user[admin_id]
        # Пересылаем сообщение пользователя
        await context.bot.send_message(chat_id=user_id, text=update.message.text)
    else:
        await update.message.reply_text(
            "Вы не ведете активный диалог. Чтобы ответить пользователю, "
            "нажмите на кнопку «Ответить на тикет» под его сообщением."
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатия на inline-кнопки."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    admin_id = query.from_user.id

    if data.startswith("start_chat_"):
        user_id = int(data.split("_")[2])

        # Проверяем, не занят ли этот админ другим диалогом
        if admin_id in admin_to_user:
            await query.edit_message_text(text=f"Вы уже ведете диалог с пользователем {admin_to_user[admin_id]}. Завершите его командой /close_ticket.")
            return
        
        # Проверяем, не ответил ли уже кто-то другой на этот тикет
        if user_id in active_chats:
            await query.edit_message_text(text=f"Этот тикет уже был взят в работу администратором {active_chats[user_id]}.")
            return

        # Устанавливаем связь
        active_chats[user_id] = admin_id
        admin_to_user[admin_id] = user_id

        await query.edit_message_text(text=f"Вы начали диалог с пользователем {user_id}. "
                                           f"Все ваши следующие сообщения будут пересылаться ему. "
                                           f"Для завершения используйте /close_ticket.")
        
        # Уведомляем пользователя
        await context.bot.send_message(chat_id=user_id, text="Администратор подключился к вашему диалогу.")


async def close_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Закрывает активный тикет."""
    admin_id = update.message.from_user.id

    if admin_id in admin_to_user:
        user_id = admin_to_user.pop(admin_id)
        if user_id in active_chats:
            del active_chats[user_id]
        
        await update.message.reply_text("Диалог успешно завершен.")
        await context.bot.send_message(chat_id=user_id, text="Ваш диалог с администратором завершен. Если у вас остались вопросы, просто напишите их снова.")
    else:
        await update.message.reply_text("У вас нет активных диалогов.")


async def post_init_setup(application: Application) -> None:
    """Устанавливает меню команд после инициализации."""
    # Команды для обычных пользователей
    user_commands = [
        BotCommand("start", "Начать / Перезапустить")
    ]
    await application.bot.set_my_commands(user_commands)

    # Расширенные команды для админов
    admin_commands = [
        BotCommand("start", "Начать / Перезапустить"),
        BotCommand("close_ticket", "Закрыть активный диалог")
    ]
    for admin_id in ADMIN_IDS:
        try:
            await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:
            logger.warning(f"Не удалось установить команды для админа {admin_id}: {e}")


def main() -> None:
    """Запуск бота."""
    application = Application.builder().token(BOT_TOKEN).post_init(post_init_setup).build()

    # Фильтр для сообщений от админов
    admin_filter = filters.User(user_id=ADMIN_IDS)
    # Фильтр для сообщений от обычных пользователей
    user_filter = ~admin_filter & filters.TEXT & ~filters.COMMAND

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("close_ticket", close_ticket, filters=admin_filter))

    # Обработчики сообщений
    application.add_handler(MessageHandler(user_filter, handle_user_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & admin_filter, handle_admin_message))

    # Обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^start_chat_"))

    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()
