import asyncio
import difflib
import logging
import random
import json
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, Dict, List, Tuple
import translate

import contractions
import openai
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import StateFilter, CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, \
    FSInputFile
from aiogram import Router
from aiogram.fsm.context import FSMContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.future import select
from sqlalchemy import Column, String, Integer, Text, ForeignKey, and_
from sqlalchemy.orm import sessionmaker

import config
from buttons import *

# Настройка логирования
logging.basicConfig(
    level=config.LOGGING_LEVEL,
    format=config.LOGGING_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.LOGGING_FILE, mode='w', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

# Настройка базы данных
engine = create_async_engine(config.DATABASE_URL, echo=False)
SessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False
)
Base = declarative_base()

# Асинхронный менеджер контекста для работы с сессией базы данных
@asynccontextmanager
async def session_scope() -> AsyncSession:
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Session rollback due to: {e}")
        raise
    finally:
        await session.close()

# Кэширование озвучки
speech_cache = {}

async def generate_speech(word: str) -> str:
    """Генерация озвучки для слова с использованием OpenAI, с кэшированием."""
    if word in speech_cache:
        return speech_cache[word]

    speech_file_path = Path(f"speech_{word}.mp3")
    try:
        with client.audio.speech.with_streaming_response.create(
                model="tts-1-hd",
                voice="alloy",
                input=word
        ) as response:
            response.stream_to_file(speech_file_path)
        speech_cache[word] = speech_file_path
    finally:
        if not speech_file_path.exists():
            speech_file_path.unlink()
    return speech_cache[word]

# Модели базы данных
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, unique=True, index=True)
    level = Column(String, index=True)
    notification_time = Column(String)
    notification_days = Column(Text)
    language = Column(String, default='en')
    chosen_character = Column(String, default='Lori')

class UserHistory(Base):
    __tablename__ = "user_histories"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    role = Column(String)
    content = Column(Text)

class Dictionary(Base):
    __tablename__ = "dictionaries"
    id = Column(Integer, primary_key=True, index=True)
    level = Column(String, index=True)
    word = Column(String, index=True)
    definition = Column(Text)
    translation = Column(Text)

class GrammarExercise(Base):
    __tablename__ = "grammar_exercises"
    id = Column(Integer, primary_key=True, index=True)
    level = Column(String, index=True)
    rule_name = Column(String, index=True)
    question = Column(Text)
    answer = Column(Text)

