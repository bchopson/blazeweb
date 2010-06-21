from __future__ import with_statement
import __builtin__
import logging

from blazeutils.datastructures import BlankObject
from blazeutils.strings import randchars, randhash
from werkzeug.exceptions import HTTPException, InternalServerError
from werkzeug import create_environ
from werkzeug.routing import Map, Submount

from blazeweb.globals import ag, rg, settings, user
from blazeweb.events import Namespace, signal
from blazeweb.exceptions import ProgrammingError
from blazeweb.hierarchy import findobj, HierarchyImportError, \
    listplugins, visitmods, findview, split_endpoint
from blazeweb.logs import create_handlers_from_settings
from blazeweb.mail import mail_programmers
from blazeweb.templating import default_engine
from blazeweb.users import User
from blazeweb.utils import exception_with_context, abort, _Redirect
from blazeweb.utils.filesystem import mkdirs, copy_static_files
from blazeweb.views import _RouteToTemplate, _Forward
from blazeweb.wrappers import Request

log = logging.getLogger(__name__)

class RequestManager(object):
    def __init__(self, app, environ):
        self.app = app
        self.environ = environ

    def init_registry(self):
        environ = self.environ
        environ['paste.registry'].register(rg, BlankObject())
        environ['paste.registry'].register(settings, self.app.settings)
        environ['paste.registry'].register(ag, self.app.ag)
        environ['paste.registry'].register(user, self.init_user())

    def init_rg(self):
        rg.ident = randchars()
        rg.environ = self.environ
        # the request object binds itself to rg.request
        Request(self.environ)
        if self.environ.has_key('beaker.session'):
            rg.session = self.environ['beaker.session']
            log.debug('beaker session found, id: %s', rg.session.id)
        else:
            rg.session = None

    def init_routing(self):
        rg.urladapter = ag.route_map.bind_to_environ(self.environ)

    def init_user(self):
        environ = self.environ
        if 'beaker.session' in environ:
            if '__blazeweb_user' not in environ['beaker.session']:
                environ['beaker.session']['__blazeweb_user'] = User()
            return environ['beaker.session']['__blazeweb_user']
        # having a user object that is not in a session makes sense for testing
        # purposes, but probably not in production use
        return User()

    def __enter__(self):
        self.init_registry()
        self.init_rg()
        self.init_routing()
        # allow middleware higher in the stack to help initilize the request
        # after the registry variables have been setup
        if 'blazeweb.request_setup' in self.environ:
            for callable in self.environ['blazeweb.request_setup']:
                callable()

    def __exit__(self, exc_type, exc_value, tb):
        if 'blazeweb.request_teardown' in self.environ:
            for callable in self.environ['blazeweb.request_teardown']:
                callable()

class ResponseContext(object):
    def __init__(self, error_doc_code):
        self.environ = rg.environ
        # this gets set if this response context is initilized b/c
        # an error document handler is being called.  It allows the View
        # that handles the error code to know what code it is being called
        # for.
        self.error_doc_code = error_doc_code

    def __enter__(self):
        log.debug('enter response context')
        rg.respctx = self
        # allow middleware higher in the stack to help initilize the response
        if 'blazeweb.response_cycle_setup' in self.environ:
            for callable in self.environ['blazeweb.response_cycle_setup']:
                callable()

    def __exit__(self, exc_type, e, tb):
        log.debug('exit response context started')
        if 'blazeweb.response_cycle_teardown' in self.environ:
            for callable in self.environ['blazeweb.response_cycle_teardown']:
                callable()
        if isinstance(e, _Forward):
            log.debug('forwarding to %s (%s)', e.forward_endpoint, e.forward_args)
            rg.forward_queue.append((e.forward_endpoint, e.forward_args))
            if len(rg.forward_queue) == 10:
                raise ProgrammingError('forward loop detected: %s' % '->'.join([g[0] for g in rg.forward_queue]))
            return True
        if 'beaker.session' in self.environ:
            self.environ['beaker.session'].save()
        log.debug('exit response context finished')

