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

# Голоса персонажей
CHARACTER_VOICES = {
    "Lori": "nova",
    "Kiko": "fable",
    "Nancy": "shimmer",
    "Broot": "echo",
    "default": "alloy"
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