async def create_db() -> None:
    """Создание всех таблиц в базе данных."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

client = openai.OpenAI(api_key=config.PROXY_API_KEY, base_url="https://api.proxyapi.ru/openai/v1")

# Настройка бота, диспетчера и планировщика
bot = Bot(token=config.TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
scheduler = AsyncIOScheduler()

# Загрузка конфигураций из JSON
def load_configurations():
    with open('configurations.json', 'r', encoding='utf-8') as f:
        return json.load(f)

configurations = load_configurations()

LEVEL_MAPPING = configurations['LEVEL_MAPPING']
GREETINGS = configurations['GREETINGS']
REMINDER_MESSAGES = configurations['REMINDER_MESSAGES']

async def get_user(session: AsyncSession, chat_id: int) -> Optional[User]:
    """Получение пользователя по chat_id из базы данных."""
    try:
        result = await session.execute(select(User).filter(User.chat_id == chat_id))
        return result.scalars().first()
    except Exception as e:
        logger.error(f"Error fetching user: {e}")
        return None

async def get_user_history(session: AsyncSession, user_id: int) -> List[UserHistory]:
    """Получение истории пользователя по user_id."""
    try:
        result = await session.execute(select(UserHistory).filter(UserHistory.user_id == user_id).order_by(UserHistory.id))
        return result.scalars().all()
    except Exception as e:
        logger.error(f"Error fetching user history: {e}")
        return []

async def save_user_history(session: AsyncSession, user_id: int, history: List[UserHistory]) -> None:
    """Сохранение истории пользователя."""
    try:
        await session.execute(UserHistory.__table__.delete().where(UserHistory.user_id == user_id))
        for entry in history:
            new_entry = UserHistory(user_id=user_id, role=entry.role, content=entry.content)
            session.add(new_entry)
        await session.commit()
    except Exception as e:
        logger.error(f"Error saving user history: {e}")
        await session.rollback()

async def add_to_history(session: AsyncSession, user_id: int, role: str, message: str) -> None:
    """Добавление записи в историю пользователя."""
    try:
        history = await get_user_history(session, user_id)

        if len(history) >= config.MAX_HISTORY_LENGTH * 2:
            history = history[2:]

        new_entry = UserHistory(user_id=user_id, role=role, content=message)
        session.add(new_entry)
        await session.commit()
    except Exception as e:
        logger.error(f"Error adding to history: {e}")
        await session.rollback()

async def load_dictionary_into_db(dictionary_data: Dict[str, Dict[str, Dict[str, str]]], session: AsyncSession) -> None:
    """Загрузка словаря в базу данных."""
    try:
        for level, words in dictionary_data.items():
            for word, info in words.items():
                existing_word = await session.execute(
                    select(Dictionary).filter_by(level=level, word=word.capitalize())
                )
                if not existing_word.scalars().first():
                    new_word = Dictionary(
                        level=level,
                        word=word.capitalize(),
                        definition=info['definition'],
                        translation=info['translation']
                    )
                    session.add(new_word)
        await session.commit()
    except Exception as e:
        logger.error(f"Error loading dictionary into DB: {e}")
        await session.rollback()

async def remove_duplicates_from_db(session: AsyncSession) -> None:
    """Удаление дубликатов из базы данных."""
    try:
        words_seen = set()
        duplicates = await session.execute(select(Dictionary))
        for entry in duplicates.scalars().all():
            word_key = (entry.level, entry.word)
            if word_key in words_seen:
                await session.delete(entry)
            else:
                words_seen.add(word_key)
        await session.commit()
    except Exception as e:
        logger.error(f"Error removing duplicates from DB: {e}")
        await session.rollback()

""" Функции для работы с уведомлениями """

async def schedule_notifications(chat_id: int, days: List[str], time: str, language: str = 'en') -> None:
    """Планирование уведомлений для пользователя."""
    hours, minutes = map(int, time.split(":"))
    job_id = f"notification_{chat_id}"

    existing_jobs = scheduler.get_jobs()
    for job in existing_jobs:
        if job.id.startswith(job_id):
            scheduler.remove_job(job.id)

    for day in days:
        try:
            scheduler.add_job(send_reminder, 'cron', day_of_week=day, hour=hours, minute=minutes, id=f"{job_id}_{day}",
                              args=[chat_id, language])
        except Exception as e:
            logger.error(f"Error scheduling notification for {day}: {e}")
            await bot.send_message(chat_id, f"Failed to schedule notification for {day.capitalize()}.")

    if not scheduler.running:
        scheduler.start()

async def send_reminder(chat_id: int, language: str) -> None:
    """Отправка уведомления пользователю."""
    reminder_messages_local = REMINDER_MESSAGES.get(language, REMINDER_MESSAGES['en'])
    await bot.send_message(chat_id, random.choice(reminder_messages_local))

""" Обработка команды /start """

class LanguageStates(StatesGroup):
    choosing_language = State()

@router.message(CommandStart())
async def send_welcome(message: Message, state: FSMContext) -> None:
    """Обработка команды /start и выбор языка."""
    chat_id = message.chat.id
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="English", callback_data="set_lang_en")],
        [InlineKeyboardButton(text="Русский", callback_data="set_lang_ru")]
    ])
    await state.set_state(LanguageStates.choosing_language)
    await bot.send_message(chat_id, "Please select your language / Пожалуйста, выберите язык", reply_markup=markup)

@router.callback_query(F.data.startswith("set_lang_"))
async def set_language(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    """Обработка выбора языка пользователем."""
    language = callback_query.data.split("_")[-1]
    chat_id = callback_query.message.chat.id

    async with session_scope() as session:
        user = await get_user(session, chat_id)
        if user:
            user.language = language
        else:
            user = User(chat_id=chat_id, language=language)
            session.add(user)

    # Добавляем кнопку "Support project" в разметку
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Support project", callback_data="support_project")]
    ])

    if language == 'ru':
        await bot.send_message(chat_id, "Добро пожаловать в бот для изучения английского!", reply_markup=markup)
    else:
        await bot.send_message(chat_id, "Welcome to the English Learning Bot!", reply_markup=markup)

    await state.clear()

""" Обработка выбора уровня """

@router.message(F.text.in_({"Level", "Уровень"}))
async def handle_level_button(message: Message) -> None:
    """Обработка выбора уровня языка пользователем."""
    async with session_scope() as session:
        user = await get_user(session, message.chat.id)
        language = user.language if user else 'en'
    markup = create_level_buttons(language)
    await bot.send_message(message.chat.id, "Choose your level:" if language == 'en' else "Выберите свой уровень:",
                           reply_markup=markup)

@router.callback_query(F.data.startswith("set_level_"))
async def set_user_level(callback_query: types.CallbackQuery) -> None:
    """Сохранение выбранного уровня пользователя."""
    level = callback_query.data[len('set_level_'):]
    chat_id = callback_query.message.chat.id

    async with session_scope() as session:
        user = await get_user(session, chat_id)
        if user:
            user.level = level
    logger.info(f"User {chat_id} set their level to {level}")

    async with session_scope() as session:
        user = await get_user(session, callback_query.message.chat.id)
        language = user.language if user else 'en'

    message = f"Your level has been set to {level}." if language == 'en' else f"Ваш уровень установлен на {level}."
    await bot.send_message(callback_query.message.chat.id, message)

""" Обработка информации """

@router.message(F.text.in_({"Info", "Информация"}))
async def handle_info_button(message: Message) -> None:
    """Отправка информации о боте и поддержке проекта."""
    async with session_scope() as session:
        user = await get_user(session, message.chat.id)
        language = user.language if user else 'en'

    info_text = {
        'en': (
            "<b>/start</b>: Begin interaction with the bot and see the main menu.\n\n"
            "<b>Level</b>: Set your English level to ensure the content matches your skill level.\n\n"
            "<b>Notification</b>: Enable or disable daily practice notifications and set the time to receive them.\n\n"
            "<b>Grammar</b>: Learn grammar rules and practice exercises based on your level.\n\n"
            "<b>Practice</b>: Test your knowledge with grammar exercises.\n\n"
            "<b>Dictionary</b>: Add, learn, and see the meaning of words based on your level.\n\n"
            "<b>Talk</b>: Engage in a conversation with the bot, tailored to your English level.\n\n"
            "<b>Info</b>: See all available commands and how to use them.\n\n"
            "<b>Support project</b>: Help us by joining our recommended projects!"
        ),
        'ru': (
            "<b>/start</b>: Начните взаимодействие с ботом и откройте главное меню.\n\n"
            "<b>Уровень</b>: Установите свой уровень английского, чтобы контент соответствовал вашим навыкам.\n\n"
            "<b>Уведомление</b>: Включите или отключите ежедневные уведомления о практике и установите время их получения.\n\n"
            "<b>Грамматика</b>: Учите правила грамматики и выполняйте упражнения в зависимости от вашего уровня.\n\n"
            "<b>Практика</b>: Проверьте свои знания с помощью упражнений по грамматике.\n\n"
            "<b>Словарь</b>: Добавляйте слова, учите их и смотрите их значение в зависимости от вашего уровня.\n\n"
            "<b>Разговор</b>: Поговорите с ботом на английском, адаптированном под ваш уровень.\n\n"
            "<b>Информация</b>: Посмотрите все доступные команды и узнайте, как ими пользоваться.\n\n"
            "<b>Поддержать проект</b>: Помогите нам, присоединившись к нашим рекомендуемым проектам!"
        )
    }

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Support project" if language == 'en' else "Поддержать проект", callback_data="support_project")],
        [InlineKeyboardButton(text="Go back" if language == 'en' else "Вернуться назад", callback_data="go_back")]
    ])

    await bot.send_message(message.chat.id, info_text[language], parse_mode="html", reply_markup=markup)

@router.callback_query(F.data == "support_project")
async def handle_support_project(callback_query: types.CallbackQuery) -> None:
    """Отправка меню с реферальными ссылками."""
    async with session_scope() as session:
        user = await get_user(session, callback_query.message.chat.id)
        language = user.language if user else 'en'

    markup = create_support_buttons(language)
    await bot.send_message(callback_query.message.chat.id,
                           "Support our project by joining the following platforms:" if language == 'en' else "Поддержите наш проект, присоединившись к следующим платформам:",
                           reply_markup=markup)

""" Обработка уведомлений """

class NotificationStates(StatesGroup):
    days = State()
    time = State()

@router.message(F.text.in_({"Notification", "Уведомление"}))
async def handle_notification(message: Message) -> None:
    """Обработка настроек уведомлений пользователя."""
    async with session_scope() as session:
        user = await get_user(session, message.chat.id)
        language = user.language if user else 'en'

    markup = create_notification_buttons(language)
    await bot.send_message(message.chat.id,
                           "Do you want to enable or disable notifications?" if language == 'en' else "Вы хотите включить или отключить уведомления?",
                           reply_markup=markup)

@router.message(F.text.in_({"Enable Notifications", "Включить уведомления"}))
async def enable_notifications(message: Message, state: FSMContext) -> None:
    """Включение уведомлений и выбор дней недели."""
    await state.set_state(NotificationStates.days)
    async with session_scope() as session:
        user = await get_user(session, message.chat.id)
        selected_days = user.notification_days.split(',') if user and user.notification_days else []
        language = user.language if user else 'en'
    markup = create_days_buttons(selected_days, language)
    await bot.send_message(message.chat.id,
                           "Select days for notifications and click Save." if language == 'en' else "Выберите дни для уведомлений и нажмите Сохранить.",
                           reply_markup=markup)

@router.callback_query(F.data.startswith("toggle_"))
async def toggle_day(callback_query: types.CallbackQuery) -> None:
    """Переключение выбора дней для уведомлений."""
    day = callback_query.data[len('toggle_'):]
    chat_id = callback_query.message.chat.id

    async with session_scope() as session:
        user = await get_user(session, chat_id)
        selected_days = user.notification_days.split(',') if user and user.notification_days else []
        if day in selected_days:
            selected_days.remove(day)
        else:
            selected_days.append(day)
        user.notification_days = ','.join(selected_days)
        language = user.language if user else 'en'

    markup = create_days_buttons(selected_days, language)
    await callback_query.message.edit_reply_markup(reply_markup=markup)

@router.callback_query(F.data == "save_days")
async def save_days(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    """Сохранение выбранных дней для уведомлений."""
    async with session_scope() as session:
        user = await get_user(session, callback_query.message.chat.id)
        selected_days = user.notification_days.split(',') if user and user.notification_days else []
        language = user.language if user else 'en'

    valid_days = {
        "monday": "mon",
        "tuesday": "tue",
        "wednesday": "wed",
        "thursday": "thu",
        "friday": "fri",
        "saturday": "sat",
        "sunday": "sun"
    }
    selected_days_lower = [valid_days[day.lower()] for day in selected_days if day.lower() in valid_days]

    if not selected_days_lower:
        await bot.send_message(callback_query.message.chat.id,
                               "No valid days selected." if language == 'en' else "Не выбраны допустимые дни.")
        return

    await state.update_data(selected_days_lower=selected_days_lower)

    await bot.send_message(callback_query.message.chat.id,
                           f"Notifications will be sent on: {', '.join(selected_days)}." if language == 'en' else f"Уведомления будут отправляться в: {', '.join(selected_days)}.")
    await state.set_state(NotificationStates.time)
    await bot.send_message(callback_query.message.chat.id,
                           "Please specify the time for notifications in HH:MM format (Moscow time)." if language == 'en' else "Пожалуйста, укажите время для уведомлений в формате ЧЧ:ММ (Московское время).")

@router.message(StateFilter(NotificationStates.time))
async def set_notification_time(message: Message, state: FSMContext) -> None:
    """Установка времени уведомлений."""
    chat_id = message.chat.id
    user_input = message.text.strip()

    try:
        valid_time = datetime.strptime(user_input, "%H:%M")
        valid_time_utc = valid_time - timedelta(hours=3)

        data = await state.get_data()
        selected_days_lower = data.get("selected_days_lower", [])

        async with session_scope() as session:
            user = await get_user(session, chat_id)
            if user:
                user.notification_time = valid_time_utc.strftime("%H:%M")
                session.add(user)

        async with session_scope() as session:
            user = await get_user(session, chat_id)
            language = user.language if user else 'en'

        await bot.send_message(
            chat_id,
            f"Notifications will be sent on {', '.join([day.capitalize() for day in selected_days_lower])} at {valid_time.strftime('%H:%M')} (Moscow time)." if language == 'en' else f"Уведомления будут отправляться в {', '.join([day.capitalize() for day in selected_days_lower])} в {valid_time.strftime('%H:%M')} (Московское время).",
            reply_markup=create_navigation_buttons(language)
        )

        await schedule_notifications(chat_id, selected_days_lower, valid_time_utc.strftime("%H:%M"), language)
        await state.clear()

    except ValueError:
        async with session_scope() as session:
            user = await get_user(session, chat_id)
            language = user.language if user else 'en'
        await bot.send_message(chat_id,
                               "Please enter a valid time in HH:MM format." if language == 'en' else "Пожалуйста, введите допустимое время в формате ЧЧ:ММ.")

@router.message(F.text.in_({"Disable Notifications", "Отключить уведомления"}))
async def disable_notifications(message: Message, state: FSMContext) -> None:
    """Отключение уведомлений."""
    chat_id = message.chat.id
    job_id = f"notification_{chat_id}"

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    async with session_scope() as session:
        user = await get_user(session, chat_id)
        if user:
            user.notification_time = None
            user.notification_days = None
            language = user.language if user else 'en'

    await bot.send_message(chat_id, "Notifications disabled." if language == 'en' else "Уведомления отключены.",
                           reply_markup=create_navigation_buttons(language))
    await state.clear()

""" Обработка грамматических правил """

@router.message(F.text.in_({"Grammar", "Грамматика"}))
async def handle_grammar_button(message: Message) -> None:
    """Обработка запроса на изучение грамматики."""
    async with session_scope() as session:
        user = await get_user(session, message.chat.id)
        language = user.language if user else 'en'
    await send_grammar_options(message, language)

def read_grammar_rules(file_path: str) -> Dict[str, str]:
    """Чтение правил грамматики из файла."""
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
    rules = {}
    current_title = None
    current_text = []
    section_titles = [
        "Form", "Spelling", "Use", "Notes", "Form - regular verbs",
        "We do not normally use in the continuous the following groups of verbs (so called state verbs):",
        "If some of these verbs are used in the present continuous, they have a different meaning. In such a case they become action verbs.",
        "Form - irregular verbs", "Time expressions:", "Examples:"
    ]
    for line in lines:
        stripped_line = line.strip()
        if stripped_line and stripped_line != '-----------------------------------------':
            if stripped_line.isupper() and not stripped_line.isdigit():
                if current_title:
                    rules[current_title] = '\n'.join(current_text)
                current_title = stripped_line
                current_text = []
            else:
                if any(stripped_line.startswith(title) for title in section_titles):
                    if current_text:
                        current_text.append("")
                    current_text.append(f"<b>{stripped_line}</b>")
                    current_text.append("")
                else:
                    current_text.append(stripped_line)
        elif stripped_line == '-----------------------------------------':
            continue
    if current_title:
        rules[current_title] = '\n'.join(current_text)
    return rules

grammar_rules = read_grammar_rules(config.GRAMMAR_RULES_FILE)

def create_grammar_buttons(language: str = 'en') -> InlineKeyboardMarkup:
    """Создание кнопок для выбора правил грамматики."""
    buttons = [[InlineKeyboardButton(text=title, callback_data=title)] for title in grammar_rules.keys()]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    return markup

async def send_grammar_options(message: Message, language: str) -> None:
    """Отправка вариантов правил грамматики для выбора."""
    markup = create_grammar_buttons(language)
    await bot.send_message(message.chat.id,
                           "Choose grammar rule:" if language == 'en' else "Выберите правило грамматики:",
                           reply_markup=markup)

@router.callback_query(F.data.in_(grammar_rules.keys()))
async def handle_grammar_selection(callback_query: types.CallbackQuery) -> None:
    """Обработка выбора правила грамматики."""
    rule_text = grammar_rules[callback_query.data]
    await bot.send_message(callback_query.message.chat.id, rule_text, parse_mode="html")

""" Обработка грамматических упражнений """

def load_grammar_exercises(filepath: str) -> Dict[str, Dict[str, List[Tuple[str, str]]]]:
    """Загрузка упражнений по грамматике из файла."""
    grammar_exercises = {}
    current_level = None
    current_rule = None
    with open(filepath, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if line.startswith('# Уровень'):
                current_level = line.split()[-1]
                if current_level not in grammar_exercises:
                    grammar_exercises[current_level] = {}
            elif line.startswith('##'):
                current_rule = line.split(' ', 1)[1]
                if current_level and current_rule:
                    grammar_exercises[current_level][current_rule] = []
            elif line:
                if current_level and current_rule:
                    question, answer = line.split(' - ')
                    grammar_exercises[current_level][current_rule].append((question, answer))
    return grammar_exercises

grammar_exercises = load_grammar_exercises(config.GRAMMAR_EXERCISES_FILE)

@router.message(F.text.in_({"Practice", "Практика"}))
async def handle_practice_button(message: Message, state: FSMContext) -> None:
    """Обработка запроса на практику грамматики."""
    async with session_scope() as session:
        user = await get_user(session, message.chat.id)
        language = user.language if user else 'en'
    await send_practice_info(message.chat.id, state, language)

async def send_practice_info(chat_id: int, state: FSMContext, language: str) -> None:
    """Отправка информации о разделе практики."""
    await bot.send_message(chat_id,
                           "Welcome to the Practice section. Here you can practice various grammar rules depending on your level. Please select a grammar rule to start practicing." if language == 'en' else "Добро пожаловать в раздел практики. Здесь вы можете практиковать различные правила грамматики в зависимости от вашего уровня. Пожалуйста, выберите правило грамматики для начала практики.")
    async with session_scope() as session:
        user = await get_user(session, chat_id)
        level = user.level if user else 'A1'
    mapped_level = LEVEL_MAPPING.get(level, 'A1-A2')
    await send_practice_options(chat_id, mapped_level, state, language)

async def send_practice_exercise(chat_id: int, level: str, rule: str, state: FSMContext, language: str) -> None:
    """Отправка упражнения по грамматике пользователю."""
    if level in grammar_exercises and rule in grammar_exercises[level]:
        exercises = grammar_exercises[level][rule]
        if exercises:
            data = await state.get_data()
            exercise_index = data.get("exercise_index", 0)
            if exercise_index >= len(exercises):
                await bot.send_message(chat_id,
                                       "You have completed all exercises for this grammar rule." if language == 'en' else "Вы выполнили все упражнения по этому правилу грамматики.",
                                       reply_markup=create_navigation_buttons(language))
                await state.clear()
                return

            question, answer = exercises[exercise_index]
            await state.update_data(current_exercise=(question, answer, rule), exercise_index=exercise_index + 1)
            await bot.send_message(chat_id, question)
        else:
            await bot.send_message(chat_id,
                                   "No exercises available for this grammar rule." if language == 'en' else "Нет упражнений для этого правила грамматики.",
                                   reply_markup=create_navigation_buttons(language))
    else:
        await bot.send_message(chat_id,
                               "Invalid grammar rule or level." if language == 'en' else "Недопустимое правило грамматики или уровень.",
                               reply_markup=create_navigation_buttons(language))

async def send_practice_options(chat_id: int, level: str, state: FSMContext, language: str) -> None:
    """Отправка пользователю вариантов упражнений для практики."""
    buttons = []
    if level in grammar_exercises:
        for rule in grammar_exercises[level]:
            buttons.append([InlineKeyboardButton(text=rule, callback_data=f"practice_{rule}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await bot.send_message(chat_id,
                               "Choose a grammar rule to practice:" if language == 'en' else "Выберите правило грамматики для практики:",
                               reply_markup=markup)
    else:
        await bot.send_message(chat_id,
                               "No grammar rules found for this level." if language == 'en' else "Правила грамматики для этого уровня не найдены.",
                               reply_markup=create_navigation_buttons(language))

@router.callback_query(F.data.startswith("practice_"))
async def handle_practice_selection(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    """Обработка выбора правила грамматики для практики."""
    rule = callback_query.data[len("practice_"):]
    chat_id = callback_query.message.chat.id

    async with session_scope() as session:
        user = await get_user(session, chat_id)
        language = user.language if user else 'en'
        level = user.level if user else 'A1'

    mapped_level = LEVEL_MAPPING.get(level, 'A1-A2')

    logger.info(f"User {chat_id} selected rule {rule} for practice.")

    await state.update_data(current_rule=rule, level=mapped_level, training_type="grammar")

    await send_practice_exercise(chat_id, mapped_level, rule, state, language)
    await state.set_state("practice")

@router.message(StateFilter("practice"))
async def handle_practice_message(message: Message, state: FSMContext) -> None:
    """Обработка ответа пользователя на упражнение по грамматике."""
    chat_id = message.chat.id
    data = await state.get_data()

    if "current_exercise" in data:
        question, correct_answer, rule = data["current_exercise"]
        correct_answer_normalized = contractions.fix(correct_answer.strip().lower())
        text_normalized = contractions.fix(message.text.strip().lower())

        # Удаляем местоимения из начала правильного ответа и ответа пользователя
        correct_answer_words = correct_answer_normalized.split()
        user_answer_words = text_normalized.split()

        # Игнорируем первое слово, если оно местоимение
        if user_answer_words and user_answer_words[0] in ["i", "you", "he", "she", "it", "we", "they"]:
            user_answer_words = user_answer_words[1:]

        if correct_answer_words and correct_answer_words[0] in ["i", "you", "he", "she", "it", "we", "they"]:
            correct_answer_words = correct_answer_words[1:]

        correct_answer_normalized = " ".join(correct_answer_words)
        text_normalized = " ".join(user_answer_words)

        # Сравнение ответа с допустимой погрешностью
        if text_normalized == correct_answer_normalized or difflib.SequenceMatcher(None, text_normalized, correct_answer_normalized).ratio() > 0.9:
            await bot.send_message(chat_id, "Correct!" if data.get('language', 'en') == 'en' else "Правильно!",
                                   reply_markup=create_continue_back_buttons(data.get('language', 'en')))
        else:
            await bot.send_message(chat_id, f"Incorrect. The correct answer is: {correct_answer}" if data.get('language', 'en') == 'en' else f"Неправильно. Правильный ответ: {correct_answer}",
                                   reply_markup=create_continue_back_buttons(data.get('language', 'en')))

        await state.update_data(current_exercise=None)
    else:
        await bot.send_message(chat_id, "Please select a grammar rule to start practicing." if data.get('language', 'en') == 'en' else "Пожалуйста, выберите правило грамматики для начала практики.")

@router.callback_query(F.data == "continue")
async def handle_continue(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    """Обработка запроса на продолжение упражнения по грамматике."""
    data = await state.get_data()
    training_type = data.get('training_type')
    chat_id = callback_query.message.chat.id

    async with session_scope() as session:
        user = await get_user(session, chat_id)
        language = user.language if user else 'en'

    if training_type == "grammar":
        rule = data.get("current_rule")
        level = data.get("level")

        if not rule or not level:
            await bot.send_message(chat_id,
                                   "Grammar rule or level information is missing. Returning to the main menu." if language == 'en' else "Информация о правиле грамматики или уровне отсутствует. Возвращение в главное меню.",
                                   reply_markup=create_navigation_buttons(language))
            await state.clear()
            return

        await send_practice_exercise(chat_id, level, rule, state, language)

    elif training_type == "words":
        level = data.get('level')
        if not level:
            await bot.send_message(chat_id,
                                   "Level information is missing. Returning to the main menu." if language == 'en' else "Информация об уровне отсутствует. Возвращение в главное меню.",
                                   reply_markup=create_navigation_buttons(language))
            await state.clear()
            return

        await study_words(callback_query.message, level, state, practice=True)

    else:
        await bot.send_message(chat_id,
                               "Invalid training type. Returning to the main menu." if language == 'en' else "Недопустимый тип тренировки. Возвращение в главное меню.",
                               reply_markup=create_navigation_buttons(language))
        await state.clear()

@router.callback_query(F.data == "go_back")
async def handle_go_back(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    """Обработка запроса на возврат в главное меню."""
    async with session_scope() as session:
        user = await get_user(session, callback_query.message.chat.id)
        language = user.language if user else 'en'

    await bot.send_message(callback_query.message.chat.id,
                           "Returning to the main menu." if language == 'en' else "Возвращение в главное меню.",
                           reply_markup=create_navigation_buttons(language))
    await state.clear()

""" Работа со словарём """

def read_dictionary_file(file_path: str) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Чтение данных из файла словаря."""
    dictionaries = {
        'A1-A2': {},
        'B1-B2': {},
        'C1-C2': {}
    }
    current_level = None

    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                if line.startswith("Level:"):
                    current_level = line.split(": ")[1]
                else:
                    parts = line.split(' - ')
                    if len(parts) == 3:
                        word, definition, translation = parts
                        word = word.lower()
                        if current_level in dictionaries:
                            dictionaries[current_level][word] = {
                                'definition': definition,
                                'translation': translation
                            }
    except FileNotFoundError:
        logger.error(f"Dictionary file not found at {file_path}")
        return {}
    except Exception as e:
        logger.error(f"Error reading dictionary file: {e}")
        return {}

    return dictionaries

