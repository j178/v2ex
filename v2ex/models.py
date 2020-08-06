# -*- coding: utf-8 -*-
# Created by johnj at 2020/8/6
import asyncio
import enum
from dataclasses import dataclass, InitVar
from datetime import datetime
from typing import AsyncGenerator

import httpx

from v2ex.api import client_from_cookies, client_from_signin


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

    async def topics(self) -> AsyncGenerator['Topic', None]:
        pass


@dataclass
class Member(Base):
    id: str = None
    number: str = None
    join_time: datetime = None
    avatar_link: str = None

    async def topics(self) -> AsyncGenerator['Topic', None]:
        pass

    async def replies(self) -> AsyncGenerator['Reply', None]:
        pass

    async def notifications(self) -> AsyncGenerator['Notification', None]:
        pass


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

    async def replies(self) -> AsyncGenerator['Reply', None]:
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

    async def create_topic(self, title: str, content: str, node: 'Node') -> 'Topic':
        pass

    @classmethod
    async def signin(cls, username, password) -> 'Me':
        client = client_from_signin(username, password)
        me = cls(client=client)

        return me

    @classmethod
    async def from_cookies(cls, cookies: dict) -> 'Me':
        client = client_from_cookies(cookies)
        me = cls(client=client)

        return me


async def test_me():
    me = await Me.from_cookies()
    async for topic in me.topics():
        print(topic)


if __name__ == '__main__':
    asyncio.run(test_me())
