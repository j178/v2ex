# -*- coding: utf-8 -*-
# Created by johnj at 2020/7/28

import asyncio
import logging
import os
import re
import typing
from typing import Callable, Optional, Tuple

import httpx
from bs4 import BeautifulSoup as _BeautifulSoup, NavigableString

from v2ex.errors import Need2FA, NeedLogin, SigninFailed
from v2ex.models import NotifyType, Notification

if typing.TYPE_CHECKING:
    from pyotp import TOTP, HOTP

log = logging.getLogger(__name__)

default_headers = {
    'referer': 'https://www.v2ex.com/',
    'accept-language': 'en,zh;q=0.9',
    'accept-encoding': 'gzip, deflate, br',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.89 Safari/537.36'
}

BeautifulSoup = lambda text: _BeautifulSoup(text, features='lxml')


def logged_in(response):
    if response.url.path == '/2fa':
        return False
    if '确定要从 V2EX 登出？' in response.text:
        return True
    return False


def check_session(response):
    if '你要查看的页面需要先登录' in response.text:
        raise NeedLogin
    if '两步验证登录' in response.text:
        raise Need2FA


async def get_notifications(client: httpx.AsyncClient, start_page: int = 1, limit: int = None):
    count = 0
    page = start_page
    while True:
        if limit is not None and count >= limit:
            break

        try:
            log.info(f'Fetching page {page}')
            resp = await client.get('/notifications', params={'p': page})
        except Exception:
            log.exception('Request failed')
            return

        soup = BeautifulSoup(resp.text)
        notifications = soup.find(id='notifications')
        for notification in notifications.find_all('div', recursive=False):
            notify_id = int(notification.get('id')[2:])
            td = notification.find('td', {'valign': 'middle'})
            spans = td.find_all('span')
            first_span = spans[0]
            author = first_span.contents[0].strong.string.strip()
            thread = first_span.contents[2].string.strip()
            content_link = first_span.contents[2].get('href')
            span_content_1 = first_span.contents[1].strip()
            span_content_3 = ''
            if len(first_span.contents) > 3:
                span_content_3 = first_span.contents[3].strip()
            if span_content_1 == '在回复' and span_content_3 == '时提到了你':
                type = NotifyType.MENTION
            elif span_content_1 == '在' and span_content_3 == '里回复了你':
                type = NotifyType.REPLY
            elif '感谢了你在主题' in span_content_1:
                type = NotifyType.THANK
            elif '收藏了你发布的主题' in span_content_1:
                type = NotifyType.FAVORITE
            else:
                type = NotifyType.OTHER

            time = spans[1].string.strip()
            div = td.find('div', class_='payload')
            content = ''
            if div:
                # If a tag contains more than one thing, then it’s not clear what .string should refer to,
                # so .string is defined to be None
                for node in div.contents:
                    if isinstance(node, NavigableString):
                        content += node.strip()
                    elif node.name == 'a':
                        content += node.get_text(strip=True) + ' '

            yield Notification(notify_id, time, thread,
                               content, author, type, content_link)
            count += 1

        page += 1


async def get_notifications_after(client: httpx.AsyncClient, notify_id: int):
    async for notify in get_notifications(client):
        if notify.id > notify_id:
            yield notify
        else:
            break


async def redeem_daily_mission(client: httpx.AsyncClient) -> Optional[Tuple[int, Tuple[int, ...]]]:
    """每日登录奖励
    返回 (连续登录天数，(金币，银币，铜币))
    """
    log.info('Requesting daily mission page')
    resp = await client.get('/mission/daily')
    check_session(resp)

    if '每日登录奖励已领取' not in resp.text:
        # 不带 V2EX_XXX 相关的 cookie, 会返回浏览器有问题
        once = _get_once(resp.text)
        log.info('Redeeming daily mission')
        resp = await client.get('/mission/daily/redeem',
                                params={'once': once})
        check_session(resp)

        if '已成功领取每日登录奖励' not in resp.text:
            log.error(f'Redeem failed: {resp.text}')
            return None

    match = re.search(r'已连续登录 (\d+) 天', resp.text, re.I)
    days = int(match.group(1))

    soup = BeautifulSoup(resp.text)
    archor = soup.find(id='money').a
    balance = archor.get_text()
    balance = list(int(m) for m in balance.split())
    balance = [0] * (3 - len(balance)) + balance

    log.info(f'Consective mission days: {days}, balance: {balance}')
    return days, tuple(balance)


def _get_once(text: str):
    match = re.search(r"/(?:_captcha|signout)\?once=(\d+)", text, re.I)
    if match:
        return match.group(1)


