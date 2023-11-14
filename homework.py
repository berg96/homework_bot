import logging
import os
import sys

import requests
import time
import telegram

from dotenv import load_dotenv

from exceptions import (
    AuthenticationError,
    EndpointUnavailableError,
    EndpointError,
    StatusError,
    NoNewStatus
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

STATUS = None
LAST_MESSAGE = None


def check_tokens():
    """Проверяет доступность переменных окружения"""

    expected_tokens = ['PRACTICUM_TOKEN', 'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID']
    missing_tokens = [
        token for token in expected_tokens if not os.getenv(token)
    ]

    if missing_tokens:
        logger.critical(
            f'''Отсутствут обязательные переменные окружения: {missing_tokens}.
Программа принудительно остановлена.'''
        )
        sys.exit(0)


def send_message(bot, message):
    """Отправляет сообщение в Telegram чат"""

    global LAST_MESSAGE

    try:
        if message != LAST_MESSAGE:
            bot.send_message(TELEGRAM_CHAT_ID, message)
            logger.debug(f'Бот отправил сообщение "{message}"')
            LAST_MESSAGE = message

    except Exception as e:
        logger.error(f'Сбой при отправке сообщения в Telegram: {e}')


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса"""

    try:
        response = requests.get(
            ENDPOINT, headers=HEADERS, params={'from_date': timestamp}
        )
        if response.status_code == 404:
            raise EndpointUnavailableError(
                f'Сбой в работе программы: Эндпоинт {ENDPOINT} недоступен. '
                'Код ответа API: 404'
            )
        return response.json()

    except EndpointUnavailableError:
        raise
    except Exception as e:
        raise EndpointError(f'Сбой при запросе к эндпоинту {ENDPOINT}: {e}')


def check_response(response):
    """Проверяет ответ API на соответствие документации"""

    expected_keys = {'homeworks', 'current_date'}

    if expected_keys != set(response.keys()):
        if response['code'] == 'UnknownError':
            raise TypeError(response['error']['error'])
        elif response['code'] == 'not_authenticated':
            raise AuthenticationError(response['message'])
        else:
            raise KeyError('Отсутствуют ожидаемые ключи в ответе API: '
                           f'{expected_keys - set(response.keys())}')

    if not response['homeworks']:
        raise NoNewStatus('Нет нового статуса')


def parse_status(homework):
    """Извлекает из информации о конкретной
        домашней работе статус этой работы"""

    global STATUS

    if 'status' in homework:
        if homework['status'] != STATUS:
            if homework['status'] not in HOMEWORK_VERDICTS:
                raise StatusError(
                    f'Получен неожиданный статус: {homework["status"]}'
                )
            STATUS = homework['status']
            return (
                f'Изменился статус проверки работы '
                f'"{homework["lesson_name"]}". {HOMEWORK_VERDICTS[STATUS]}'
            )


def main():
    """Основная логика работы бота."""

    check_tokens()
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())

    while True:
        try:
            response = get_api_answer(timestamp)
            check_response(response)
            timestamp = response['current_date']
            send_message(bot, parse_status(response['homeworks'][0]))

        except EndpointUnavailableError as eue:
            logger.error(eue)
            send_message(bot, str(eue))
        except EndpointError as ee:
            logger.error(ee)
            send_message(bot, str(ee))
        except KeyError as ke:
            logger.error(ke)
            send_message(bot, str(ke))
        except TypeError as te:
            logger.error(te)
            send_message(bot, str(te))
        except AuthenticationError as ae:
            logger.error(ae)
            send_message(bot, str(ae))
        except StatusError as se:
            logger.error(se)
            send_message(bot, str(se))
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
