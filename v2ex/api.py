# -*- coding: utf-8 -*-
# Created by johnj at 2020/8/6
import enum
import logging
import re
from dataclasses import InitVar, dataclass
from datetime import datetime
from typing import AsyncIterator, Awaitable, Callable, Dict, Optional, Tuple, Union

import httpx
from bs4 import BeautifulSoup as _BeautifulSoup, NavigableString
from pyotp import TOTP

from v2ex.errors import Need2FA, NeedLogin, SigninFailed
from v2ex.utils import parse_cookies

DEFAULT_HEADERS = {
    'referer': 'https://www.v2ex.com/',
    'accept-language': 'en,zh;q=0.9',
    'accept-encoding': 'gzip, deflate, br',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.89 Safari/537.36'
}

log = logging.getLogger(__name__)
BeautifulSoup = lambda text: _BeautifulSoup(text, features='lxml')


def check_session(response):
    if '你要查看的页面需要先登录' in response.text:
        raise NeedLogin
    if '两步验证登录' in response.text:
        raise Need2FA


def logged_in(response):
    if response.url.path == '/2fa':
        return False
    if '确定要从 V2EX 登出？' in response.text:
        return True
    return False


def _get_once(text: str):
    match = re.search(r"/(?:_captcha|signout)\?once=(\d+)", text, re.I)
    if match:
        return match.group(1)


@dataclass
class Base:
    client: InitVar[httpx.AsyncClient] = None

    def __post_init__(self, client):
        self._client = client


@dataclass
class Node(Base):
    name: str = None
    topics_num: int = None
    description: str = None

    async def topics(self) -> AsyncIterator['Topic']:
        pass


@dataclass
class Member(Base):
    id: str = None
    number: str = None
    join_time: datetime = None
    avatar_link: str = None

    async def topics(self) -> AsyncIterator['Topic']:
        yield 1

    async def replies(self) -> AsyncIterator['Reply']:
        yield 1


@dataclass
class Reply(Base):
    author: Member = None
    create_time: datetime = None
    topic: 'Topic' = None
    content: str = None


@dataclass
class Topic(Base):
    id: int = None
    author: Member = None
    create_time: datetime = None

    async def replies(self) -> AsyncIterator['Reply']:
        pass


class NotifyType(enum.Enum):
    THANK = 'thank'
    MENTION = 'mention'
    REPLY = 'reply'
    FAVORITE = 'favorite'
    OTHER = 'other'


@dataclass
class Notification(Base):
    id: int = None
    time: str = None
    thread: str = None
    content: str = None
    author: str = None
    type: NotifyType = None
    content_link: str = None

    def __str__(self):
        if self.type == NotifyType.MENTION:
            left = '在回复'
            right = '时提到了你'
        elif self.type == NotifyType.REPLY:
            left = '在'
            right = '里回复了你'
        elif self.type == NotifyType.FAVORITE:
            left = '收藏了你发布的主题'
            right = ''
        elif self.type == NotifyType.THANK:
            left = '感谢了你在主题'
            right = '里的回复'
        else:
            left = ''
            right = ''
        return f'{self.id} [{self.author}] {left} "{self.thread}" {right} ({self.time})' \
               f'{": " + self.content if right else ""}'


class Me(Member):

    @classmethod
    async def signin(cls,
                     username: str,
                     password: str,
                     get_captcha: Callable[[httpx.AsyncClient, str], Awaitable[str]],
                     otp: TOTP = None) -> 'Me':
        client = await cls._init_signin_client()
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

        me = cls(client=client)
        return me

    @classmethod
    async def _init_signin_client(cls) -> httpx.AsyncClient:
        # 添加无意义的初始 cookie，避免触发 cloudflare DDOS 防护
        initial_cookies = {
            '__cfduid': 'd0b5790fe665c3514c9ebbefcd6db371d1596503219',
            'PB3_SESSION': '"2|1:0|10:1596503219|11:PB3_SESSION|36:djJleDo0Ny4yNDAuNTkuNzU6MjU1ODg0ODE=|936d4c8e1d706718fdc75b7cfae788ef8ff69e47c6a156bd06396d3fa3e5fe9c"',
            'V2EX_LANG': 'zhcn'
        }
        client = httpx.AsyncClient(
            base_url='https://www.v2ex.com/',
            trust_env=True,
            timeout=None,
            http2=True,
            cookies=initial_cookies,
            headers=DEFAULT_HEADERS
        )

        resp = await client.get('/')
        resp.raise_for_status()

        return client

    @classmethod
    async def from_cookies(cls, cookies: Union[str, Dict[str, str]]) -> 'Me':
        if isinstance(cookies, str):
            cookies = parse_cookies(cookies)

        # 另外，开启 2FA 之后需要 A2O
        if 'A2' not in cookies:
            raise ValueError('A2 cookie is required')
        # 添加一些必须的初始 Cookie
        cookies.setdefault('V2EX_LANG', 'zhcn')
        cookies.setdefault('V2EX_REFERER',
                           '"2|1:0|10:1596250535|13:V2EX_REFERRER|8:Z2FuY2w=|b40d742208ad5645a1387a0a9b8249bf3b40cdc1d61b17d594d91bab5e1cfaa2"')
        cookies.setdefault('V2EX_TAB',
                           '"2|1:0|10:1596384658|8:V2EX_TAB|8:dGVjaA==|807dcc66eeac29c25764bae31b0d206531f1af3d69365238f6bf457492f7d452"')

        client = httpx.AsyncClient(
            base_url='https://www.v2ex.com/',
            trust_env=False,
            timeout=None,
            http2=True,
            cookies=cookies,
            headers=DEFAULT_HEADERS
        )
        me = cls(client=client)

        return me

    async def create_topic(self, title: str, content: str, node: 'Node') -> 'Topic':
        pass

    async def redeem_daliy_mission(self) -> Optional[Tuple[int, Tuple[int, ...]]]:
        """每日登录奖励
        返回 (连续登录天数，(金币，银币，铜币))
        """
        log.info('Requesting daily mission page')
        client = self._client
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

    async def notifications(self, start_page: int = 1, limit: int = None) -> AsyncIterator['Notification']:
        count = 0
        page = start_page
        while True:
            if limit is not None and count >= limit:
                break

            try:
                log.info(f'Fetching page {page}')
                resp = await self._client.get('/notifications', params={'p': page})
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

    async def notifications_after(self, notify_id: int):
        async for notify in self.notifications():
            if notify.id > notify_id:
                yield notify
            else:
                break

# 1. partial init, 即先只使用部分数据实例化对象，之后需要访问更多信息时再加载，完整填充数据
# 2. generator list 的获取 API a) 提供无限获取的 generator b) 提供 time, count 控制
# 3. 通用的翻页实现