dictionaries = read_dictionary_file(config.DICTIONARY_FILE)

async def setup() -> None:
    """Настройка базы данных."""
    async with session_scope() as session:
        await load_dictionary_into_db(dictionaries, session)
        await remove_duplicates_from_db(session)

@router.message(F.text.in_({"Dictionary", "Словарь"}))
async def handle_dict_button(message: Message, state: FSMContext) -> None:
    """Обработка нажатия на кнопку "Словарь"."""
    async with session_scope() as session:
        user = await get_user(session, message.chat.id)
        language = user.language if user else 'en'
    await show_dict_menu(message, language)

async def show_dict_menu(message: Message, language: str) -> None:
    """Отправка меню словаря пользователю."""
    markup = create_dict_menu_buttons(language)
    await bot.send_message(message.chat.id, 'Select an action:' if language == 'en' else 'Выберите действие:',
                           reply_markup=markup)

@router.message(StateFilter("add_word_state"))
async def add_word(message: Message, state: FSMContext) -> None:
    """Добавление нового слова в словарь."""
    try:
        word, definition, translation = map(str.strip, message.text.split(' - '))
        word = word.lower()
        async with session_scope() as session:
            user = await get_user(session, message.chat.id)
            level = LEVEL_MAPPING.get(user.level, 'A1-A2')
            existing_word = await session.execute(
                select(Dictionary).filter_by(level=level, word=word.capitalize())
            )
            if not existing_word.scalars().first():
                new_word = Dictionary(level=level, word=word.capitalize(), definition=definition,
                                      translation=translation)
                session.add(new_word)
                await bot.send_message(message.chat.id,
                                       f'The word "{word.capitalize()}" has been added to the dictionary.')
            else:
                await bot.send_message(message.chat.id,
                                       f'The word "{word.capitalize()}" already exists in the dictionary.')
    except ValueError:
        await bot.send_message(message.chat.id, 'Invalid format. Try again.')
    await state.clear()
    async with session_scope() as session:
        user = await get_user(session, message.chat.id)
        language = user.language if user else 'en'
    await show_dict_menu(message, language)

