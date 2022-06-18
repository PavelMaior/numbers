import json
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
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    ranges = ["Лист1!B2:D1000"]

    db_user = "nekr"
    db_password = "qwerty"
    db_host = "db"
    db_port = 5432
    db_name = "catalog"

    bot_id = '5320746202:AAFjObqDiUc7u7fMTykOvj10zcLadJU8Dkc'
    telegram_channel = '@orders_check_channel'
    update_period = timedelta(hours=1)
    recent_sending_id = tuple()

    def __init__(self, file_path=None, sheet_id=None):
        if file_path:
            self.creds_json = os.path.dirname(__file__) + f"/{file_path}"
        else:
            self.creds_json = os.path.dirname(__file__) + "/numbers-353308-cd55c53c6f90.json"

        if sheet_id:
            self.sheet_id = sheet_id
        else:
            self.sheet_id = '1qdb9iLhHrcBic83SsjK18_wbKTn-B4OFuXo8GRa_lWY'
        self.time_to_update = datetime.now() + self.update_period
        self.rub_to_usd = self.get_rub_to_usd()
        self.db_connection = self.get_db_connection()

    @staticmethod
    def get_rub_to_usd():
        data = requests.get('https://www.cbr-xml-daily.ru/daily_json.js').json()
        rub_for_usd = data['Valute']['USD']['Value']
        return rub_for_usd

    def get_build(self):
        creds_service = ServiceAccountCredentials.from_json_keyfile_name(self.creds_json, self.scopes).authorize(
            httplib2.Http())
        return build('sheets', 'v4', http=creds_service)

    def get_response(self):
        return self.get_build().spreadsheets().values().batchGet(
            spreadsheetId=self.sheet_id,
            ranges=self.ranges
        ).execute()

    def get_prepared_data_db(self):
        prepared_data = tuple()
        response = self.get_response()
        for order in response['valueRanges'][0]['values']:
            if len(order) != 3:
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
            except ValueError:
                logging.warning('Обнаруженны некорректные данные')
                continue
        return prepared_data

    def get_db_connection(self):
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
                time.sleep(2)

    def send_order_db(self, order):
        try:
            if not self.db_connection:
                self.db_connection = self.get_db_connection()
            self.cursor = self.db_connection.cursor()

            insert_query = """INSERT INTO ordersapp_order (id, usd_price, rub_price, delivery_date) VALUES (%s,%s,%s,%s)"""

            self.cursor.execute(insert_query, order)
            self.db_connection.commit()
            return self.cursor.rowcount
        except (Exception, Error) as error:
            if hasattr(error, 'pgcode'):
                return error.pgcode
            else:
                return error
        finally:
            if self.db_connection:
                self.cursor.close()
                self.db_connection.close()

    def send_prepared_data(self, prepared_data):
        if not self.db_connection:
            self.db_connection = self.get_db_connection()
        for order in prepared_data:
            if order[0] not in self.recent_sending_id:
                answer = self.send_order_db(order)
                if answer == 1:
                    self.check_delivery_time(order)
                    self.recent_sending_id += (order[0],)
                elif answer == '23505':
                    self.recent_sending_id += (order[0],)

    def check_delivery_time(self, order):
        delivery_date = datetime.strptime(order[3], '%Y-%m-%d')
        if datetime.now() >= delivery_date:
            bot = telebot.TeleBot(self.bot_id)
            bot.send_message(
                self.telegram_channel,
                f'Срок поставки заказа № {order[0]} истек!')

    def run(self):
        while True:
            prepared_data = self.get_prepared_data_db()
            self.send_prepared_data(prepared_data)
            self.release_recent_checker()
            time.sleep(5)

    def release_recent_checker(self):
        if datetime.now() > self.time_to_update:
            self.recent_sending_id = tuple()
            self.time_to_update = datetime.now() + self.update_period
            self.rub_to_usd = self.get_rub_to_usd()

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
            ocheck = OrderChecker()
            ocheck.run()
        except Exception as error:
            logging.warning(
                "Ошибка при работе скрипта",
                error
            )
            time.sleep(2)

