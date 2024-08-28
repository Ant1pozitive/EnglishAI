import asyncio
import difflib
import logging
import sys
import random
import os
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager

import contractions
import openai
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import StateFilter, CommandStart
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, \
    FSInputFile
from aiogram import Router
from aiogram.fsm.context import FSMContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, String, Integer, Text, ForeignKey, and_
from sqlalchemy.orm import sessionmaker, declarative_base

""" Загрузка переменных окружения """
load_dotenv()

# Установка токенов и моделей
TOKEN = os.getenv('TELEGRAM_TOKEN')
PROXY_API_KEY = os.getenv('PROXY_API')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', mode='w', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

""" Настройка базы данных """
DATABASE_URL = "sqlite:///bot_data.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Session rollback due to: {e}")
        raise
    finally:
        session.close()


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


# Создание таблиц
Base.metadata.create_all(bind=engine)

# Создание клиента OpenAI
client = openai.OpenAI(api_key=PROXY_API_KEY, base_url="https://api.proxyapi.ru/openai/v1")

# Глобальные переменные и константы
MAX_HISTORY_LENGTH = 5

level_mapping = {
    'A1': 'A1-A2',
    'A2': 'A1-A2',
    'B1': 'B1-B2',
    'B2': 'B1-B2',
    'C1': 'C1-C2',
    'C2': 'C1-C2'
}

greetings = {
    'A1': ["Hello! My name is {name}. How can I help you today?",
           "Hi! I'm {name}. What would you like to talk about today?"],
    'A2': ["Hello! I'm {name}. What can I do for you today?", "Hi! I'm {name}. What topic would you like to discuss?"],
    'B1': ["Hi there! I'm {name}. How can I assist you with your English?",
           "Hello! I'm {name}. What would you like to talk about?"],
    'B2': ["Hello! My name is {name}. How can I assist you in your English journey?",
           "Hi! I'm {name}. What can I do for you today?"],
    'C1': ["Hi! I'm {name}. Let's dive into advanced topics. What would you like to discuss?",
           "Hello! My name is {name}. How can I support your advanced English learning today?"],
    'C2': ["Hello! I'm {name}. Let's talk about something challenging today. What's on your mind?",
           "Hi! My name is {name}. How can I assist with your high-level English skills?"]
}

CHARACTER_VOICES = {
    "Lori": "nova",
    "Kiko": "fable",
    "Nancy": "shimmer",
    "Broot": "echo",
    "default": "alloy"
}

reminder_messages_en = [
    "Hello, I missed you. Let's practice!",
    "Time to practice your English!",
    "Don't forget to practice today!",
    "Let's improve your English skills!",
    "A little practice goes a long way!",
    "Ready for some English practice?",
    "It's practice time!",
    "Time to sharpen your English skills!",
    "Keep up the great work! Practice time!",
    "Let's continue your English journey!"
]

reminder_messages_ru = [
    "Привет, я скучал по тебе. Давай практиковаться!",
    "Время практиковать свой английский!",
    "Не забудь попрактиковаться сегодня!",
    "Давайте улучшим ваши навыки английского!",
    "Немного практики имеет большое значение!",
    "Готов к практике английского?",
    "Пора тренироваться!",
    "Время совершенствовать свои навыки английского!",
    "Продолжай в том же духе! Время практиковаться!",
    "Давайте продолжим ваше путешествие по английскому!"
]

# Настройка бота, диспетчера и планировщика
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
scheduler = AsyncIOScheduler()

""" Функции для работы с базой данных """


def get_user(session, chat_id):
    try:
        return session.query(User).filter(User.chat_id == chat_id).first()
    except Exception as e:
        logger.error(f"Error fetching user: {e}")
        return None


def get_user_history(session, user_id):
    try:
        return session.query(UserHistory).filter(UserHistory.user_id == user_id).order_by(UserHistory.id).all()
    except Exception as e:
        logger.error(f"Error fetching user history: {e}")
        return []


def save_user_history(session, user_id, history):
    try:
        session.query(UserHistory).filter(UserHistory.user_id == user_id).delete()
        for entry in history:
            new_entry = UserHistory(user_id=user_id, role=entry.role, content=entry.content)
            session.add(new_entry)
        session.commit()
    except Exception as e:
        logger.error(f"Error saving user history: {e}")
        session.rollback()


def add_to_history(session, user_id, role, message):
    try:
        history = get_user_history(session, user_id)

        if len(history) >= MAX_HISTORY_LENGTH * 2:
            history = history[2:]

        new_entry = UserHistory(user_id=user_id, role=role, content=message)
        session.add(new_entry)
        session.commit()
    except Exception as e:
        logger.error(f"Error adding to history: {e}")
        session.rollback()


