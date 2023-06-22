import asyncio
import datetime
import logging
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ContentTypes
from aiogram.utils import executor
import config


logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.TOKEN)
dispatcher = Dispatcher(bot)
dispatcher.middleware.setup(LoggingMiddleware())

user_chats = set()

@dispatcher.pre_checkout_query_handler(lambda query: True)
async def pre_checkout_query(pre_checkout_q: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)


async def get_weather(api_key, city, chat_id):
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&lang=ru"
    response = requests.get(url)
    data = response.json()

    if response.status_code == 200:
        forecasts = data['list']

        for forecast in forecasts:
            timestamp = forecast['dt']
            date_time = datetime.datetime.fromtimestamp(timestamp)
            time = date_time.strftime('%H:%M')

            # Отправляем прогноз только на нужное время (21:00)
            if time == '21:00':
                temperature_kelvin = forecast['main']['temp']
                temperature_celsius = temperature_kelvin - 273.15
                weather_description = forecast['weather'][0]['description']

                # Получаем курс валют и биткоина
                currency_url = "https://api.exchangerate-api.com/v4/latest/RUB"
                currency_response = requests.get(currency_url)
                currency_data = currency_response.json()

                bitcoin_url = "https://api.coindesk.com/v1/bpi/currentprice/BTC.json"
                bitcoin_response = requests.get(bitcoin_url)
                bitcoin_data = bitcoin_response.json()

                usd_rate = round(1 / currency_data["rates"]["USD"], 2)
                eur_rate = round(1 / currency_data["rates"]["EUR"], 2)
                bitcoin_rate = round(float(bitcoin_data["bpi"]["USD"]["rate"].replace(",", "")), 2)

                # Формируем сообщение с прогнозом погоды и курсами валют и биткоина
                message = f"Погода в городе:\n"
                message += f"Вечером температура: {temperature_celsius:.1f}°C\n"
                message += f"Описание: {weather_description}\n\n"
                message += f"Курс валют:\n"
                message += f"Доллар (USD): {usd_rate} рублей\n"
                message += f"Евро (EUR): {eur_rate} рублей\n\n"
                message += f"Курс биткоина (BTC):\n"
                message += f"{bitcoin_rate}$"

                if chat_id is not None:
                    await bot.send_message(chat_id, message)
                break


async def send_daily_weather():
    city = config.city
    api_key = config.WEATHER_API

    while True:
        now = datetime.datetime.now()

        if now.hour == 11 and now.minute == 00:
            for chat_id in user_chats:
                await get_weather(api_key, city, chat_id)

        await asyncio.sleep(60)


@dispatcher.message_handler(Command("start"))
async def command_start(message: types.Message):
    chat_id = message.chat.id
    user_chats.add(chat_id)
    await bot.send_message(chat_id, "Добро пожаловать! Получайте ежедневный прогноз погоды в 11:00 и информацию о курсе валют и биткоина. " \
                                    "Для получения введите команду /forecast." \
                                    "Для просмотра своего баланса bitcoin кошелька введите команду /balance")


@dispatcher.message_handler(Command("forecast"))
async def command_weather(message: types.Message):
    chat_id = message.chat.id
    city = config.city
    api_key = config.WEATHER_API

    await get_weather(api_key, city, chat_id)



# Словарь для хранения кошельков пользователей
user_wallets = {}


@dispatcher.message_handler(Command("balance"))
async def command_balance(message: types.Message):
    chat_id = message.chat.id

    if chat_id in user_wallets:
        wallet = user_wallets[chat_id]
        balance_message = await get_balance_bitcoin(wallet)
        await bot.send_message(chat_id, balance_message)
    else:
        await bot.send_message(chat_id, "Пожалуйста, введите ваш биткоин кошелек: (для удаление его /reset)")
        # Регистрируем обработчик следующего сообщения от пользователя
        dispatcher.register_message_handler(save_wallet_and_show_balance, content_types=types.ContentTypes.TEXT)

@dispatcher.message_handler(Command("reset"))
async def command_delete_wallet(message: types.Message):
    chat_id = message.chat.id

    if chat_id in user_wallets:
        del user_wallets[chat_id]
        await bot.send_message(chat_id, "Ваш биткоин кошелек удален.")
    else:
        await bot.send_message(chat_id, "У вас нет сохраненного биткоин кошелька.")



async def save_wallet_and_show_balance(message: types.Message):
    chat_id = message.chat.id
    wallet = message.text

    user_wallets[chat_id] = wallet

    balance_message = await get_balance_bitcoin(wallet)
    await bot.send_message(chat_id, balance_message)

    # Удаляем обработчик следующего сообщения от пользователя
    dispatcher.unregister_message_handler(save_wallet_and_show_balance)


async def get_balance_bitcoin(wallet):
    # Формируем URL для получения информации о кошельке
    wallet_api_url = f"https://blockchain.info/rawaddr/{wallet}"

    # Формируем URL для получения текущей цены биткоина в долларах
    price_api_url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"

    price_api_url_rub = 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=rub'
    response = requests.get(price_api_url_rub)
    price_rub_bitcoin = response.json()['bitcoin']['rub']
    # Получаем информацию о кошельке с помощью запроса GET
    wallet_response = requests.get(wallet_api_url)
    wallet_data = wallet_response.json()

    # Извлекаем финальный баланс из данных кошелька и конвертируем его в биткоины
    balance = wallet_data["final_balance"] / 100000000

    # Получаем текущую цену биткоина в долларах с помощью запроса GET
    price_response = requests.get(price_api_url)

    # Получаем данные в формате JSON из ответа
    price_data = price_response.json()

    # Извлекаем цену биткоина в долларах из данных и вычисляем эквивалент баланса в долларах
    usd_price = price_data["bitcoin"]["usd"]
    usd_balance = balance * usd_price
    price_rub_bitcoin = balance * price_rub_bitcoin

    message = f"Баланс в BTC: {balance}\n"
    message += f"Баланс в USD: {usd_balance}\n"
    message += f"Баланс в RUB: {price_rub_bitcoin}"
    return message

def main():
    loop = asyncio.get_event_loop()
    loop.create_task(send_daily_weather())
    executor.start_polling(dispatcher, skip_updates=False)


if __name__ == '__main__':
    main()


