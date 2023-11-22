import logging
import os
import sys
import time

import requests
import telegram
from dotenv import load_dotenv
from requests.exceptions import RequestException

load_dotenv()

logger = logging.getLogger(__name__)
stream_handler = logging.StreamHandler(sys.stdout)
file_handler = logging.FileHandler(__file__ + '.log')

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
EXPECTED_TOKENS = ['PRACTICUM_TOKEN', 'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID']
RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}
HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}
ERROR_MISSING_ENV_VARIABLE = (
    'Отсутствует обязательная переменная окружения: {token}.'
)
STATUS_CHANGE_MESSAGE = (
    'Изменился статус проверки работы "{homework_name}". {status}'
)
BOT_MESSAGE = 'Бот отправил сообщение "{message}"'
SEND_MESSAGE_ERROR = (
    'Сбой при отправке сообщения в Telegram "{message}" : {error}.'
)
REQUEST_PARAMS = (
    'Параметры запроса: Эндпоинт: {url}, Headers: {headers}, params: {params}.'
)
API_ERROR_MESSAGE = '{error}. ' + REQUEST_PARAMS
STATUS_CODE_ERROR = (
    'Полученный статус кода: {status_code} != 200. '
    'Полученный ответ: {response}. '
) + REQUEST_PARAMS
KEY_WITH_ERROR = (
    'В ответе найден "{key_error}": {possible_text_error}. '
    'Полученный ответ: {response}. '
) + REQUEST_PARAMS
ERROR_MESSAGE = 'Сбой в работе программы: {error}'
INSTANCE_DICT_ERROR = (
    'В ответе ожидался словарь, получен другой тип данных: {type}'
)
INSTANCE_LIST_ERROR = (
    'В ответе ожидался "список" домашних заданий, '
    'получен другой тип данных: {type}'
)
UNEXPECTED_STATUS_ERROR = (
    'В ответе получен неожиданный статус домашнего задания: {status}'
)


def check_tokens():
    """Проверяет доступность переменных окружения."""
    missing_tokens = None
    for token in EXPECTED_TOKENS:
        if not globals()[token]:
            logger.critical(
                ERROR_MISSING_ENV_VARIABLE.format(token=token)
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
        return True
    except Exception as e:
        logger.exception(SEND_MESSAGE_ERROR.format(message=message, error=e))
        return False


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса."""
    request_params = dict(
        url=ENDPOINT, headers=HEADERS, params={'from_date': timestamp}
    )
    try:
        response = requests.get(**request_params)
    except RequestException as error:
        raise ConnectionError(
            API_ERROR_MESSAGE.format(error=error, **request_params)
        )
    response_data = response.json()
    for key in response_data.keys():
        if key != 'homeworks' and key != 'current_date':
            raise ValueError(
                KEY_WITH_ERROR.format(
                    key_error=key,
                    possible_text_error=response_data.get(key),
                    response=response_data,
                    **request_params
                )
            )
    if response.status_code != 200:
        raise RequestException(
            STATUS_CODE_ERROR.format(
                status_code=response.status_code,
                response=response_data,
                **request_params
            )
        )
    return response_data


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
    if not isinstance(response, dict):
        raise TypeError(INSTANCE_DICT_ERROR.format(type=type(response)))
    if 'homeworks' not in response:
        raise KeyError('Отсутствует ожидаемый ключ в ответе API: "homeworks"')
    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise TypeError(INSTANCE_LIST_ERROR.format(type=type(homeworks)))


def parse_status(homework):
    """Извлекает из информации о конкретной домашней работе статус."""
    homework_status = homework['status']
    if 'status' not in homework:
        raise KeyError('Нет ожидаемого ключа: status')
    if 'homework_name' not in homework:
        raise KeyError('Нет ожидаемого ключа: homework_name')
    if homework_status not in HOMEWORK_VERDICTS:
        raise ValueError(
            UNEXPECTED_STATUS_ERROR.format(status=homework_status)
        )
    return STATUS_CHANGE_MESSAGE.format(
        homework_name=homework['homework_name'],
        status=HOMEWORK_VERDICTS[homework_status]
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
                    if send_message(bot, message):
                        last_message = message
                        timestamp = response.get('current_date', timestamp)
            else:
                logger.debug('Отсутствие в ответе новых статусов.')
        except Exception as error:
            message = ERROR_MESSAGE.format(error=error)
            logger.exception(message)
            if last_message != message:
                if send_message(bot, message):
                    last_message = message
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