def load_dictionary_into_db(dictionary_data, session):
    try:
        for level, words in dictionary_data.items():
            for word, info in words.items():
                if not session.query(Dictionary).filter_by(level=level, word=word).first():
                    new_word = Dictionary(
                        level=level,
                        word=word.capitalize(),
                        definition=info['definition'],
                        translation=info['translation']
                    )
                    session.add(new_word)
                    session.commit()
    except Exception as e:
        logger.error(f"Error loading dictionary into DB: {e}")
        session.rollback()


def remove_duplicates_from_db(session):
    try:
        words_seen = set()
        duplicates = session.query(Dictionary).all()
        for entry in duplicates:
            word_key = (entry.level, entry.word)
            if word_key in words_seen:
                session.delete(entry)
                session.commit()
            else:
                words_seen.add(word_key)
    except Exception as e:
        logger.error(f"Error removing duplicates from DB: {e}")
        session.rollback()


""" Функции для работы с уведомлениями """


async def schedule_notifications(chat_id, days, time, language='en'):
    hours, minutes = map(int, time.split(":"))
    job_id = f"notification_{chat_id}"

    # Удаление старых задач перед добавлением новых
    existing_jobs = scheduler.get_jobs()
    for job in existing_jobs:
        if job.id.startswith(job_id):
            scheduler.remove_job(job.id)

    for day in days:
        try:
            scheduler.add_job(send_reminder, 'cron', day_of_week=day, hour=hours, minute=minutes, id=f"{job_id}_{day}",
                              args=[chat_id, language])
        except Exception as e:
            logging.error(f"Error scheduling notification for {day}: {e}")
            await bot.send_message(chat_id, f"Failed to schedule notification for {day.capitalize()}.")

    # Проверяем, запущен ли планировщик
    if not scheduler.running:
        scheduler.start()


async def send_reminder(chat_id, language):
    reminder_messages = reminder_messages_ru if language == 'ru' else reminder_messages_en
    await bot.send_message(chat_id, random.choice(reminder_messages))


""" Обработка команды /start """


class LanguageStates(StatesGroup):
    choosing_language = State()


@router.message(CommandStart())
async def send_welcome(message: Message, state: FSMContext):
    chat_id = message.chat.id
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="English", callback_data="set_lang_en")],
        [InlineKeyboardButton(text="Русский", callback_data="set_lang_ru")]
    ])
    await state.set_state(LanguageStates.choosing_language)
    await bot.send_message(chat_id, "Please select your language / Пожалуйста, выберите язык", reply_markup=markup)


@router.callback_query(F.data.startswith("set_lang_"))
async def set_language(callback_query: types.CallbackQuery, state: FSMContext):
    language = callback_query.data.split("_")[-1]
    chat_id = callback_query.message.chat.id

    with session_scope() as session:
        user = get_user(session, chat_id)
        if user:
            user.language = language
        else:
            user = User(chat_id=chat_id, language=language)
            session.add(user)

    if language == 'ru':
        await bot.send_message(chat_id, "Добро пожаловать в бот для изучения английского!",
                               reply_markup=create_navigation_buttons('ru'))
    else:
        await bot.send_message(chat_id, "Welcome to the English Learning Bot!",
                               reply_markup=create_navigation_buttons('en'))

    await state.clear()


""" Обработка выбора уровня """


@router.message(F.text.in_({"Level", "Уровень"}))
async def handle_level_button(message: Message):
    with session_scope() as session:
        user = get_user(session, message.chat.id)
        language = user.language if user else 'en'
    markup = create_level_buttons(language)
    await bot.send_message(message.chat.id, "Choose your level:" if language == 'en' else "Выберите свой уровень:",
                           reply_markup=markup)


@router.callback_query(F.data.startswith("set_level_"))
async def set_user_level(callback_query: types.CallbackQuery):
    level = callback_query.data[len('set_level_'):]
    chat_id = callback_query.message.chat.id

    with session_scope() as session:
        user = get_user(session, chat_id)
        if user:
            user.level = level
    logging.info(f"User {chat_id} set their level to {level}")

    with session_scope() as session:
        user = get_user(session, callback_query.message.chat.id)
        language = user.language if user else 'en'

    message = f"Your level has been set to {level}." if language == 'en' else f"Ваш уровень установлен на {level}."
    await bot.send_message(callback_query.message.chat.id, message)


""" Обработка информации """