@router.message(StateFilter("see_meaning_state"))
async def handle_see_meaning(message: Message, state: FSMContext) -> None:
    """Просмотр значения слова из словаря."""
    await show_word_definition(message)
    await state.clear()

@router.message(F.text.in_(
    ['Add words', 'Practice words', 'Learn words', 'See the meaning of a word', 'Go back', 'Добавить слова',
     'Практиковать слова', 'Учить слова', 'Посмотреть значение слова', 'Вернуться назад']))
async def process_dict_action(message: Message, state: FSMContext) -> None:
    """Обработка действий, связанных со словарем."""
    action = message.text.strip()
    chat_id = message.chat.id
    async with session_scope() as session:
        user = await get_user(session, chat_id)
        level = configurations['LEVEL_MAPPING'].get(user.level, 'A1-A2')
        language = user.language if user else 'en'

    if action in ['Add words', 'Добавить слова']:
        await state.set_state("add_word_state")
        await bot.send_message(message.chat.id,
                               'Enter a word, definition, and translation (for example, "word - definition - translation"):' if language == 'en' else 'Введите слово, определение и перевод (например, "слово - определение - перевод"):')
    elif action in ['Practice words', 'Практиковать слова']:
        await study_words(message, level, state, practice=True)
    elif action in ['Learn words', 'Учить слова']:
        await study_words(message, level, state, practice=False)
    elif action in ['See the meaning of a word', 'Посмотреть значение слова']:
        await state.set_state("see_meaning_state")
        await bot.send_message(message.chat.id,
                               'Enter the search word:' if language == 'en' else 'Введите искомое слово:')
    elif action in ['Go back', 'Вернуться назад']:
        await bot.send_message(message.chat.id,
                               'Returning to the main menu.' if language == 'en' else 'Возвращение в главное меню.',
                               reply_markup=create_navigation_buttons(language))
        await state.clear()

