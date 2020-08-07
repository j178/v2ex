# -*- coding: utf-8 -*-
# Created by johnj at 2020/8/4
import io
import logging
import os
import typing
from http.cookies import SimpleCookie
from typing import Optional

import httpx

if typing.TYPE_CHECKING:
    from v2ex.api import Notification, Me


def parse_cookies(cookie_str: str) -> dict:
    cookie = SimpleCookie(cookie_str)
    cookies = {value.key: value.coded_value for value in cookie.values()}
    return cookies


class RestDB:
    def __init__(self):
        self.url = f'https://v2exrecord-f78c.restdb.io/rest/v2ex/{os.environ["RESTDB_OBJECT_ID"]}'
        self.headers = {'x-apikey': os.environ['RESTDB_KEY']}
        self._client = httpx.AsyncClient()

    async def get_last_check_id(self) -> Optional[int]:
        try:
            resp = await self._client.get(self.url, headers=self.headers)
            resp.raise_for_status()
        except Exception:
            logging.exception('Fetch last check id failed')
            return None

        data = resp.json()
        return data.get('last_id')

    async def save_last_check_id(self, last_id: int) -> None:
        data = {'last_id': last_id}
        try:
            resp = await self._client.put(self.url, json=data, headers=self.headers)
            resp.raise_for_status()
        except Exception:
            logging.exception('Update last check id failed')
            raise


async def send_notfication(notify: 'Notification') -> None:
    sc_url = f'https://sc.ftqq.com/{os.environ["SCKEY"]}.send'
    data = {'text': 'v2ex new notifcation', 'desp': str(notify)}
    client = httpx.AsyncClient()
    try:
        resp = await client.post(sc_url, data=data)
        resp.raise_for_status()
    except httpx.HTTPError:
        logging.exception('Send sc notfication failed')
        raise
    logging.info(f'Sent notification {notify.id}')


async def recognize_captcha_by_human(client: httpx.AsyncClient, image_url: str) -> str:
    from PIL import Image

    resp = await client.get(image_url)
    im = Image.open(io.BytesIO(resp.content))
    im.show()

    text = input('Captcha?').strip()
    return text


async def notify_notifications(me: 'Me'):
    rest_db = RestDB()
    last_check_id = await rest_db.get_last_check_id()
    logging.info(f'Got last_id {last_check_id}')
    if last_check_id is None:
        latest_notify = await me.notifications(limit=1).__anext__()
        if latest_notify:
            last_check_id = latest_notify.id
            await rest_db.save_last_check_id(last_check_id)
            return

    new_last_check_id = None
    new_notifications = [notify async for notify in me.notifications_after(last_check_id)]
    new_notifications.reverse()
    try:
        for notify in new_notifications:
            await send_notfication(notify)
            new_last_check_id = notify.id
    finally:
        if new_last_check_id:
            await rest_db.save_last_check_id(new_last_check_id)
            logging.info(f'Update last check id to {new_last_check_id}')