@router.message(F.text.in_({"Info", "Информация"}))
async def handle_info_button(message: Message):
    with session_scope() as session:
        user = get_user(session, message.chat.id)
        language = user.language if user else 'en'

    info_text_en = (
        "<b>/start</b>: Begin interaction with the bot and see the main menu.\n\n"
        "<b>Level</b>: Set your English level to ensure the content matches your skill level.\n\n"
        "<b>Notification</b>: Enable or disable daily practice notifications and set the time to receive them.\n\n"
        "<b>Grammar</b>: Learn grammar rules and practice exercises based on your level.\n\n"
        "<b>Practice</b>: Test your knowledge with grammar exercises.\n\n"
        "<b>Dictionary</b>: Add, learn, and see the meaning of words based on your level.\n\n"
        "<b>Talk</b>: Engage in a conversation with the bot, tailored to your English level.\n\n"
        "<b>Info</b>: See all available commands and how to use them."
    )

    info_text_ru = (
        "<b>/start</b>: Начните взаимодействие с ботом и откройте главное меню.\n\n"
        "<b>Уровень</b>: Установите свой уровень английского, чтобы контент соответствовал вашим навыкам.\n\n"
        "<b>Уведомление</b>: Включите или отключите ежедневные уведомления о практике и установите время их получения.\n\n"
        "<b>Грамматика</b>: Учите правила грамматики и выполняйте упражнения в зависимости от вашего уровня.\n\n"
        "<b>Практика</b>: Проверьте свои знания с помощью упражнений по грамматике.\n\n"
        "<b>Словарь</b>: Добавляйте слова, учите их и смотрите их значение в зависимости от вашего уровня.\n\n"
        "<b>Разговор</b>: Поговорите с ботом на английском, адаптированном под ваш уровень.\n\n"
        "<b>Информация</b>: Посмотрите все доступные команды и узнайте, как ими пользоваться."
    )

    info_text = info_text_en if language == 'en' else info_text_ru
    await bot.send_message(message.chat.id, info_text, parse_mode="html")


""" Обработка уведомлений """


class NotificationStates(StatesGroup):
    days = State()
    time = State()


@router.message(F.text.in_({"Notification", "Уведомление"}))
async def handle_notification(message: Message):
    with session_scope() as session:
        user = get_user(session, message.chat.id)
        language = user.language if user else 'en'

    markup = create_notification_buttons(language)
    await bot.send_message(message.chat.id,
                           "Do you want to enable or disable notifications?" if language == 'en' else "Вы хотите включить или отключить уведомления?",
                           reply_markup=markup)


@router.message(F.text.in_({"Enable Notifications", "Включить уведомления"}))
async def enable_notifications(message: Message, state: FSMContext):
    await state.set_state(NotificationStates.days)
    with session_scope() as session:
        user = get_user(session, message.chat.id)
        selected_days = user.notification_days.split(',') if user and user.notification_days else []
        language = user.language if user else 'en'
    markup = create_days_buttons(selected_days, language)
    await bot.send_message(message.chat.id,
                           "Select days for notifications and click Save." if language == 'en' else "Выберите дни для уведомлений и нажмите Сохранить.",
                           reply_markup=markup)


@router.callback_query(F.data.startswith("toggle_"))
async def toggle_day(callback_query: types.CallbackQuery):
    day = callback_query.data[len('toggle_'):]
    chat_id = callback_query.message.chat.id

    with session_scope() as session:
        user = get_user(session, chat_id)
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
async def save_days(callback_query: types.CallbackQuery, state: FSMContext):
    with session_scope() as session:
        user = get_user(session, callback_query.message.chat.id)
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
async def set_notification_time(message: Message, state: FSMContext):
    chat_id = message.chat.id
    user_input = message.text.strip()

    try:
        valid_time = datetime.strptime(user_input, "%H:%M")
        valid_time_utc = valid_time - timedelta(hours=3)

        data = await state.get_data()
        selected_days_lower = data.get("selected_days_lower", [])

        # Сохранение времени уведомлений в базу данных
        with session_scope() as session:
            user = get_user(session, chat_id)
            if user:
                user.notification_time = valid_time_utc.strftime("%H:%M")
                session.add(user)

        # Отправка подтверждения пользователю
        with session_scope() as session:
            user = get_user(session, chat_id)
            language = user.language if user else 'en'

        await bot.send_message(
            chat_id,
            f"Notifications will be sent on {', '.join([day.capitalize() for day in selected_days_lower])} at {valid_time.strftime('%H:%M')} (Moscow time)." if language == 'en' else f"Уведомления будут отправляться в {', '.join([day.capitalize() for day in selected_days_lower])} в {valid_time.strftime('%H:%M')} (Московское время).",
            reply_markup=create_navigation_buttons(language)
        )

        await schedule_notifications(chat_id, selected_days_lower, valid_time_utc.strftime("%H:%M"), language)
        await state.clear()

    except ValueError:
        with session_scope() as session:
            user = get_user(session, chat_id)
            language = user.language if user else 'en'
        await bot.send_message(chat_id,
                               "Please enter a valid time in HH:MM format." if language == 'en' else "Пожалуйста, введите допустимое время в формате ЧЧ:ММ.")