async def study_words(message: Message, level: str, state: FSMContext, practice: bool) -> None:
    """Практика слов из словаря."""
    async with session_scope() as session:
        result = await session.execute(select(Dictionary).filter(Dictionary.level == level))
        words = result.scalars().all()
        words_data = [(word.word, word.translation) for word in words]

    if not words_data:
        async with session_scope() as session:
            user = await get_user(session, message.chat.id)
            language = user.language if user else 'en'
        await bot.send_message(message.chat.id,
                               'The dictionary is empty or does not exist.' if language == 'en' else 'Словарь пуст или не существует.')
        await show_dict_menu(message, language)
        return

    if practice:
        random_word = random.choice(words_data)
        word, correct_translation = random_word
        listen_button = InlineKeyboardButton(text="🔊 Listen", callback_data=f"listen_{word}")
        listen_markup = InlineKeyboardMarkup(inline_keyboard=[[listen_button]])

        await bot.send_message(message.chat.id, f'Translate the word: {word}', reply_markup=listen_markup)
        await state.set_state("check_translation_state")
        await state.update_data(word=word, correct_translation=correct_translation)
    else:
        selected_words = random.sample(words_data, min(5, len(words_data)))
        buttons = [[InlineKeyboardButton(text=word, callback_data=f"learn_{word}")] for word, _ in selected_words]
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        async with session_scope() as session:
            user = await get_user(session, message.chat.id)
            language = user.language if user else 'en'
        await bot.send_message(message.chat.id,
                               "Select a word to learn:" if language == 'en' else "Выберите слово для изучения:",
                               reply_markup=markup)

