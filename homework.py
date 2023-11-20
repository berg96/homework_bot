import logging
import os
import sys
import time

import requests
import telegram
from dotenv import load_dotenv
from requests.exceptions import HTTPError, RequestException

from exceptions import AuthenticationError, ApiError

load_dotenv()

logger = logging.getLogger(__name__)
stream_handler = logging.StreamHandler(sys.stdout)
file_handler = logging.FileHandler(__file__ + '.log')

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

STATUS_CHANGE_MESSAGE = (
    'Изменился статус проверки работы "{homework_name}". {status}'
)
BOT_MESSAGE = 'Бот отправил сообщение "{message}"'
SEND_MESSAGE_ERROR = (
    'Сбой при отправке сообщения в Telegram "{message}" : {error}.'
)
API_ERROR_MESSAGE = (
    'Сбой в работе программы: {error}. '
    f'Эндпоинт: {ENDPOINT}. '
    'Код ответа API: {status_code}. '
    'Headers: {headers}, '
    'params: "from_date": {timestamp}.'
)


def check_tokens():
    """Проверяет доступность переменных окружения."""
    missing_tokens = None
    for token, value in {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
    }.items():
        if not value:
            logger.critical(
                f'Отсутствует обязательная переменная окружения: {token}.'
            )
            missing_tokens = True
    if missing_tokens:
        logger.critical('Программа принудительно остановлена.')
        raise ValueError('Отсутствуют обязательные переменные окружения')


def send_message(bot, message):
    """Отправляет сообщение в Telegram чат."""
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logger.debug(BOT_MESSAGE.format(message=message))

    except Exception as e:
        logger.exception(SEND_MESSAGE_ERROR.format(message=message, error=e))


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса."""
    try:
        response = requests.get(
            ENDPOINT, headers=HEADERS, params={'from_date': timestamp}
        )

    except RequestException as re:
        raise ApiError(
            API_ERROR_MESSAGE.format(
                error=re, status_code='unknown',
                headers=HEADERS, timestamp=timestamp
            )
        )

    if response.status_code != 200:
        raise HTTPError(
            API_ERROR_MESSAGE.format(
                error='HTTPError',
                status_code=response.status_code,
                headers=HEADERS,
                timestamp=timestamp
            )
        )

    response_dict = response.json()

    if response_dict.get('code') or response_dict.get('error'):
        if response_dict.get('code') == 'UnknownError':
            raise TypeError(
                API_ERROR_MESSAGE.format(
                    error=response_dict['error']['error'],
                    status_code=response.status_code,
                    headers=HEADERS,
                    timestamp=timestamp
                )
            )
        elif response_dict.get('code') == 'not_authenticated':
            raise AuthenticationError(
                API_ERROR_MESSAGE.format(
                    error=response_dict['message'],
                    status_code=response.status_code,
                    headers=HEADERS,
                    timestamp=timestamp
                )
            )
        else:
            raise ValueError(
                API_ERROR_MESSAGE.format(
                    error=response_dict.get('error'),
                    status_code=response.status_code,
                    headers=HEADERS,
                    timestamp=timestamp
                )
            )

    return response_dict


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
    if not isinstance(response, dict):
        raise TypeError(f'Ожидался словарь, получен {type(response)}')

    if 'homeworks' not in response:
        raise KeyError('Отсутствуют ожидаемые ключи в ответе API: "homeworks"')

    if not isinstance(response['homeworks'], list):
        raise TypeError(
            f'Ожидался список, получен: {type(response["homeworks"])}'
        )


def parse_status(homework):
    """Извлекает из информации о конкретной домашней работе статус."""
    if 'status' not in homework:
        raise KeyError('Нет ожидаемого ключа: status')
    if 'homework_name' not in homework:
        raise KeyError('Нет ожидаемого ключа: homework_name')
    if homework['status'] not in HOMEWORK_VERDICTS:
        raise ValueError(
            f'Получен неожиданный статус: {homework["status"]}'
        )
    return STATUS_CHANGE_MESSAGE.format(
        homework_name=homework['homework_name'],
        status=HOMEWORK_VERDICTS[homework['status']]
    )


def main():
    """Основная логика работы бота."""
    last_message = None
    check_tokens()
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    while True:
        try:
            response = get_api_answer(timestamp)
            check_response(response)
            if response.get('homeworks'):
                message = parse_status(response['homeworks'][0])
                if last_message != message:
                    send_message(bot, message)
                    last_message = message
                    timestamp = response.get('current_date', timestamp)
            else:
                logger.debug('Отсутствие в ответе новых статусов.')

        except (
            ApiError,
            AuthenticationError,
            HTTPError,
            KeyError,
            RequestException,
            TypeError,
            ValueError,
        ) as e:
            logger.error(e, exc_info=True)
            if last_message != str(e):
                send_message(bot, str(e))
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.error(message)
            if last_message != message:
                send_message(bot, message)
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] '
               '%(funcName)s::%(lineno)d %(message)s',
        handlers=[stream_handler, file_handler]
    )
    main()