@router.message(F.text.in_({"Disable Notifications", "Отключить уведомления"}))
async def disable_notifications(message: Message, state: FSMContext):
    chat_id = message.chat.id
    job_id = f"notification_{chat_id}"

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    with session_scope() as session:
        user = get_user(session, chat_id)
        if user:
            user.notification_time = None
            user.notification_days = None
            language = user.language if user else 'en'

    await bot.send_message(chat_id, "Notifications disabled." if language == 'en' else "Уведомления отключены.",
                           reply_markup=create_navigation_buttons(language))
    await state.clear()


""" Обработка грамматических упражнений """


@router.message(F.text.in_({"Grammar", "Грамматика"}))
async def handle_grammar_button(message: Message):
    with session_scope() as session:
        user = get_user(session, message.chat.id)
        language = user.language if user else 'en'
    await send_grammar_options(message, language)


def read_grammar_rules(file_path):
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


grammar_rules = read_grammar_rules("C:/Users/User/PycharmProjects/pythonProject/extra_files/grammar_rules.txt")


def create_grammar_buttons(language='en'):
    buttons = [[InlineKeyboardButton(text=title, callback_data=title)] for title in grammar_rules.keys()]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    return markup


async def send_grammar_options(message: Message, language):
    markup = create_grammar_buttons(language)
    await bot.send_message(message.chat.id,
                           "Choose grammar rule:" if language == 'en' else "Выберите правило грамматики:",
                           reply_markup=markup)


@router.callback_query(F.data.in_(grammar_rules.keys()))
async def handle_grammar_selection(callback_query: types.CallbackQuery):
    rule_text = grammar_rules[callback_query.data]
    await bot.send_message(callback_query.message.chat.id, rule_text, parse_mode="html")


def load_grammar_exercises(filepath):
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


grammar_exercises = load_grammar_exercises(
    'C:/Users/User/PycharmProjects/pythonProject/extra_files/grammar_exercises.txt')


@router.message(F.text.in_({"Practice", "Практика"}))
async def handle_practice_button(message: Message, state: FSMContext):
    with session_scope() as session:
        user = get_user(session, message.chat.id)
        language = user.language if user else 'en'
    await send_practice_info(message.chat.id, state, language)


async def send_practice_info(chat_id, state: FSMContext, language):
    await bot.send_message(chat_id,
                           "Welcome to the Practice section. Here you can practice various grammar rules depending on your level. Please select a grammar rule to start practicing." if language == 'en' else "Добро пожаловать в раздел практики. Здесь вы можете практиковать различные правила грамматики в зависимости от вашего уровня. Пожалуйста, выберите правило грамматики для начала практики.")
    with session_scope() as session:
        user = get_user(session, chat_id)
        level = user.level if user else 'A1'
    mapped_level = level_mapping.get(level, 'A1-A2')
    await send_practice_options(chat_id, mapped_level, state, language)


async def send_practice_exercise(chat_id, level, rule, state: FSMContext, language):
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


async def send_practice_options(chat_id, level, state: FSMContext, language):
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
async def handle_practice_selection(callback_query: types.CallbackQuery, state: FSMContext):
    rule = callback_query.data[len("practice_"):]
    chat_id = callback_query.message.chat.id

    with session_scope() as session:
        user = get_user(session, chat_id)
        language = user.language if user else 'en'
        level = user.level if user else 'A1'

    mapped_level = level_mapping.get(level, 'A1-A2')

    logging.info(f"User {chat_id} selected rule {rule} for practice.")

    await state.update_data(current_rule=rule, level=mapped_level, training_type="grammar")

    await send_practice_exercise(chat_id, mapped_level, rule, state, language)
    await state.set_state("practice")


@router.message(StateFilter("practice"))
async def handle_practice_message(message: Message, state: FSMContext):
    chat_id = message.chat.id
    data = await state.get_data()

    if "current_exercise" in data:
        question, correct_answer, rule = data["current_exercise"]
        correct_answer_normalized = contractions.fix(correct_answer.strip().lower())
        text_normalized = contractions.fix(message.text.strip().lower())

        with session_scope() as session:
            user = get_user(session, chat_id)
            language = user.language if user and user.language else 'en'

        if text_normalized == correct_answer_normalized or difflib.SequenceMatcher(None, text_normalized,
                                                                                   correct_answer_normalized).ratio() > 0.9:
            await bot.send_message(chat_id, "Correct!" if language == 'en' else "Правильно!",
                                   reply_markup=create_continue_back_buttons(language))
        else:
            await bot.send_message(chat_id,
                                   f"Incorrect. The correct answer is: {correct_answer}" if language == 'en' else f"Неправильно. Правильный ответ: {correct_answer}",
                                   reply_markup=create_continue_back_buttons(language))

        await state.update_data(current_exercise=None)
    else:
        # Получение языка из состояния перед отправкой сообщения
        with session_scope() as session:
            user = get_user(session, chat_id)
            language = user.language if user and user.language else 'en'

        await bot.send_message(chat_id,
                               "Please select a grammar rule to start practicing." if language == 'en' else "Пожалуйста, выберите правило грамматики для начала практики.",
                               reply_markup=create_navigation_buttons(language))


