import os
import sys
import asyncio
import logging

from v2ex import Me
from v2ex import __version__

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s [%(module)s:%(lineno)d] %(message)s')


def init_asyncio_reactor():
    if sys.platform == 'win32':
        if sys.version_info >= (3, 8):
            # If twisted releases a fix/workaround we can check that version too
            # https://twistedmatrix.com/trac/ticket/9766
            import asyncio

            selector_policy = asyncio.WindowsSelectorEventLoopPolicy()
            asyncio.set_event_loop_policy(selector_policy)


init_asyncio_reactor()


def test_version():
    assert __version__ == '0.1.0'


async def test_me():
    c = os.environ['COOKIES']
    me = await Me.from_cookies(c)
    print(me.id, flush=True)
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
