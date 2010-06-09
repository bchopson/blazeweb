import logging
from os import path

from werkzeug.exceptions import HTTPException, InternalServerError
from werkzeug import create_environ
from werkzeug.routing import Map, Submount

from pysutils.datastructures import BlankObject
from pysutils.strings import randchars
import pysmvt
from pysmvt import session, rg, user, config, _getview
from pysmvt.config import DefaultSettings
from pysmvt.exceptions import ForwardException, ProgrammingError
from pysmvt.hierarchy import findobj, HierarchyImportError, \
    listplugins, visitmods
from pysmvt.logs import _create_handlers_from_settings
from pysmvt.mail import mail_programmers
from pysmvt.view import function_view_handler
from pysmvt.users import User
from pysmvt.utils import randhash, Context, exception_with_context
from pysmvt.utils.filesystem import mkdirs
from pysmvt.wrappers import Request

log = logging.getLogger(__name__)

class Application(object):

    def __init__(self, module_or_settings, profile=None):
        self._id = randhash()
        self.settings = module_or_settings
        if profile is not None:
            module = module_or_settings
            self.settings = getattr(module, profile)()
        self.ag_setup()
        self.registry_setup()
        self.filesystem_setup()
        self.settings_setup()
        self.logging_setup()
        self.routing_setup()

    def registry_setup(self):
        pysmvt.settings._push_object(self.settings)
        pysmvt.ag._push_object(self.ag)

    def ag_setup(self):
        self.ag = BlankObject()
        self.ag.view_functions = {}
        self.ag.hierarchy_import_cache = {}
        self.ag.hierarchy_file_cache = {}

    def filesystem_setup(self):
        # create the writeable directories if they don't exist already
        mkdirs(self.settings.dirs.data)
        mkdirs(self.settings.dirs.logs)
        mkdirs(self.settings.dirs.tmp)

    def settings_setup(self):
        # now we need to assign plugin's settings to the main setting object
        for pname in listplugins():
            try:
                Settings = findobj('%s:config.settings' % pname, 'Settings')
                ms = Settings()
                # update the plugin's settings with any plugin level settings made
                # at the app level.  This allows us to override plugin settings
                # in our application's settings.py file.
                try:
                    ms.update(self.settings.plugins[pname])
                except KeyError, e:
                    if pname not in str(e):
                        raise
                self.settings.plugins[pname] = ms
            except HierarchyImportError, e:
                if '%s.config.settings' % pname not in str(e) and 'Settings' not in str(e):
                    raise

        # lock the settings, this ensures that an attribute error is thrown if an
        # attribute is accessed that doesn't exist.  Without the lock, a new attr
        # would be created, which is undesirable since any "new" attribute at this
        # point would probably be an accident
        self.settings.lock()

    def logging_setup(self):
        _create_handlers_from_settings(self.settings)

    def routing_setup(self):
        # setup the Map object with the appropriate settings
        self.ag.route_map = Map(**self.settings.routing.map.todict())

        # load view modules so routes from @asview() get setup correctly
        if self.settings.auto_load_views:
            visitmods('views')

        # application routes first since they should take precedence
        self.add_routing_rules(self.settings.routing.routes)

        # now the routes from plugin settings
        for pname in self.settings.plugins.keys():
            psettings = self.settings.plugins[pname]
            try:
                self.add_routing_rules(psettings.routes)
            except AttributeError, e:
                if "no attribute 'routes'" not in str(e):
                    raise

    def add_routing_rules(self, rules):
        if self.settings.routing.prefix:
            # prefix the routes with the prefix in the app settings class
            self.ag.route_map.add(Submount(self.settings.routing.prefix, rules ))
        else:
            for rule in rules or ():
                self.ag.route_map.add(rule)

    def start_request(self, environ=None):
        rg._push_object(Context())

        # create a fake environment if needed
        if not environ:
            environ = create_environ('/[pysmvt_test]')

        # this might throw an exception, but we are letting that go
        # b/c we need to make sure the url adapter gets created
        rg.urladapter = self.ag.route_map.bind_to_environ(environ)

    def console_dispatch(self, callable, environ=None):
        self.start_request(environ)
        try:
            callable()
        finally:
            self.end_request()

    def end_request(self):
        rg._pop_object()

class RequestManager(object):
    def __init__(self, app, environ):
        self.app = app
        self.environ = environ

    def registry_setup(self):
        environ = self.environ
        environ['paste.registry'].register(pysmvt.settings, self.app.settings)
        environ['paste.registry'].register(pysmvt.ag, self.app.ag)
        if environ.has_key('beaker.session'):
            environ['paste.registry'].register(session, environ['beaker.session'])
            environ['paste.registry'].register(user, self.user_setup())
        else:
            environ['paste.registry'].register(session, None)
            environ['paste.registry'].register(user, None)
        environ['paste.registry'].register(rg, BlankObject())

    def rg_setup(self):
        # WSGI request setup
        rg.ident = randchars()
        rg.environ = self.environ
        # the request object binds itself to rg.request
        Request(self.environ)

    def routing_setup(self):
        rg.urladapter = pysmvt.ag.route_map.bind_to_environ(self.environ)

    def user_setup(self):
        environ = self.environ
        try:
            return environ['beaker.session'].setdefault('__pysmvt_user', User())
        except KeyError, e:
            if '__pysmvt_user' not in str(e):
                raise
            environ['beaker.session']['__pysmvt_user'] = User()
            return environ['beaker.session']['__pysmvt_user']

    def __enter__(self):
        self.registry_setup()
        self.rg_setup()
        self.routing_setup()
        # allow middleware higher in the stack to help initilize the request
        # after the registry variables have been setup
        if 'pysmvt.request_setup' in self.environ:
            for callable in self.environ['pysmvt.request_setup']:
                callable()

    def __exit__(self, exc_type, exc_value, tb):
        if 'pysmvt.request_teardown' in self.environ:
            for callable in self.environ['pysmvt.request_teardown']:
                callable()

