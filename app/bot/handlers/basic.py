"""Базовые хендлеры бота"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove
from sqlalchemy import delete

from app.bot.bot import dp
from app.database import Reminder, UserSettings
from app.database.base import AsyncSessionLocal

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я бот-напоминалка. Просто напиши что и когда — я напомню.\n\n"
        "<b>Формат:</b> <code>текст дата время</code>\n\n"
        "<b>Примеры:</b>\n"
        "• <i>позвонить маме завтра в 10:00</i>\n"
        "• <i>подъем 17.02 в 5 утра</i>\n"
        "• <i>встреча в пятницу в 15:00</i>\n"
        "• <i>выпить таблетку через 30 минут</i>\n\n"
        "<b>Периодические напоминания:</b>\n"
        "• <i>выпить кофе в 8 утра каждый день</i>\n"
        "• <i>стендап в 10:00 по будням</i>\n"
        "• <i>уборка в 11:00 по выходным</i>\n"
        "• <i>заплатить налог 20 ноября в 10:00 ежегодно</i>\n\n"
        "<b>Команды:</b>\n"
        "/list — мои напоминания\n"
        "/settings — настройки\n"
        "/help — справка",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(Command("deleteme"))
async def cmd_deleteme(message: Message):
    """Удаляет все данные пользователя"""
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Reminder).where(Reminder.user_id == user_id))
        await session.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
        await session.commit()
    await message.answer(
        "🗑 Все ваши данные удалены:\n"
        "• напоминания\n"
        "• настройки\n\n"
        "Если захотите снова — просто напишите напоминание."
    )


@router.message(Command("privacy"))
async def cmd_privacy(message: Message):
    """Политика конфиденциальности"""
    await message.answer(
        "🔒 <b>Политика конфиденциальности</b>\n\n"
        "<b>Какие данные мы храним:</b>\n"
        "• Ваш Telegram ID — для привязки напоминаний\n"
        "• Тексты напоминаний и время срабатывания\n"
        "• Настройки (часовой пояс, интервал повтора)\n\n"
        "<b>Чего мы НЕ храним:</b>\n"
        "• Имя, фамилия, @username\n"
        "• История сообщений\n\n"
        "<b>Как удалить свои данные:</b>\n"
        "Команда /deleteme — удаляет все ваши напоминания и настройки немедленно.\n\n"
        "<b>Хранение:</b> данные хранятся на частном сервере, "
        "не передаются третьим лицам."
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    await message.answer(
        "📚 <b>Справка</b>\n\n"
        "<b>Формат:</b> <code>текст дата время</code>\n\n"
        "<b>Примеры:</b>\n"
        "• <i>позвонить маме завтра в 10:00</i>\n"
        "• <i>подъем 17.02 в 5 утра</i>\n"
        "• <i>встреча в пятницу в 15:00</i>\n"
        "• <i>написать заявление 20.02 в 13:40</i>\n"
        "• <i>выпить таблетку через 30 минут</i>\n"
        "• <i>позвонить врачу в следующий четверг в 9 утра</i>\n\n"
        "<b>Если не указать время</b> — бот спросит отдельно.\n\n"
        "<b>Периодические напоминания:</b>\n"
        "Добавь ключевое слово в конец фразы:\n"
        "• <i>выпить кофе в 8 утра</i> <b>каждый день</b> / <b>ежедневно</b>\n"
        "• <i>стендап в 10:00</i> <b>по будням</b> / <b>в будние дни</b>\n"
        "• <i>уборка в 11:00</i> <b>по выходным</b> / <b>каждые выходные</b>\n"
        "• <i>архивировать отчёт каждую пятницу в 18:00</i> <b>еженедельно</b>\n"
        "• <i>оплатить счёт 1 числа в 10:00</i> <b>ежемесячно</b>\n"
        "• <i>заплатить налог 20 ноября в 10:00</i> <b>ежегодно</b>\n"
        "• <i>бэкап данных в 3:00</i> <b>каждый час</b> / <b>ежечасно</b>\n\n"
        "После «✅ Выполнено» напоминание автоматически переносится на следующий срок.\n"
        "«✏️ Перенести» сдвигает только текущее срабатывание — базовый день повтора не меняется.\n\n"
        "В списке /list периодические напоминания отмечены флагом:\n"
        "<code>🔁ч</code> — ежечасно  <code>🔁д</code> — ежедневно  "
        "<code>🔁н</code> — еженедельно  <code>🔁м</code> — ежемесячно  <code>🔁г</code> — ежегодно\n"
        "<code>🔁пн-пт</code> — по будням  <code>🔁сб-вс</code> — по выходным\n\n"
        "<b>Команды:</b>\n"
        "/list — список активных напоминаний (изменение и удаление)\n"
        "/delete &lt;ID&gt; — удалить напоминание\n"
        "/settings — настройки (интервал повтора)\n"
        "/cancel — отменить текущее действие\n"
        "/privacy — политика конфиденциальности\n"
        "/deleteme — удалить все мои данные"
    )


# Регистрируем роутер в диспетчере
dp.include_router(router)