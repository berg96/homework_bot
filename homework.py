import logging
import os
import sys
import time

import requests
import telegram
from dotenv import load_dotenv

from exceptions import (
    AuthenticationError,
    EndpointError,
    EndpointUnavailableError,
    NoNewStatus,
    StatusError
)

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}

HW_STATUS = (None, None)
LAST_MESSAGE = None


def check_tokens():
    """Проверяет доступность переменных окружения."""
    return all([PRACTICUM_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID])


def send_message(bot, message):
    """Отправляет сообщение в Telegram чат."""
    global LAST_MESSAGE

    try:
        if message != LAST_MESSAGE:
            bot.send_message(TELEGRAM_CHAT_ID, message)
            logger.debug(f'Бот отправил сообщение "{message}"')
            LAST_MESSAGE = message

    except Exception as e:
        logger.error(f'Сбой при отправке сообщения в Telegram: {e}')


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса."""
    try:
        response = requests.get(
            ENDPOINT, headers=HEADERS, params={'from_date': timestamp}
        )
        if response.status_code != 200:
            raise EndpointUnavailableError(
                f'Сбой в работе программы: Эндпоинт {ENDPOINT} недоступен. '
                f'Код ответа API: {response.status_code}'
            )
        return response.json()

    except EndpointUnavailableError:
        raise
    except Exception as e:
        raise EndpointError(f'Сбой при запросе к эндпоинту {ENDPOINT}: {e}')


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
    expected_keys = {'homeworks', 'current_date'}

    if type(response) is not dict:
        raise TypeError(f'Ожидался словарь, получен {type(response)}')

    if expected_keys != set(response.keys()):
        if response['code'] == 'UnknownError':
            raise TypeError(response['error']['error'])
        elif response['code'] == 'not_authenticated':
            raise AuthenticationError(response['message'])
        else:
            raise KeyError('Отсутствуют ожидаемые ключи в ответе API: '
                           f'{expected_keys - set(response.keys())}')

    if type(response['homeworks']) is not list:
        raise TypeError(
            f'Ожидался список, получен: {type(response["homeworks"])}'
        )

    if not response['homeworks']:
        raise NoNewStatus('Нет нового статуса')


def parse_status(homework):
    """Извлекает из информации о конкретной домашней работе статус."""
    global HW_STATUS

    if 'status' in homework:
        if 'homework_name' in homework:
            if (homework['homework_name'], homework['status']) != HW_STATUS:
                if homework['status'] not in HOMEWORK_VERDICTS:
                    raise StatusError(
                        f'Получен неожиданный статус: {homework["status"]}'
                    )
                HW_STATUS = (homework['homework_name'], homework['status'])
                return (
                    f'Изменился статус проверки работы '
                    f'"{homework["homework_name"]}". '
                    f'{HOMEWORK_VERDICTS.get(homework["status"])}'
                )
        raise StatusError('Нет ожидаемого ключа: homework_name')
    raise StatusError('Нет ожидаемого ключа: status')


def main():
    """Основная логика работы бота."""
    if not check_tokens():
        logger.critical(
            '''Отсутствуют обязательные переменные окружения.
Программа принудительно остановлена.'''
        )
        sys.exit(0)
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    while True:
        try:
            response = get_api_answer(timestamp)
            check_response(response)
            timestamp = response['current_date']
            send_message(bot, parse_status(response['homeworks'][0]))

        except (
                AuthenticationError,
                EndpointError,
                EndpointUnavailableError,
                KeyError,
                StatusError,
                TypeError,

        ) as e:
            logger.error(e)
            send_message(bot, str(e))
        except NoNewStatus as nns:
            logger.debug(nns)
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.error(message)
            send_message(bot, message)
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