@router.callback_query(F.data.startswith("learn_"))
async def handle_learn_word(callback_query: types.CallbackQuery) -> None:
    """Обработка выбора слова для изучения."""
    word = callback_query.data[len("learn_"):]

    async with session_scope() as session:
        word_entry = await session.execute(select(Dictionary).filter(Dictionary.word == word))
        word_entry = word_entry.scalars().one_or_none()

        if word_entry:
            listen_button = InlineKeyboardButton(text="🔊 Listen", callback_data=f"listen_{word_entry.word}")
            listen_markup = InlineKeyboardMarkup(inline_keyboard=[[listen_button]])
            await bot.send_message(
                callback_query.message.chat.id,
                f"<b>{word_entry.word}</b>\n<b>Definition:</b> {word_entry.definition}\n<b>Translation:</b> {word_entry.translation}",
                parse_mode="html",
                reply_markup=listen_markup
            )

@router.callback_query(F.data.startswith("listen_"))
async def handle_listen(callback_query: types.CallbackQuery) -> None:
    """Обработка запроса на озвучивание слова."""
    word = callback_query.data[len("listen_"):]

    speech_file_path = None
    try:
        speech_file_path = Path("word.mp3")
        with client.audio.speech.with_streaming_response.create(
                model="tts-1-hd",
                voice="alloy",
                input=word
        ) as response:
            response.stream_to_file(speech_file_path)

        voice_message = FSInputFile(speech_file_path)
        await bot.send_voice(callback_query.message.chat.id, voice_message)
    finally:
        if speech_file_path and speech_file_path.exists():
            speech_file_path.unlink() 

