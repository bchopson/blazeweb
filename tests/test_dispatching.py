import sys

from webtest import TestApp

from pysmvt import session, user, forward
from pysmvt.views import asview

import config
from minimal2.application import make_wsgi

class TestAltStack(object):

    @classmethod
    def setup_class(cls):
        try:
            del sys.modules['minimal2.views']
        except KeyError:
            pass
        cls.wsgiapp = make_wsgi('Dispatching', use_session=False)
        cls.ta = TestApp(cls.wsgiapp)

    def test_workingview(self):
        r = self.ta.get('/workingview')
        r.mustcontain('hello foo!')

    def test_no_session(self):
        r = self.ta.get('/nosession')
        r.mustcontain('hello nosession!')

    def test_forward(self):
        r = self.ta.get('/page1')
        r.mustcontain('page2!')

class TestAltStackWithSession(object):

    @classmethod
    def setup_class(cls):
        try:
            del sys.modules['minimal2.views']
        except KeyError:
            pass
        cls.wsgiapp = make_wsgi('Dispatching')
        cls.ta = TestApp(cls.wsgiapp)

    def test_hassession(self):

        r = self.ta.get('/hassession')
        r.mustcontain('hello hassession!')

    def test_session_saves(self):
        r = self.ta.get('/session1')

        r = self.ta.get('/session2')

        # get a new ta so that the cookie is different
        nta = TestApp(self.wsgiapp)
        r = nta.get('/session3')
