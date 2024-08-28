#!/bin/bash

# Загружаем переменные окружения из .env
source /root/EnglishAI/.env

# Активируем виртуальную среду
source /root/EnglishAI/botenv/bin/activate

# Запускаем бота
python /root/EnglishAI/bot.py

# Деактивируем виртуальную среду
deactivate