@router.message(StateFilter("check_translation_state"))
async def check_translation(message: Message, state: FSMContext) -> None:
    """Проверка перевода слова, предложенного пользователем."""
    data = await state.get_data()
    word = data['word']
    correct_translation = data['correct_translation']

    chat_id = message.chat.id
    async with session_scope() as session:
        user = await get_user(session, chat_id)
        language = user.language if user else 'en'

    if message.text.lower() in ["go back", "вернуться назад"]:
        await bot.send_message(message.chat.id,
                               'Returning to the main menu.' if language == 'en' else 'Возвращение в главное меню.',
                               reply_markup=create_navigation_buttons(language))
        await state.clear()
        return

    user_translation = message.text.strip().lower()
    if user_translation == correct_translation.lower():
        await bot.send_message(message.chat.id, 'Right!' if language == 'en' else 'Правильно!',
                               reply_markup=create_continue_back_buttons(language))
    else:
        await bot.send_message(message.chat.id,
                               f'Wrong. Correct translation: {correct_translation}' if language == 'en' else f'Неправильно. Правильный перевод: {correct_translation}',
                               reply_markup=create_continue_back_buttons(language))

    async with session_scope() as session:
        user = await get_user(session, message.chat.id)
        level = LEVEL_MAPPING.get(user.level, 'A1-A2')
        await state.update_data(training_type="words", level=level)

async def show_word_definition(message: Message) -> None:
    """Отправка определения слова из словаря."""
    word = message.text.strip().lower()
    chat_id = message.chat.id

    async with session_scope() as session:
        user = await get_user(session, chat_id)
        level = LEVEL_MAPPING.get(user.level, 'A1-A2')
        language = user.language if user else 'en'

        word_entry = await session.execute(
            select(Dictionary).filter(
                and_(Dictionary.level == level, Dictionary.word == word)
            )
        )
        word_entry = word_entry.scalars().first()

    if word_entry:
        await bot.send_message(
            message.chat.id,
            f'<b>Definition:</b> {word_entry.definition}\n<b>Translation:</b> {word_entry.translation}'
        )
    else:
        await bot.send_message(message.chat.id,
                               'The word was not found in the dictionary.' if language == 'en' else 'Слово не найдено в словаре.')

""" Функции для общения и озвучки """

@router.message(F.text.in_({"Talk", "Разговор"}))
async def start_talk(message: Message, state: FSMContext) -> None:
    """Начало диалога с ботом."""
    chat_id = message.chat.id

    buttons = [
        [InlineKeyboardButton(text="Lori 🐱", callback_data="choose_Lori")],
        [InlineKeyboardButton(text="Kiko 🐥", callback_data="choose_Kiko")],
        [InlineKeyboardButton(text="Nancy 🦦", callback_data="choose_Nancy")],
        [InlineKeyboardButton(text="Broot 🐶", callback_data="choose_Broot")]
    ]

    markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    for character in config.CHARACTER_IMAGES:
        photo = FSInputFile(config.CHARACTER_IMAGES[character])
        await bot.send_photo(chat_id, photo, caption=f"{character} is ready to chat with you!")

    await bot.send_message(chat_id, "Choose your character:", reply_markup=markup)
    await state.set_state("choose_character")

