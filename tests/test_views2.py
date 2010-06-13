from formencode.validators import Int
from nose.tools import eq_
from werkzeug import MultiDict, run_wsgi_app, Headers
from werkzeug.exceptions import BadRequest

from pysmvt import rg, user
from pysmvt.views import View
from pysmvt.testing import inrequest
from pysmvt.wrappers import Response

# create the wsgi application that will be used for testing
import config
from newlayout.application import make_wsgi

def setup_module():
   make_wsgi()

@inrequest()
def test_basic_view():
    # instantiate the view for test coverage purposes
    class TestView(View):
        def default(self):
            return 'hw'

    v = TestView({})
    r = v.process()

    assert isinstance(r, Response)
    eq_(r.data, 'hw')

@inrequest()
def test_retval_edit():

    class TestView(View):
        def default(self):
            self.retval = 'foobar'
            return 'hw'

    v = TestView({})
    r = v.process()

    assert isinstance(r, Response)
    eq_(r.data, 'foobar')

@inrequest()
def test_direct_response_edit():

    class TestView(View):
        def default(self):
            rg.respctx.response.data = 'hw2'

    v = TestView({})
    r = v.process()

    assert isinstance(r, Response)
    eq_(r.data, 'hw2')

@inrequest()
def test_wsgi_app_return():

    class TestView(View):
        def default(self):
            def hello_world(environ, start_response):
                start_response('200 OK', [('Content-Type', 'text/html')])
                return ['wsgi hw']
            return hello_world

    v = TestView({})
    r = v.process()

    appiter, status, headers = run_wsgi_app(r, rg.environ)
    eq_(''.join(appiter), 'wsgi hw')


@inrequest()
def test_incorrect_return():

    class TestView(View):
        def default(self):
            return 2

    v = TestView({})
    try:
        r = v.process()
        assert False
    except TypeError, e:
        eq_('View "TestView" returned a value with an unexpected type: <type \'int\'>', str(e))

@inrequest('/foo?bar=baz')
def test_get_args():
    # URL args only
    class TestView(View):
        def default(self, bar):
            return bar
    r = TestView({'bar':'2'}).process()
    assert r.data == '2'

    # no args causes 400
    class TestView(View):
        def default(self, bar):
            pass # pragma: no coverage
    try:
        r = TestView({}).process()
        assert False
    except BadRequest, e:
        pass

    # register get args
    class TestView(View):
        def init(self):
            self.expect_getargs('bar')

        def default(self, bar):
            return bar
    r = TestView({}).process()
    assert r.data == 'baz'

@inrequest('/foo?bar=baz&a1=a')
def test_arg_processor():
    # register get args with a processor
    class TestView(View):
        def init(self):
            self.add_processor('bar')
            self.add_processor('a1')
            # shouldn't cause a problem
            self.add_processor('nothere', int)

        def default(self, bar, a1):
            eq_(bar, 'baz')
            return str(a1)
    r = TestView({}).process()
    eq_(r.data, u'a')
    # url values take precedence
    r = TestView({'a1':2}).process()
    eq_(r.data, '2')

@inrequest('/foo?a=1&b=b&d=3')
def test_arg_validation():
    class TestView(View):
        def init(self):
            self.add_processor('a', int)
            self.add_processor('b', int)
            self.add_processor('c', int)
            self.add_processor('d', Int)
            try:
                # try a bad processor type
                self.add_processor('e', 5)
                assert False
            except TypeError, e:
                if 'processor must be a Formencode validator or a callable' != str(e):
                    raise # pragma: no cover
        def default(self, a, b, c, d):
            eq_(a, 1)
            eq_(c, 2)
            eq_(d, 3)
            assert b is None, b
    r = TestView({'c':u'2'}).process()


@inrequest('/foo?a=1&b=b')
def test_arg_validation_with_strict():
    # view level stric
    class TestView(View):
        def init(self):
            self.strict_args = True
            self.add_processor('b', int)
    try:
        r = TestView({}).process()
        assert False
    except BadRequest:
        pass

    # arg level strict
    class TestView(View):
        def init(self):
            self.add_processor('b', int, strict=True)
    try:
        r = TestView({}).process()
        assert False
    except BadRequest:
        pass

    # non-strict failure with strict arg that passes
    class TestView(View):
        def init(self):
            self.add_processor('a', int, strict=True)
            self.add_processor('b', int, custom_msg='mycustom')
        def default(self, a, b):
            msgs = user.get_messages()
            eq_(a, 1)
            assert b is None, b
            eq_(str(msgs[0]), 'error: b: mycustom')
    r = TestView({}).process()

    # require implies strict; usage without processor
    class TestView(View):
        def init(self):
            self.add_processor('c', required=True)
    try:
        r = TestView({}).process()
        assert False
    except BadRequest:
        pass

    # required usage with a processor
    class TestView(View):
        def init(self):
            self.add_processor('c', int, required=True)
    try:
        r = TestView({}).process()
        assert False
    except BadRequest:
        pass

