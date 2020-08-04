# -*- coding: utf-8 -*-
# Created by johnj at 2020/8/4
import io
import logging
import os
import httpx
from typing import Optional

from v2ex.api import Notification, get_notifications, get_notifications_after

restdb_url = f'https://v2exrecord-f78c.restdb.io/rest/v2ex/{os.environ["RESTDB_OBJECT_ID"]}'
restdb_headers = {'x-apikey': os.environ['RESTDB_KEY']}
sc_url = f'https://sc.ftqq.com/{os.environ["SCKEY"]}.send'


async def get_last_check_id(client: httpx.AsyncClient) -> Optional[int]:
    try:
        resp = await client.get(restdb_url, headers=restdb_headers)
        resp.raise_for_status()
    except Exception:
        logging.exception('Fetch last check id failed')
        return None

    data = resp.json()
    return data.get('last_id')


async def save_last_check_id(client: httpx.AsyncClient, last_id: int) -> None:
    data = {'last_id': last_id}
    try:
        resp = await client.put(restdb_url, json=data, headers=restdb_headers)
        resp.raise_for_status()
    except Exception:
        logging.exception('Update last check id failed')
        raise


async def send_notfication(client: httpx.AsyncClient, notify: Notification) -> None:
    data = {'text': 'v2ex new notifcation', 'desp': str(notify)}
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


async def notify_notifications(client: httpx.AsyncClient):
    last_check_id = await get_last_check_id(client)
    logging.info(f'Got last_id {last_check_id}')
    if last_check_id is None:
        latest_notify = await get_notifications(client, limit=1).__anext__()
        if latest_notify:
            last_check_id = latest_notify.id
            await save_last_check_id(client, last_check_id)
            return

    new_last_check_id = None
    new_notifications = [notify async for notify in get_notifications_after(client, last_check_id)]
    new_notifications.reverse()
    try:
        for notify in new_notifications:
            await send_notfication(client, notify)
            new_last_check_id = notify.id
    finally:
        if new_last_check_id:
            await save_last_check_id(new_last_check_id)
            logging.info(f'Update last check id to {new_last_check_id}')