@router.callback_query(F.data == "continue")
async def handle_continue(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    training_type = data.get('training_type')
    chat_id = callback_query.message.chat.id

    with session_scope() as session:
        user = get_user(session, chat_id)
        language = user.language if user else 'en'

    if training_type == "grammar":
        rule = data.get("current_rule")
        level = data.get("level")

        if not rule or not level:
            await bot.send_message(callback_query.message.chat.id,
                                   "Grammar rule or level information is missing. Returning to the main menu." if language == 'en' else "Информация о правиле грамматики или уровне отсутствует. Возвращение в главное меню.",
                                   reply_markup=create_navigation_buttons(language))
            await state.clear()
            return

        await send_practice_exercise(callback_query.message.chat.id, level, rule, state, language)

    elif training_type == "words":
        level = data.get('level')
        if not level:
            await bot.send_message(callback_query.message.chat.id,
                                   "Level information is missing. Returning to the main menu." if language == 'en' else "Информация об уровне отсутствует. Возвращение в главное меню.",
                                   reply_markup=create_navigation_buttons(language))
            await state.clear()
            return

        await study_words(callback_query.message, level, state, practice=True)

    else:
        await bot.send_message(callback_query.message.chat.id,
                               "Invalid training type. Returning to the main menu." if language == 'en' else "Недопустимый тип тренировки. Возвращение в главное меню.",
                               reply_markup=create_navigation_buttons(language))
        await state.clear()


@router.callback_query(F.data == "go_back")
async def handle_go_back(callback_query: types.CallbackQuery, state: FSMContext):
    with session_scope() as session:
        user = get_user(session, callback_query.message.chat.id)
        language = user.language if user else 'en'

    await bot.send_message(callback_query.message.chat.id,
                           "Returning to the main menu." if language == 'en' else "Возвращение в главное меню.",
                           reply_markup=create_navigation_buttons(language))
    await state.clear()


""" Работа со словарём """


def read_dictionary_file(file_path):
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
        logging.error(f"Dictionary file not found at {file_path}")
        return {}
    except Exception as e:
        logging.error(f"Error reading dictionary file: {e}")
        return {}

    return dictionaries


dictionaries = read_dictionary_file('C:/Users/User/PycharmProjects/pythonProject/extra_files/dictionary.txt')

with session_scope() as session:
    load_dictionary_into_db(dictionaries, session)
    remove_duplicates_from_db(session)


@router.message(F.text.in_({"Dictionary", "Словарь"}))
async def handle_dict_button(message: Message, state: FSMContext):
    with session_scope() as session:
        user = get_user(session, message.chat.id)
        language = user.language if user else 'en'
    await show_dict_menu(message, language)


async def show_dict_menu(message: Message, language):
    markup = create_dict_menu_buttons(language)
    await bot.send_message(message.chat.id, 'Select an action:' if language == 'en' else 'Выберите действие:',
                           reply_markup=markup)


@router.message(StateFilter("add_word_state"))
async def add_word(message: Message, state: FSMContext):
    try:
        word, definition, translation = map(str.strip, message.text.split(' - '))
        word = word.lower()
        with session_scope() as session:
            user = get_user(session, message.chat.id)
            level = level_mapping.get(user.level, 'A1-A2')
            if not session.query(Dictionary).filter_by(level=level, word=word).first():
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
    with session_scope() as session:
        user = get_user(session, message.chat.id)
        language = user.language if user else 'en'
    await show_dict_menu(message, language)


@router.message(StateFilter("see_meaning_state"))
async def handle_see_meaning(message: Message, state: FSMContext):
    await show_word_definition(message)
    await state.clear()


@router.message(F.text.in_(
    ['Add words', 'Practice words', 'Learn words', 'See the meaning of a word', 'Go back', 'Добавить слова',
     'Практиковать слова', 'Учить слова', 'Посмотреть значение слова', 'Вернуться назад']))
async def process_dict_action(message: Message, state: FSMContext):
    action = message.text.strip()
    chat_id = message.chat.id
    with session_scope() as session:
        user = get_user(session, chat_id)
        level = level_mapping.get(user.level, 'A1-A2')
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


async def study_words(message: Message, level, state: FSMContext, practice: bool):
    with session_scope() as session:
        words = session.query(Dictionary).filter(Dictionary.level == level).all()
        words_data = [(word.word, word.translation) for word in words]

    if not words_data:
        with session_scope() as session:
            user = get_user(session, message.chat.id)
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
        with session_scope() as session:
            user = get_user(session, message.chat.id)
            language = user.language if user else 'en'
        await bot.send_message(message.chat.id,
                               "Select a word to learn:" if language == 'en' else "Выберите слово для изучения:",
                               reply_markup=markup)


@router.callback_query(F.data.startswith("learn_"))
async def handle_learn_word(callback_query: types.CallbackQuery):
    word = callback_query.data[len("learn_"):]  # Получаем слово

    with session_scope() as session:
        word_entry = session.query(Dictionary).filter(Dictionary.word == word).one_or_none()

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
async def handle_listen(callback_query: types.CallbackQuery):
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
            speech_file_path.unlink()  # Удаление файла в блоке finally


@router.message(StateFilter("check_translation_state"))
async def check_translation(message: Message, state: FSMContext):
    data = await state.get_data()
    word = data['word']
    correct_translation = data['correct_translation']

    chat_id = message.chat.id
    with session_scope() as session:
        user = get_user(session, chat_id)
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

    # Сохраняем тип тренировки как "words" и уровень пользователя
    with session_scope() as session:
        user = get_user(session, message.chat.id)
        level = level_mapping.get(user.level, 'A1-A2')
        await state.update_data(training_type="words", level=level)


async def show_word_definition(message: Message):
    word = message.text.strip().lower()
    chat_id = message.chat.id

    with session_scope() as session:
        user = get_user(session, chat_id)
        level = level_mapping.get(user.level, 'A1-A2')
        language = user.language if user else 'en'

        word_entry = session.query(Dictionary).filter(
            and_(Dictionary.level == level, Dictionary.word == word)
        ).first()

    if word_entry:
        await bot.send_message(
            message.chat.id,
            f'<b>Definition:</b> {word_entry.definition}\n<b>Translation:</b> {word_entry.translation}'
        )
    else:
        await bot.send_message(message.chat.id,
                               'The word was not found in the dictionary.' if language == 'en' else 'Слово не найдено в словаре.')


""" Функции для общения и озвучки """

CHARACTER_IMAGES = {
    "Lori": "C:/Users/User/PycharmProjects/pythonProject/images/Lori_image.jpg",
    # Замените на реальный путь к изображению Lori
    "Kiko": "C:/Users/User/PycharmProjects/pythonProject/images/Kiko_image.jpg",
    # Замените на реальный путь к изображению Kiko
    "Nancy": "C:/Users/User/PycharmProjects/pythonProject/images/Nancy_image.jpg",
    # Замените на реальный путь к изображению Nancy
    "Broot": "C:/Users/User/PycharmProjects/pythonProject/images/Broot_image.jpg"
    # Замените на реальный путь к изображению Broot
}

CHARACTERS = ["Lori", "Kiko", "Nancy", "Broot"]


@router.message(F.text.in_({"Talk", "Разговор"}))
async def start_talk(message: Message, state: FSMContext):
    chat_id = message.chat.id

    # Создание кнопок с персонажами
    buttons = [
        [InlineKeyboardButton(text="Lori 🐱", callback_data="choose_Lori")],
        [InlineKeyboardButton(text="Kiko 🐥", callback_data="choose_Kiko")],
        [InlineKeyboardButton(text="Nancy 🦦", callback_data="choose_Nancy")],
        [InlineKeyboardButton(text="Broot 🐶", callback_data="choose_Broot")]
    ]

    markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Отправка сообщений с изображениями и кнопками
    for character in CHARACTERS:
        photo = FSInputFile(CHARACTER_IMAGES[character])
        await bot.send_photo(chat_id, photo, caption=f"{character} is ready to chat with you!")

    await bot.send_message(chat_id, "Choose your character:", reply_markup=markup)
    await state.set_state("choose_character")


@router.callback_query(F.data.startswith("choose_"))
async def handle_character_choice(callback_query: types.CallbackQuery, state: FSMContext):
    chosen_character = callback_query.data.split("_")[-1]
    chat_id = callback_query.message.chat.id

    # Сохранение выбранного персонажа и голоса в базу данных
    with session_scope() as session:
        user = get_user(session, chat_id)
        if user:
            user.chosen_character = chosen_character
            user_level = user.level  # Сохраняем уровень и язык в переменные, чтобы использовать после закрытия сессии
            language = user.language
        else:
            user = User(chat_id=chat_id, chosen_character=chosen_character)
            session.add(user)
            user_level = "A1"  # Значение по умолчанию, если пользователь новый
            language = 'en'
        session.commit()

    # Формирование приветственного сообщения
    greeting = random.choice(greetings[user_level]).format(name=chosen_character)

    # Отправка изображения и приветственного сообщения
    if CHARACTER_IMAGES.get(chosen_character):
        photo = FSInputFile(CHARACTER_IMAGES[chosen_character])
        await bot.send_photo(chat_id, photo, caption=f"{chosen_character} is ready to chat with you!")

    # Отправка голосового приветствия
    await send_tts_message(chat_id, greeting, CHARACTER_VOICES[chosen_character])
    await bot.send_message(chat_id, greeting, reply_markup=create_back_button(language))

    await state.clear()


async def send_tts_message(chat_id, text, voice="echo"):
    speech_file_path = None
    try:
        # Добавляем паузу перед текстом для улучшения интерпретации TTS
        text_with_pause = f"... {text}"

        speech_file_path = Path("speech.mp3")

        # Генерация аудио с помощью TTS
        with client.audio.speech.with_streaming_response.create(
                model="tts-1-hd",
                voice=voice,
                input=text_with_pause
        ) as response:
            response.stream_to_file(speech_file_path)

        # Проверка на пустой или некорректный файл
        if speech_file_path.stat().st_size == 0:
            raise Exception("TTS generated an empty file.")

        # Отправка голосового сообщения пользователю
        voice_message = FSInputFile(speech_file_path)
        await bot.send_voice(chat_id, voice_message)
    except Exception as e:
        logging.error(f"Ошибка генерации TTS для текста '{text}': {e}")
        # Можете добавить код для повторной попытки или уведомления пользователя
        await bot.send_message(chat_id, "Извините, я не смог озвучить это сообщение. Попробуйте снова.")
    finally:
        # Удаляем временный файл
        if speech_file_path and speech_file_path.exists():
            speech_file_path.unlink()


async def generate_chatgpt_response(user_id, chosen_character):
    try:
        with session_scope() as session:
            user = get_user(session, user_id)
            user_level = user.level if user else "A1"
            history = get_user_history(session, user_id)

            messages = [{"role": h.role, "content": h.content} for h in history][-MAX_HISTORY_LENGTH:]

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
        logging.error(f"OpenAI API error: {e}")
        return "Sorry, I couldn't generate a response at the moment."


@router.message(F.content_type == "voice")
async def handle_voice_message(message: Message, state: FSMContext):
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
            logging.info(f"Whisper recognized text for chat_id {chat_id}: {recognized_text}")
        else:
            logging.warning(f"Whisper failed to recognize the voice message for chat_id {chat_id}")

        if not recognized_text:
            with session_scope() as session:
                user = get_user(session, chat_id)
                language = user.language if user else 'en'
            await bot.send_message(chat_id,
                                   "Sorry, I couldn't understand the audio. Please try again." if language == 'en' else "Извините, я не смог распознать аудио. Пожалуйста, попробуйте снова.")
            return

        with session_scope() as session:
            add_to_history(session, chat_id, "user", recognized_text)
            user = get_user(session, chat_id)
            chosen_character = user.chosen_character if user else "Lori"

        response_text = await generate_chatgpt_response(chat_id, chosen_character)

        logging.info(f"Generated response for user {chat_id}: {response_text}")

        await send_tts_message(chat_id, response_text, CHARACTER_VOICES[chosen_character])
        with session_scope() as session:
            user = get_user(session, chat_id)
            language = user.language if user else 'en'
        await bot.send_message(chat_id, response_text, reply_markup=create_back_button(language))

        with session_scope() as session:
            add_to_history(session, chat_id, "assistant", response_text)
    finally:
        if audio_path and audio_path.exists():
            audio_path.unlink()


""" Вспомогательные функции для кнопок """


def create_back_button(language='en'):
    text = "Go back" if language == 'en' else "Вернуться назад"
    buttons = [[InlineKeyboardButton(text=text, callback_data="go_back")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_continue_back_buttons(language='en'):
    buttons = [
        [InlineKeyboardButton(text="Continue" if language == 'en' else "Продолжить", callback_data="continue")],
        [InlineKeyboardButton(text="Go back" if language == 'en' else "Вернуться назад", callback_data="go_back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_navigation_buttons(language='en'):
    buttons_en = [
        [KeyboardButton(text="Level"), KeyboardButton(text="Notification")],
        [KeyboardButton(text="Grammar"), KeyboardButton(text="Practice")],
        [KeyboardButton(text="Dictionary"), KeyboardButton(text="Talk")],
        [KeyboardButton(text="Info")]
    ]

    buttons_ru = [
        [KeyboardButton(text="Уровень"), KeyboardButton(text="Уведомление")],
        [KeyboardButton(text="Грамматика"), KeyboardButton(text="Практика")],
        [KeyboardButton(text="Словарь"), KeyboardButton(text="Разговор")],
        [KeyboardButton(text="Информация")]
    ]

    markup = ReplyKeyboardMarkup(keyboard=buttons_en if language == 'en' else buttons_ru, resize_keyboard=True)
    return markup


def create_level_buttons(language='en'):
    buttons_en = [
        [InlineKeyboardButton(text=level, callback_data=f"set_level_{level}") for level in
         ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']],
        [InlineKeyboardButton(text="I don't know my level", url="https://english.lingolia.com/en/test")]
    ]

    buttons_ru = [
        [InlineKeyboardButton(text=level, callback_data=f"set_level_{level}") for level in
         ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']],
        [InlineKeyboardButton(text="Я не знаю свой уровень", url="https://english.lingolia.com/en/test")]
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons_en if language == 'en' else buttons_ru)


def create_notification_buttons(language='en'):
    buttons_en = [
        [KeyboardButton(text="Enable Notifications"), KeyboardButton(text="Disable Notifications")]
    ]

    buttons_ru = [
        [KeyboardButton(text="Включить уведомления"), KeyboardButton(text="Отключить уведомления")]
    ]

    return ReplyKeyboardMarkup(keyboard=buttons_en if language == 'en' else buttons_ru, resize_keyboard=True)


def create_days_buttons(selected_days, language='en'):
    day_translations = {
        'Monday': 'Понедельник',
        'Tuesday': 'Вторник',
        'Wednesday': 'Среда',
        'Thursday': 'Четверг',
        'Friday': 'Пятница',
        'Saturday': 'Суббота',
        'Sunday': 'Воскресенье'
    }

    buttons = [
        [InlineKeyboardButton(
            text=f"Monday {'✅' if 'Monday' in selected_days else ''}" if language == 'en' else f"{day_translations['Monday']} {'✅' if 'Monday' in selected_days else ''}",
            callback_data="toggle_Monday")],
        [InlineKeyboardButton(
            text=f"Tuesday {'✅' if 'Tuesday' in selected_days else ''}" if language == 'en' else f"{day_translations['Tuesday']} {'✅' if 'Tuesday' in selected_days else ''}",
            callback_data="toggle_Tuesday")],
        [InlineKeyboardButton(
            text=f"Wednesday {'✅' if 'Wednesday' in selected_days else ''}" if language == 'en' else f"{day_translations['Wednesday']} {'✅' if 'Wednesday' in selected_days else ''}",
            callback_data="toggle_Wednesday")],
        [InlineKeyboardButton(
            text=f"Thursday {'✅' if 'Thursday' in selected_days else ''}" if language == 'en' else f"{day_translations['Thursday']} {'✅' if 'Thursday' in selected_days else ''}",
            callback_data="toggle_Thursday")],
        [InlineKeyboardButton(
            text=f"Friday {'✅' if 'Friday' in selected_days else ''}" if language == 'en' else f"{day_translations['Friday']} {'✅' if 'Friday' in selected_days else ''}",
            callback_data="toggle_Friday")],
        [InlineKeyboardButton(
            text=f"Saturday {'✅' if 'Saturday' in selected_days else ''}" if language == 'en' else f"{day_translations['Saturday']} {'✅' if 'Saturday' in selected_days else ''}",
            callback_data="toggle_Saturday")],
        [InlineKeyboardButton(
            text=f"Sunday {'✅' if 'Sunday' in selected_days else ''}" if language == 'en' else f"{day_translations['Sunday']} {'✅' if 'Sunday' in selected_days else ''}",
            callback_data="toggle_Sunday")],
        [InlineKeyboardButton(text="Save" if language == 'en' else "Сохранить", callback_data="save_days")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_dict_menu_buttons(language='en'):
    buttons_en = [
        [KeyboardButton(text='Add words'), KeyboardButton(text='Practice words')],
        [KeyboardButton(text='Learn words'), KeyboardButton(text='See the meaning of a word')],
        [KeyboardButton(text='Go back')]
    ]

    buttons_ru = [
        [KeyboardButton(text='Добавить слова'), KeyboardButton(text='Практиковать слова')],
        [KeyboardButton(text='Учить слова'), KeyboardButton(text='Посмотреть значение слова')],
        [KeyboardButton(text='Вернуться назад')]
    ]

    return ReplyKeyboardMarkup(keyboard=buttons_en if language == 'en' else buttons_ru, one_time_keyboard=True,
                               resize_keyboard=True)


""" Запуск бота """


async def main():
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
