# -*- coding: utf-8 -*-
# Created by johnj at 2020/8/6
import enum
from dataclasses import dataclass


class NotifyType(enum.Enum):
    THANK = 'thank'
    MENTION = 'mention'
    REPLY = 'reply'
    FAVORITE = 'favorite'
    OTHER = 'other'


@dataclass()
class Notification:
    id: int
    time: str
    thread: str
    content: str
    author: str
    type: NotifyType
    content_link: str

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
