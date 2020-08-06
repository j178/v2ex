# -*- coding: utf-8 -*-
# Created by johnj at 2020/8/6

class Error(Exception):
    def __init__(self, message):
        self.message = message


class NeedLogin(Error):
    pass


class Need2FA(Error):
    pass


class SigninFailed(Error):
    pass