def client_from_cookies(A2, A2O=None) -> httpx.AsyncClient:
    cookies = {
        'A2': A2,
        # 开启 2FA 之后需要 A2O
        'A2O': A2O,
        'V2EX_LANG': 'zhcn',
        'V2EX_REFERER': '"2|1:0|10:1596250535|13:V2EX_REFERRER|8:Z2FuY2w=|b40d742208ad5645a1387a0a9b8249bf3b40cdc1d61b17d594d91bab5e1cfaa2"',
        'V2EX_TAB': '"2|1:0|10:1596384658|8:V2EX_TAB|8:dGVjaA==|807dcc66eeac29c25764bae31b0d206531f1af3d69365238f6bf457492f7d452"',
    }
    client = httpx.AsyncClient(
        base_url='https://www.v2ex.com',
        trust_env=True,
        timeout=None,
        http2=True,
        cookies=cookies,
        headers=default_headers
    )

    return client


async def client_from_signin(
        username: str,
        password: str,
        get_captcha: Callable,
        otp: typing.Union['HOTP', 'TOTP'] = None
) -> httpx.AsyncClient:
    # 添加无意义的初始 cookie，避免触发 cloudflare DDOS 防护
    initial_cookies = {
        '__cfduid': 'd0b5790fe665c3514c9ebbefcd6db371d1596503219',
        'PB3_SESSION': '"2|1:0|10:1596503219|11:PB3_SESSION|36:djJleDo0Ny4yNDAuNTkuNzU6MjU1ODg0ODE=|936d4c8e1d706718fdc75b7cfae788ef8ff69e47c6a156bd06396d3fa3e5fe9c"',
        'V2EX_LANG': 'zhcn'
    }
    client = httpx.AsyncClient(
        base_url='https://www.v2ex.com',
        trust_env=True,
        timeout=None,
        http2=True,
        cookies=initial_cookies,
        headers=default_headers
    )

    resp = await client.get('/')
    resp.raise_for_status()

    await signin(client, username, password, get_captcha, otp)
    return client


async def signin(
        client: httpx.AsyncClient,
        username: str,
        password: str,
        get_captcha: Callable,
        otp: typing.Union['HOTP', 'TOTP'] = None):
    # referer 不匹配会被重定向到首页
    client.headers['referer'] = 'https://www.v2ex.com/signin'
    resp = await client.get('/signin')
    resp.raise_for_status()
    if '由于当前 IP 在短时间内的登录尝试次数太多，目前暂时不能继续尝试' in resp.text:
        raise SigninFailed('Too many logins')

    once = _get_once(resp.text)
    soup = BeautifulSoup(resp.text)
    username_field = soup.find('input', {'placeholder': '用户名或电子邮箱地址'}).get('name')
    password_field = soup.find('input', {'type': 'password'}).get('name')
    captcha_field = soup.find('input', {'placeholder': '请输入上图中的验证码'}).get('name')
    captcha = await get_captcha(client, f'/_captcha?once={once}')
    log.info(f'Recognized captcha as {captcha}')

    data = {
        'next': '/',
        'once': once,
        username_field: username,
        password_field: password,
        captcha_field: captcha
    }
    resp = await client.post('/signin', data=data)
    if resp.url.path != '/2fa':
        if not logged_in(resp):
            soup = BeautifulSoup(resp.text)
            # <div class="problem">请解决以下问题然后再提交：<ul><li>输入的验证码不正确</li></ul></div>
            message = soup.find('div', {'class': 'problem'}).get_text(strip=True)
            raise SigninFailed(f'Sign in failed: {message}')
    else:
        if otp is None:
            raise SigninFailed('2FA otp authenticator is required')

        code = otp.now()
        once = _get_once(resp.text)
        data = {'code': code, 'once': once}
        resp = await client.post('/2fa', data=data)
        if not logged_in(resp):
            soup = BeautifulSoup(resp.text)
            message = soup.find('div', {'class': 'message', 'onclick': True}).get_text(strip=True)
            raise SigninFailed(f'2FA authenticate failed: {message}')

    soup = BeautifulSoup(resp.text)
    # <td width="48" valign="top"><a href="/member/j0hnj">
    member_re = re.compile(r'/member/([^"]+)', re.I)
    who = soup.find('a', {'href': member_re})
    who = member_re.search(who.get('href')).group(1)
    log.info(f'Succeed sign in as {who}')


def test_signin():
    otp = None
    if os.environ.get('OTP_URI'):
        import pyotp

        otp = pyotp.parse_uri(os.environ.get('OTP_URI'))

    from v2ex.utils import recognize_captcha_by_human

    asyncio.run(client_from_signin(os.environ.get('USERNAME'),
                                   os.environ.get('PASSWORD'),
                                   recognize_captcha_by_human,
                                   otp=otp))


def test_redeem():
    A2 = os.environ['A2']
    A2O = os.environ.get('A2O')
    client = client_from_cookies(A2, A2O)
    asyncio.run(redeem_daily_mission(client))


if __name__ == '__main__':
    test_redeem()
