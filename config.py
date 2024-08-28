from dotenv import load_dotenv
import os

load_dotenv()

# Токены и API ключи
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
PROXY_API_KEY = os.getenv('PROXY_API')

# База данных
DATABASE_URL = "sqlite+aiosqlite:///bot_data.db"

# Логирование
LOGGING_LEVEL = "INFO"
LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOGGING_FILE = 'bot.log'

# История
MAX_HISTORY_LENGTH = 5

# Карты уровней
LEVEL_MAPPING = {
    'A1': 'A1-A2',
    'A2': 'A1-A2',
    'B1': 'B1-B2',
    'B2': 'B1-B2',
    'C1': 'C1-C2',
    'C2': 'C1-C2'
}

# Приветственные сообщения
GREETINGS = {
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

# Голоса персонажей
CHARACTER_VOICES = {
    "Lori": "nova",
    "Kiko": "fable",
    "Nancy": "shimmer",
    "Broot": "echo",
    "default": "alloy"
}

# Сообщения напоминаний
REMINDER_MESSAGES = {
    'en': [
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
    ],
    'ru': [
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
}

# Пути к файлам
GRAMMAR_RULES_FILE = "/root/EnglishAI/extra_files/grammar_rules.txt"
GRAMMAR_EXERCISES_FILE = "/root/EnglishAI/extra_files/grammar_exercises.txt"
DICTIONARY_FILE = "/root/EnglishAI/extra_files/dictionary.txt"
CHARACTER_IMAGES = {
    "Lori": "/root/EnglishAI/images/Lori_image.jpg",
    "Kiko": "/root/EnglishAI/images/Kiko_image.jpg",
    "Nancy": "/root/EnglishAI/images/Nancy_image.jpg",
    "Broot": "/root/EnglishAI/images/Broot_image.jpg"
}
