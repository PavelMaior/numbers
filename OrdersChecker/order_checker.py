import logging
import os
import time
from datetime import datetime, timedelta

import httplib2
import telebot
from googleapiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials

import requests
import psycopg2
from psycopg2 import Error


class OrderChecker:
    scopes = ['https://www.googleapis.com/auth/spreadsheets']  # поля для запросов google
    ranges = ["Лист1!B2:D1000"]  # поля таблицы для сбора данных (первую ячейку сразу отбросил, порядковый номер из
    # этой таблицы в базе ни к чему)

    db_user = "nekr"
    db_password = "qwerty"
    db_host = "db"
    db_port = 5432
    db_name = "catalog"

    bot_id = '5320746202:AAFjObqDiUc7u7fMTykOvj10zcLadJU8Dkc'  # id Telegram-бота
    telegram_channel = '@orders_check_channel'  # Telegram-чат для отправки уведомлений

    recent_sending_id = tuple()  # кортеж недавних успешных запросов
    update_period = timedelta(hours=1)  # периоичность обновления курса доллара и сброса кортежа недавних запросов

    def __init__(self, file_path=None, sheet_id=None):
        if file_path:  # установка имени json файла для авторизациив googleapi
            self.creds_json = os.path.dirname(__file__) + f"/{file_path}"
        else:
            self.creds_json = os.path.dirname(__file__) + "/numbers-353308-cd55c53c6f90.json"

        if sheet_id:  # установка id таблицы для запросов
            self.sheet_id = sheet_id
        else:
            self.sheet_id = '1qdb9iLhHrcBic83SsjK18_wbKTn-B4OFuXo8GRa_lWY'
        self.time_to_update = datetime.now() + self.update_period  # установка следующейго времени сброа и обновления
        self.rub_to_usd = self.get_rub_to_usd()  # установка курса валют
        self.bot = telebot.TeleBot(self.bot_id)  # генерация бота

    @staticmethod
    def get_rub_to_usd():
        """Получить курс доллара по ЦБ"""
        data = requests.get('https://www.cbr-xml-daily.ru/daily_json.js').json()
        rub_for_usd = data['Valute']['USD']['Value']
        return rub_for_usd

    def get_build(self):
        """получение авторизованного соединения с googleapi"""
        creds_service = ServiceAccountCredentials.from_json_keyfile_name(self.creds_json, self.scopes).authorize(
            httplib2.Http())
        return build('sheets', 'v4', http=creds_service)

    def get_response(self):
        """получение данных из заданной таблицы"""
        return self.get_build().spreadsheets().values().batchGet(
            spreadsheetId=self.sheet_id,
            ranges=self.ranges
        ).execute()

    def get_prepared_data_db(self):
        """преобразование данных из запроса для корректной отправки в БД"""
        prepared_data = tuple()
        response = self.get_response()
        orders_list = response['valueRanges'][0]['values']  # получаем список заказов из всего ответа
        for order in orders_list:
            if len(order) != 3:  # проверяем все ли необходимыя ячейки заполнены
                logging.warning('Обнаруженны не полные данные')
                continue
            try:
                order_tuple = (
                    int(order[0]),
                    int(order[1]),
                    int(order[1]) * self.rub_to_usd,
                    datetime.strptime(order[2], "%d.%m.%Y").strftime('%Y-%m-%d')
                )
                prepared_data += (order_tuple,)
            except ValueError:  # валидация данных в ячейках
                logging.warning('Обнаруженны некорректные данные')
                continue
        return prepared_data

    def get_db_connection(self):
        """Установка соединенис с БД"""
        while True:
            try:
                connection = psycopg2.connect(
                    user=self.db_user,
                    password=self.db_password,
                    host=self.db_host,
                    port=self.db_port,
                    database=self.db_name)
                return connection
            except (Exception, Error) as error:
                logging.warning(
                    "Ошибка при подключении к PostgreSQL",
                    error
                )
                time.sleep(10)

    def send_order_db(self, order):
        """
        Отправка запроса на добавление элемента в БД
        возвращает:
            1 в случае успеха
            '23505' в случае повторного добавления
            ошибку в исключительном случае
        """
        try:
            self.db_connection = self.get_db_connection()
            self.cursor = self.db_connection.cursor()

            insert_query = """INSERT INTO ordersapp_order (id, usd_price, rub_price, delivery_date) VALUES (%s,%s,%s,%s)"""

            self.cursor.execute(insert_query, order)
            self.db_connection.commit()
            return self.cursor.rowcount
        except (Exception, Error) as error:
            if hasattr(error, 'pgcode'):  # проверяем
                return error.pgcode
            else:
                logging.warning('НЕКОРРЕКТНОЕ добавление в базу')
                return error
        finally:
            if self.db_connection:
                self.cursor.close()
                self.db_connection.close()

    def send_prepared_data(self, prepared_data):
        """
        Пересылает данные на отправку в БД, в зависимости от результата отправки
        формирует кортеж успешно отправленных запросов
        """
        for order in prepared_data:
            if order[0] not in self.recent_sending_id:
                result_of_sending = self.send_order_db(order)
                if result_of_sending == 1:
                    self.check_delivery_time(order)
                    self.recent_sending_id += (order[0],)
                    logging.info('УСПЕШНОЕ добавление в базу')
                elif result_of_sending == '23505':
                    logging.info('ПОВТОРНОЕ добавление в базу')
                    self.recent_sending_id += (order[0],)

    def check_delivery_time(self, order):
        """
        Проверяет корректность срока поставки.
        Отправляет сообщение в Telegram-канал в случае истечения срока
        """
        delivery_date = datetime.strptime(order[3], '%Y-%m-%d')
        if datetime.now() >= delivery_date:
            self.bot.send_message(
                self.telegram_channel,
                f'Срок поставки заказа № {order[0]} истек!')

    def run(self):
        """
        Собственно Запуск
        """
        while True:
            prepared_data = self.get_prepared_data_db()  # сбор данных из таблицы
            self.send_prepared_data(prepared_data)  # отправка данных в БД
            self.release_recent_checker()  # проверка сроков обновления кортежа и курса доллара
            time.sleep(5)

    def release_recent_checker(self):
        """
        Очищает кортеж успешно отьправленных запросов с приодичностью self.update_period
        Обновляает курс доллара
        """
        if datetime.now() > self.time_to_update:
            self.recent_sending_id = tuple()
            self.time_to_update = datetime.now() + self.update_period
            self.rub_to_usd = self.get_rub_to_usd()

    # изначально хотел с базой через api работать,
    # api_url = 'http://web/api/orders/'
    # api_headers = {
    #     'Content-type': 'application/json',
    #     'Content-Encoding': 'utf-8'}
    # def get_prepared_data_api(self):
    #     prepared_data = tuple()
    #     for order in self.response['valueRanges'][0]['values']:
    #         if len(order) != 3:
    #             continue
    #         order_dict = {
    #             "id": int(order[0]),
    #             "usd_price": int(order[1]),
    #             "rub_price": int(order[1]) * self.rub_to_usd,
    #             "delivery_date": datetime.strptime(order[2], "%d.%m.%Y").strftime('%Y-%m-%d')
    #         }
    #         prepared_data += (order_dict,)
    #     return prepared_data
    #
    # def send_order_api(self, order):
    #     try:
    #         answer = requests.post(self.sending_url, data=json.dumps(order), headers=self.sending_headers)
    #     except Exception as error:
    #         print(error)
    #     return answer.status_code


if __name__ == '__main__':
    while True:
        try:
            logging.info(
                f'Прозваниваю базу через бэк  {os.path.abspath(__file__)}'
            )
            answer = requests.get('http://nginx:8002/api/orders/')
            if answer.status_code == 200:
                logging.info(
                    'Дозвонился, запускаю проверятель'
                )
                ocheck = OrderChecker()
                ocheck.run()
            else:
                time.sleep(2)
        except Exception as error:
            logging.warning(
                "Ошибка на старте",
                error
            )