@inrequest('/foo?a=1&a=2&b=1&b=2&c=1&c=2&d=1&d=2&d=abc&e=1&g=foo&h=1&h=foo&h=bar')
def test_processing_with_lists():
    class TestView(View):
        def init(self):
            self.add_processor('a')
            self.add_processor('b', int)
            self.add_processor('c', int, takes_list=False, show_msg=True)
            self.add_processor('d', int, takes_list=True, strict=True)
            self.add_processor('e', takes_list=True)
            self.add_processor('f', takes_list=True)
            self.add_processor('g', int, takes_list=True)
            self.add_processor('h', int, takes_list=True, list_item_invalidates=True, show_msg=True)
        def default(self, a, b, f, c, d, e, g, h):
            msgs = user.get_messages()
            eq_(a, '1')
            eq_(b, 1)
            # list when takes_list == False invalidates the whole argument
            assert c is None
            # test our error message
            eq_(str(msgs[0]), 'error: c: multiple values not allowed')
            # validator/convert and one invalid value results in only valid
            # values and does not trigger strict
            eq_(d, [1, 2])
            # single item converted to list
            eq_(e, ['1'])
            # no values sent
            eq_(f, [])
            # all bad values
            eq_(g, [])
            # single bad value invalidates all values
            eq_(h, [])
    r = TestView({}).process()

    # no list strict
    class TestView(View):
        def init(self):
            self.add_processor('c', int, takes_list=False, strict=True)
    try:
        r = TestView({}).process()
        assert False
    except BadRequest:
        pass

    # list item invalidates & strict
    class TestView(View):
        def init(self):
            self.add_processor('h', int, takes_list=True, list_item_invalidates=True, strict=True)
    try:
        r = TestView({}).process()
        assert False
    except BadRequest:
        pass

    # empty list should fail required
    class TestView(View):
        def init(self):
            self.add_processor('f', int, takes_list=True, required=True)
    try:
        r = TestView({}).process()
        assert False
    except BadRequest:
        pass

    # empty list after validation should fail required
    class TestView(View):
        def init(self):
            self.add_processor('g', int, takes_list=True, required=True)
    try:
        r = TestView({}).process()
        assert False
    except BadRequest:
        pass

def test_call_method_changes():
    v = View({})
    assert v._cm_stack[0][0] == 'init_response'
    v.add_call_method('foo')
    assert v._cm_stack[1][0] == 'foo'
    v.insert_call_method('bar', 'before', 'foo')
    assert v._cm_stack[1][0] == 'bar', v._cm_stack
    v.insert_call_method('baz', 'after', 'bar')
    assert v._cm_stack[2][0] == 'baz', v._cm_stack
    assert v._cm_stack[3][0] == 'foo', v._cm_stack

    try:
        v.insert_call_method('foo', 'after', 'nothere')
    except ValueError, e:
        if 'target "nothere" was not found in the callstack' != str(e):
            assert False, e
    try:
        v.insert_call_method('whatever', 'behind', 'foo')
    except ValueError, e:
        if 'position "behind" not valid' not in str(e):
            assert False, e

@inrequest('/foo?a=1&b=b&d=3')
def test_view_callstack():
    methods_called = []
    class TestView(View):
        def init(self):
            self.add_call_method('test1')
            self.add_call_method('test2')
        def test1(self):
            methods_called.append('test1')
        def default(self):
            methods_called.append('default')
    r = TestView({}).process()
    eq_(methods_called, ['test1', 'default'])

    methods_called = []
    class TestView(View):
        def get(self):
            methods_called.append('get')
    r = TestView({}).process()
    eq_(methods_called, ['get'])

    # call stack abort
    methods_called = []
    class TestView(View):
        def init(self):
            self.add_call_method('test1')
        def test1(self):
            methods_called.append('test1')
            self.retval = 'foo'
            self.send_response()
    r = TestView({}).process()
    eq_(methods_called, ['test1'])

    class TestView(View):
        pass
    try:
        r = TestView({}).process()
        assert False
    except Exception, e:
        if 'there were no "action" methods on the view class' not in str(e):
            assert False, e

    # make sure an attirbute error in the default method gets passed out
    class TestView(View):
        def default(self):
            baz = self.notthere
    try:
        r = TestView({}).process()
        assert False
    except Exception, e:
        if "'TestView' object has no attribute 'notthere'" != str(e):
            assert False, e

@inrequest('/foo', method='POST')
def test_view_callstack_with_post():
    methods_called = []
    class TestView(View):
        def post(self):
            methods_called.append('post')
    r = TestView({}).process()
    eq_(methods_called, ['post'])

ajax_headers = Headers()
ajax_headers.add('X-Requested-With', 'XMLHttpRequest')

@inrequest('/foo', headers=ajax_headers)
def test_view_callstack_with_ajax():
    methods_called = []
    class TestView(View):
        def xhr(self):
            methods_called.append('xhr')
    r = TestView({}).process()
    eq_(methods_called, ['xhr'])