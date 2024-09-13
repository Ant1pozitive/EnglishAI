from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from typing_extensions import List


def create_back_button(language: str = 'en') -> InlineKeyboardMarkup:
    """Создание кнопки возврата в главное меню."""
    text = "Go back" if language == 'en' else "Вернуться назад"
    buttons = [[InlineKeyboardButton(text=text, callback_data="go_back")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def create_continue_back_buttons(language: str = 'en') -> InlineKeyboardMarkup:
    """Создание кнопок для продолжения или возврата в главное меню."""
    buttons = [
        [InlineKeyboardButton(text="Continue" if language == 'en' else "Продолжить", callback_data="continue")],
        [InlineKeyboardButton(text="Go back" if language == 'en' else "Вернуться назад", callback_data="go_back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def create_navigation_buttons(language: str = 'en') -> ReplyKeyboardMarkup:
    """Создание кнопок для основного меню."""
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

def create_level_buttons(language: str = 'en') -> InlineKeyboardMarkup:
    """Создание кнопок для выбора уровня языка."""
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

def create_notification_buttons(language: str = 'en') -> ReplyKeyboardMarkup:
    """Создание кнопок для настройки уведомлений."""
    buttons_en = [
        [KeyboardButton(text="Enable Notifications"), KeyboardButton(text="Disable Notifications")]
    ]

    buttons_ru = [
        [KeyboardButton(text="Включить уведомления"), KeyboardButton(text="Отключить уведомления")]
    ]

    return ReplyKeyboardMarkup(keyboard=buttons_en if language == 'en' else buttons_ru, resize_keyboard=True)

def create_days_buttons(selected_days: List[str], language: str = 'en') -> InlineKeyboardMarkup:
    """Создание кнопок для выбора дней недели для уведомлений."""
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

def create_dict_menu_buttons(language: str = 'en') -> ReplyKeyboardMarkup:
    """Создание кнопок для меню словаря."""
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

    return ReplyKeyboardMarkup(keyboard=buttons_en if language == 'en' else buttons_ru, one_time_keyboard=True, resize_keyboard=True)

def create_support_buttons(language: str = 'en') -> InlineKeyboardMarkup:
    buttons_en = [
        [InlineKeyboardButton(text="Join Blum", url="https://t.me/blum/app?startapp=ref_QB8T442IqO")],
        [InlineKeyboardButton(text="Join Tapswap", url="https://t.me/tapswap_mirror_1_bot?start=r_1110386065")],
        [InlineKeyboardButton(text="Join X Empire", url="https://t.me/empirebot/game?startapp=hero1110386065")],
        [InlineKeyboardButton(text="Join TON DAO", url="https://t.me/tonxdao_bot?start=dao_1110386065_155020")],
        [InlineKeyboardButton(text="Join BITS", url="https://t.me/BitsTonboxBot/BitsAirdrops?startapp=RBdHMC9jCZDnfHzjKQNH8V")],
        [InlineKeyboardButton(text="Join W-coin", url="https://t.me/wcoin_tapbot?start=MTExMDM4NjA2NQ==")],
        [InlineKeyboardButton(text="Join FreeDogs", url="https://t.me/theFreeDogs_bot/app?startapp=ref_LzcJ0VvB")],
        [InlineKeyboardButton(text="Join Hrum", url="https://t.me/hrummebot/game?startapp=ref1110386065")],
        [InlineKeyboardButton(text="Join KuCoin", url="https://t.me/xkucoinbot/kucoinminiapp?startapp=cm91dGU9JTJGdGFwLWdhbWUlM0ZpbnZpdGVyVXNlcklkJTNEMTExMDM4NjA2NSUyNnJjb2RlJTNE")],
        [InlineKeyboardButton(text="Join Major", url="https://t.me/major/start?startapp=1110386065")],
        [InlineKeyboardButton(text="Join Agent 301", url="https://t.me/Agent301Bot/app?startapp=onetime1110386065")],
        [InlineKeyboardButton(text="Join Dropee", url="https://t.me/DropeeBot/play?startapp=ref_IX83lhYhO3v")],
        [InlineKeyboardButton(text="Go back", callback_data="go_back")]
    ]

    buttons_ru = [
        [InlineKeyboardButton(text="Присоединиться к Blum", url="https://t.me/blum/app?startapp=ref_QB8T442IqO")],
        [InlineKeyboardButton(text="Присоединиться к Tapswap", url="https://t.me/tapswap_mirror_1_bot?start=r_1110386065")],
        [InlineKeyboardButton(text="Присоединиться к X Empire", url="https://t.me/empirebot/game?startapp=hero1110386065")],
        [InlineKeyboardButton(text="Присоединиться к TON DAO", url="https://t.me/tonxdao_bot?start=dao_1110386065_155020")],
        [InlineKeyboardButton(text="Присоединиться к BITS", url="https://t.me/BitsTonboxBot/BitsAirdrops?startapp=RBdHMC9jCZDnfHzjKQNH8V")],
        [InlineKeyboardButton(text="Присоединиться к W-coin", url="https://t.me/wcoin_tapbot?start=MTExMDM4NjA2NQ==")],
        [InlineKeyboardButton(text="Присоединиться к FreeDogs", url="https://t.me/theFreeDogs_bot/app?startapp=ref_LzcJ0VvB")],
        [InlineKeyboardButton(text="Присоединиться к Hrum", url="https://t.me/hrummebot/game?startapp=ref1110386065")],
        [InlineKeyboardButton(text="Присоединиться к KuCoin", url="https://t.me/xkucoinbot/kucoinminiapp?startapp=cm91dGU9JTJGdGFwLWdhbWUlM0ZpbnZpdGVyVXNlcklkJTNEMTExMDM4NjA2NSUyNnJjb2RlJTNE")],
        [InlineKeyboardButton(text="Присоединиться к Major", url="https://t.me/major/start?startapp=1110386065")],
        [InlineKeyboardButton(text="Присоединиться к Agent 301", url="https://t.me/Agent301Bot/app?startapp=onetime1110386065")],
        [InlineKeyboardButton(text="Присоединиться к Dropee", url="https://t.me/DropeeBot/play?startapp=ref_IX83lhYhO3v")],
        [InlineKeyboardButton(text="Вернуться назад", callback_data="go_back")]
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons_en if language == 'en' else buttons_ru)