@router.callback_query(F.data.startswith("choose_"))
async def handle_character_choice(callback_query: types.CallbackQuery, state: FSMContext) -> None:
    """Обработка выбора персонажа для диалога."""
    chosen_character = callback_query.data.split("_")[-1]
    chat_id = callback_query.message.chat.id

    async with session_scope() as session:
        user = await get_user(session, chat_id)
        if user:
            user.chosen_character = chosen_character
            user_level = user.level
            language = user.language
        else:
            user = User(chat_id=chat_id, chosen_character=chosen_character)
            session.add(user)
            user_level = "A1"
            language = 'en'
        await session.commit()

    greeting = random.choice(GREETINGS[user_level]).format(name=chosen_character)

    if config.CHARACTER_IMAGES.get(chosen_character):
        photo = FSInputFile(config.CHARACTER_IMAGES[chosen_character])
        await bot.send_photo(chat_id, photo, caption=f"{chosen_character} is ready to chat with you!")

    await send_tts_message(chat_id, greeting, config.CHARACTER_VOICES[chosen_character])
    await bot.send_message(chat_id, greeting, reply_markup=create_back_button(language))

    await state.clear()


async def send_tts_message(chat_id: int, text: str, voice: str = "echo") -> None:
    """Отправка голосового сообщения пользователю."""
    speech_file_path = None
    try:
        text_with_pause = f"... {text}"

        speech_file_path = Path("speech.mp3")

        with client.audio.speech.with_streaming_response.create(
                model="tts-1-hd",
                voice=voice,
                input=text_with_pause
        ) as response:
            response.stream_to_file(speech_file_path)

        if speech_file_path.stat().st_size == 0:
            raise Exception("TTS generated an empty file.")

        voice_message = FSInputFile(speech_file_path)
        await bot.send_voice(chat_id, voice_message)
    except Exception as e:
        logger.error(f"Ошибка генерации TTS для текста '{text}': {e}")
        await bot.send_message(chat_id, "Извините, я не смог озвучить это сообщение. Попробуйте снова.")
    finally:
        if speech_file_path and speech_file_path.exists():
            speech_file_path.unlink()

async def generate_chatgpt_response(user_id: int, chosen_character: str) -> str:
    """Генерация ответа с использованием модели ChatGPT."""
    try:
        async with session_scope() as session:
            user = await get_user(session, user_id)
            user_level = user.level if user else "A1"
            history = await get_user_history(session, user_id)

            messages = [{"role": h.role, "content": h.content} for h in history][-config.MAX_HISTORY_LENGTH:]

            system_message = {
                "role": "system",
                "content": (
                    f"The user is at the {user_level} level. "
                    f"Your name is {chosen_character}. "
                    "You are an English learning assistant. "
                    "You need to use only English!!! "
                    "Act like a human, do not mention that you are a bot. "
                    "Imagine that you have your own opinion, feelings, etc. "
                    "Your goal is to help the user improve their English skills. "
                    "Use the provided context to maintain a coherent conversation. "
                    "Adjust your language complexity based on the user's level. "
                    "Keep your responses concise, avoid unnecessary details, and do not use special symbols like *, #, etc."
                )
            }

            messages.insert(0, system_message)

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages
            )

            return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Sorry, I couldn't generate a response at the moment."

@router.message(F.content_type == "voice")
async def handle_voice_message(message: Message, state: FSMContext) -> None:
    """Обработка голосового сообщения пользователя."""
    chat_id = message.chat.id

    audio_path = None
    try:
        voice_file = await bot.download(message.voice.file_id)
        audio_path = Path("user_voice.ogg")
        with audio_path.open("wb") as f:
            f.write(voice_file.read())

        with audio_path.open("rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        recognized_text = transcript.text.strip()

        if recognized_text:
            logger.info(f"Whisper recognized text for chat_id {chat_id}: {recognized_text}")
        else:
            logger.warning(f"Whisper failed to recognize the voice message for chat_id {chat_id}")

        if not recognized_text:
            async with session_scope() as session:
                user = await get_user(session, chat_id)
                language = user.language if user else 'en'
            await bot.send_message(chat_id,
                                   "Sorry, I couldn't understand the audio. Please try again." if language == 'en' else "Извините, я не смог распознать аудио. Пожалуйста, попробуйте снова.")
            return

        async with session_scope() as session:
            await add_to_history(session, chat_id, "user", recognized_text)
            user = await get_user(session, chat_id)
            chosen_character = user.chosen_character if user else "Lori"

        response_text = await generate_chatgpt_response(chat_id, chosen_character)

        logger.info(f"Generated response for user {chat_id}: {response_text}")

        await send_tts_message(chat_id, response_text, config.CHARACTER_VOICES[chosen_character])
        async with session_scope() as session:
            user = await get_user(session, chat_id)
            language = user.language if user else 'en'
        await bot.send_message(chat_id, response_text, reply_markup=create_back_button(language))

        async with session_scope() as session:
            await add_to_history(session, chat_id, "assistant", response_text)
    finally:
        if audio_path and audio_path.exists():
            audio_path.unlink()

@router.message(Command(commands=['level', 'notification', 'grammar', 'practice', 'dictionary', 'talk', 'info']))
async def handle_command(message: Message, state: FSMContext) -> None:
    command = message.text[1:].lower()  # Извлечение команды без "/"
    if command == "level":
        await handle_level_button(message)
    elif command == "notification":
        await handle_notification(message)
    elif command == "grammar":
        await handle_grammar_button(message)
    elif command == "practice":
        await handle_practice_button(message, state)
    elif command == "dictionary":
        await handle_dict_button(message, state)
    elif command == "talk":
        await start_talk(message, state)
    elif command == "info":
        await handle_info_button(message)


""" Запуск бота """

async def main() -> None:
    await create_db()
    await setup()  # Вызов функции setup, которая загружает словарь в базу данных
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
