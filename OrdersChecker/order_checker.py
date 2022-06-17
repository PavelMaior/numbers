import json
import logging
import os
import time
from datetime import datetime

import httplib2
from googleapiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials

import requests
import psycopg2
from psycopg2 import Error


class OrderChecker:
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    ranges = ["Лист1!B2:D1000"]
    response = None
    rub_to_usd = None
    sending_url = 'http://127.0.0.1:8002/api/orders/'
    sending_headers = {'Content-type': 'application/json',
                       'Content-Encoding': 'utf-8'}

    db_user = "nekr"
    db_password = "qwerty"
    db_host = "db"
    db_port = 5432
    db_name = "catalog"

    def __init__(self, file_path=None, sheet_id=None):
        if file_path:
            self.creds_json = os.path.dirname(__file__) + f"/{file_path}"
        else:
            self.creds_json = os.path.dirname(__file__) + "/numbers-353308-cd55c53c6f90.json"

        if sheet_id:
            self.sheet_id = sheet_id
        else:
            self.sheet_id = '1qdb9iLhHrcBic83SsjK18_wbKTn-B4OFuXo8GRa_lWY'

    @staticmethod
    def get_rub_to_usd():
        data = requests.get('https://www.cbr-xml-daily.ru/daily_json.js').json()
        rub_for_usd = data['Valute']['USD']['Value']
        return rub_for_usd

    def build(self):
        creds_service = ServiceAccountCredentials.from_json_keyfile_name(self.creds_json, self.scopes).authorize(
            httplib2.Http())
        return build('sheets', 'v4', http=creds_service)

    def get_response(self):
        return self.build().spreadsheets().values().batchGet(
            spreadsheetId=self.sheet_id,
            ranges=self.ranges
        ).execute()

    def get_prepared_data_api(self):
        prepared_data = tuple()
        for order in self.response['valueRanges'][0]['values']:
            if len(order) != 3:
                continue
            order_dict = {
                "id": int(order[0]),
                "usd_price": int(order[1]),
                "rub_price": int(order[1]) * self.rub_to_usd,
                "delivery_date": datetime.strptime(order[2], "%d.%m.%Y").strftime('%Y-%m-%d')
            }
            prepared_data += (order_dict,)
        return prepared_data

    def get_prepared_data_db(self):
        prepared_data = tuple()
        for order in self.response['valueRanges'][0]['values']:
            if len(order) != 3:
                logging.warning('Обнаруженны не полные данные')
                continue
            order_tuple = (
                int(order[0]),
                int(order[1]),
                int(order[1]) * self.rub_to_usd,
                datetime.strptime(order[2], "%d.%m.%Y").strftime('%Y-%m-%d')
            )
            prepared_data += (order_tuple,)
        return prepared_data

    def send_order_api(self, order):
        try:
            answer = requests.post(self.sending_url, data=json.dumps(order), headers=self.sending_headers)
        except Exception as error:
            print(error)
        return answer.status_code

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
                    "Ошибка при работе с PostgreSQL",
                    error,
                    error.pgcode if hasattr(error, 'pgcode') else None
                )

    def send_order_db(self, order):
        try:
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

    def send_response(self):
        self.rub_to_usd = self.get_rub_to_usd()
        data = self.get_prepared_data_db()

        for order in data:
            answer = self.send_order_db(order)
            logging.warning(answer)

    def run(self):
        while True:
            if not self.response:
                self.response = self.get_response()
                self.send_response()
            else:
                new_response = self.get_response()
                if new_response != self.response:
                    self.response = new_response
                    self.send_response()
            time.sleep(10)


if __name__ == '__main__':
    ocheck = OrderChecker()
    ocheck.run()