class ResponseContext(object):
    def __init__(self, error_doc_code):
        self.environ = rg.environ
        self.respview = None
        self.error_doc_code = error_doc_code
        self.css = []
        self.js = []

    def __enter__(self):
        rg.respctx = self
        # allow middleware higher in the stack to help initilize the response
        if 'pysmvt.response_setup' in self.environ:
            for callable in self.environ['pysmvt.response_setup']:
                callable()

    def __exit__(self, exc_type, e, tb):
        if 'pysmvt.response_teardown' in self.environ:
            for callable in self.environ['pysmvt.response_teardown']:
                callable()
        if isinstance(e, ForwardException):
            log.debug('forwarding to %s (%s)', e.forward_endpoint, e.forward_args)
            rg.forward_queue.append((e.forward_endpoint, e.forward_args))
            if len(rg.forward_queue) == 10:
                raise ProgrammingError('forward loop detected: %s' % '->'.join([g[0] for g in rg.forward_queue]))
            return True
        if 'beaker.session' in self.environ:
            self.environ['beaker.session'].save()

class WSGIApplication(Application):

    def __init__(self, module_or_settings, profile=None):
        Application.__init__(self, module_or_settings, profile)

    def request_manager(self, environ):
        return RequestManager(self, environ)

    def response_context(self, error_doc_code):
        return ResponseContext(error_doc_code)

    def response_cycle(self, endpoint, args, called_from=None, error_doc_code=None):
        rg.forward_queue = [(endpoint, args)]
        while True:
            with self.response_context(error_doc_code):
                endpoint, args = rg.forward_queue[-1]
                return self.dispatch_to_view(endpoint, args, called_from)

    def dispatch_to_view(self, endpoint, args, called_from=None):
        if len(rg.forward_queue) > 1:
            called_from = 'forward'
        else:
            called_from = called_from or 'client'
        log.debug('dispatch to %s (%s)', endpoint, args)
        if endpoint.startswith('__viewfuncs__:'):
            return function_view_handler(endpoint, args)
        return _getview(endpoint, args, called_from)

    def wsgi_app(self, environ, start_response):
        with self.request_manager(environ):
            try:
                try:
                    endpoint, args = rg.urladapter.match()
                except HTTPException, e:
                    log.debug('routing HTTP exception %s from %s', e, rg.request.url)
                    raise
                log.debug('wsgi_app processing %s (%s)', endpoint, args)
                response = self.response_cycle(endpoint, args)
            except HTTPException, e:
                response = self.handle_http_exception(e)
            except Exception, e:
                response = self.handle_exception(e)
            return response(environ, start_response)

    def handle_http_exception(self, e):
        """Handles an HTTP exception.  By default this will invoke the
        registered error handlers and fall back to returning the
        exception as response.

        .. versionadded: 0.3
        """
        endpoint = self.settings.error_docs.get(e.code)
        log.debug('handling http exception %s with %s', e, endpoint)
        if endpoint is None:
            return e
        try:
            return self.response_cycle(endpoint, {}, 'error docs', error_doc_code=e.code)
        except HTTPException, httpe:
            log.debug('error doc endpoint %s raised HTTPException: %s', endpoint, httpe)
            # the document handler is bad, so send back the original exception
            return e
        except Exception, exc:
            log.debug('error doc endpoint %s raised exception: %s', endpoint, exc)
            return self.handle_exception(exc)

    def handle_exception(self, e):
        """Default exception handling that kicks in when an exception
        occours that is not catched.  In debug mode the exception will
        be re-raised immediately, otherwise it is logged an the handler
        for an 500 internal server error is used.  If no such handler
        exists, a default 500 internal server error message is displayed.

        .. versionadded: 0.3
        """
        log.error('exception encountered: %s' % exception_with_context())
        if not self.settings.exception_handling:
            raise
        if 'email' in self.settings.exception_handling:
            try:
                mail_programmers('exception encountered', exception_with_context())
            except Exception, e:
                log.exception('exception when trying to email exception')
        if 'format' in self.settings.exception_handling:
            response = InternalServerError()
            response.description = '<pre>%s</pre>' % escape(exception_with_context())
            return response
        if 'handle' in self.settings.exception_handling:
            endpoint = self.settings.error_docs.get(500)
            if endpoint is None:
                # turn the exception into a 500 server response
                log.debug('handling exception with generic 500 response')
                return InternalServerError()
            else:
                log.debug('handling exception with error doc endpoint %s' % endpoint)
                try:
                    return self.response_cycle(endpoint, {}, 'error docs', error_doc_code=500)
                except HTTPException, httpe:
                    log.debug('error doc endpoint %s raised HTTPException: %s', endpoint, httpe)
                except Exception, exc:
                    log.exception('error doc endpoint %s raised exception:', endpoint)
                # the document handler is bad, so give a generic response
                return InternalServerError()
        raise

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)