class WSGIApp(object):

    def __init__(self, module_or_settings, profile=None):
        self._id = randhash()

        self.init_settings(module_or_settings, profile)
        self.init_ag()
        self.init_signals()
        self.init_events()
        self.init_plugin_settings()
        self.init_auto_actions()
        self.init_logging()
        self.init_routing()
        self.init_templating()

    def init_settings(self, module_or_settings, profile):
        self.settings = module_or_settings
        # get the settings class and instantiate it
        if profile is not None:
            module = module_or_settings
            try:
                self.settings = getattr(module, profile)()
            except AttributeError, e:
                if "has no attribute '%s'" % profile not in str(e):
                    raise
                raise ValueError('settings profile "%s" not found in this application' % profile)
        settings._push_object(self.settings)

    def init_ag(self):
        self.ag = BlankObject()
        self.ag.app = self
        self.ag.view_functions = {}
        self.ag.hierarchy_import_cache = {}
        self.ag.hierarchy_file_cache = {}
        self.ag.events_namespace = Namespace()
        ag._push_object(self.ag)

    def init_signals(self):
        # signals are weakly referenced, so we need to keep a reference as long
        # as this application is instantiated
        self.signals = (
            signal('blazeweb.events.initialized'),
            signal('blazeweb.settings.initialized'),
            signal('blazeweb.auto_actions.initialized'),
            signal('blazeweb.logging.initialized'),
            signal('blazeweb.routing.initialized'),
            signal('blazeweb.templating.initialized'),
            signal('blazeweb.request.started'),
            signal('blazeweb.response_cycle.started'),
            signal('blazeweb.response_cycle.ended'),
            signal('blazeweb.request.ended'),
        )

    def init_events(self):
        visitmods('events')
        signal('blazeweb.events.initialized').send(self.init_events)

    def init_plugin_settings(self):
        # now we need to assign plugin's settings to the main setting object
        for pname in listplugins():
            try:
                Settings = findobj('%s:config.settings.Settings' % pname)
                ms = Settings()
                # update the plugin's settings with any plugin level settings made
                # at the app level.  This allows us to override plugin settings
                # in our application's settings.py file.
                try:
                    ms.update(self.settings.plugins[pname])
                except KeyError, e:
                    if pname not in str(e):
                        raise # pragma: no cover
                self.settings.plugins[pname] = ms
            except HierarchyImportError, e:
                if '%s.config.settings' % pname not in str(e) and 'Settings' not in str(e):
                    raise # pragma: no cover

        # lock the settings, this ensures that an attribute error is thrown if an
        # attribute is accessed that doesn't exist.  Without the lock, a new attr
        # would be created, which is undesirable since any "new" attribute at this
        # point would probably be an accident
        self.settings.lock()

    def init_auto_actions(self):
        # create the writeable directories if they don't exist already
        if self.settings.auto_create_writeable_dirs:
            mkdirs(self.settings.dirs.data)
            mkdirs(self.settings.dirs.logs)
            mkdirs(self.settings.dirs.tmp)
        # copy static files if requested
        if self.settings.auto_copy_static.enabled:
            copy_static_files(self.settings.auto_copy_static.delete_existing)
        if self.settings.auto_abort_as_builtin == True:
            __builtin__.dabort = abort

    def init_logging(self):
        create_handlers_from_settings(self.settings)

    def init_routing(self):
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
                    raise  # pragma: no cover

    def init_templating(self):
        engine = default_engine()
        self.ag.tplengine = engine()

    def add_routing_rules(self, rules):
        for rule in rules or ():
            self.ag.route_map.add(rule)

    def request_manager(self, environ):
        return RequestManager(self, environ)

    def response_context(self, error_doc_code):
        return ResponseContext(error_doc_code)

    def response_cycle(self, endpoint, args, error_doc_code=None):
        rg.forward_queue = [(endpoint, args)]
        while True:
            with self.response_context(error_doc_code):
                endpoint, args = rg.forward_queue[-1]
                signal('blazeweb.response_cycle.started').send(endpoint=endpoint, urlargs=args)
                response = self.dispatch_to_endpoint(endpoint, args)
                signal('blazeweb.response_cycle.ended').send(response=response)
                return response

    def dispatch_to_endpoint(self, endpoint, args):
        log.debug('dispatch to %s (%s)', endpoint, args)
        if '.' not in endpoint:
            vklass = findview(endpoint)
        else:
            vklass = _RouteToTemplate
        v = vklass(args, endpoint)
        response = v.process()
        return response

    def wsgi_app(self, environ, start_response):
        with self.request_manager(environ):
            signal('blazeweb.request.started').send()
            try:
                try:
                    endpoint, args = rg.urladapter.match()
                except HTTPException, e:
                    log.debug('routing HTTP exception %s from %s', e, rg.request.url)
                    raise
                log.debug('wsgi_app processing %s (%s)', endpoint, args)
                response = self.response_cycle(endpoint, args)
            except _Redirect, e:
                response = e.response
            except HTTPException, e:
                response = self.handle_http_exception(e)
            except Exception, e:
                response = self.handle_exception(e)
            signal('blazeweb.request.ended').send(response=response)
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
            return self.response_cycle(endpoint, {}, error_doc_code=e.code)
        except HTTPException, httpe:
            log.debug('error doc endpoint %s raised HTTPException: %s', endpoint, httpe)
            # the document handler is bad, so send back the original exception
            return e
        except Exception, exc:
            log.debug('error doc endpoint %s raised exception: %s', endpoint, exc)
            return self.handle_exception(exc)

    def handle_exception(self, e):
        """Default exception handling that kicks in when an exception
        occours that is not caught.  In debug mode the exception will
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
            if endpoint is not None:
                log.debug('handling exception with error doc endpoint %s' % endpoint)
                try:
                    return self.response_cycle(endpoint, {}, error_doc_code=500)
                except HTTPException, httpe:
                    log.debug('error doc endpoint %s raised HTTPException: %s', endpoint, httpe)
                except Exception, exc:
                    log.exception('error doc endpoint %s raised exception:', endpoint)
            # turn the exception into a 500 server response
            log.debug('handling exception with generic 500 response')
            return InternalServerError()
        raise

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)
