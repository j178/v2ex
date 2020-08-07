import os
import asyncio
import logging

from v2ex import Me
from v2ex import __version__

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s [%(module)s:%(lineno)d] %(message)s')


def test_version():
    assert __version__ == '0.1.0'


async def test_me():
    c = os.environ['COOKIES']
    me = await Me.from_cookies(c)
    print(me.id)
    print(await me.redeem_daliy_mission())


async def test_signin():
    otp = None
    if os.environ.get('OTP_URI'):
        import pyotp

        otp = pyotp.parse_uri(os.environ.get('OTP_URI'))

    from v2ex.utils import recognize_captcha_by_human

    me = await Me.signin(os.environ.get('USERNAME'),
                         os.environ.get('PASSWORD'),
                         recognize_captcha_by_human,
                         otp=otp)
    print(me.id)


if __name__ == '__main__':
    asyncio.run(test_me())
