# -*- coding: utf-8 -*-
from os import path
import os
import logging
import re
from pysmvt import settings, ag
from pysmvt.logs import _create_handlers_from_settings
from werkzeug.routing import Rule, Map, Submount
from pysmvt.utils import OrderedDict, Context
from pysmvt.utils.filesystem import mkdirs
from pysmvt.exceptions import SettingsError
from pysutils import case_us2cw, multi_pop
from pysutils.config import QuickSettings

class EnabledSettings(QuickSettings):
    """
        a custom settings object for "enabled" modules.  The only difference
        is that when iterating over the object, only modules with
        .enabled = True are returned.
    """
    def _set_data_item(self, item, value):
        if not isinstance(value, QuickSettings):
            raise TypeError('all values set on ModuleSettings must be a QuickSettings object')
        QuickSettings._set_data_item(self, item, value)

    def __len__(self):
        return len(self.keys())

    def iteritems(self, showinactive=False):
        for k,v in self._data.iteritems():
            try:
                if showinactive or v.enabled == True:
                    yield k,v
            except AttributeError, e:
                if "object has no attribute 'enabled'" not in str(e):
                    raise

    def __iter__(self):
        for v in self._data.values():
            try:
                if v.enabled == True:
                    yield v
            except AttributeError, e:
                if "object has no attribute 'enabled'" not in str(e):
                    raise

    def __contains__(self, key):
        return key in self.todict()

    def keys(self, showinactive=False):
        return [k for k,v in self.iteritems(showinactive)]

    def values(self, showinactive=False):
        return [v for k,v in self.iteritems(showinactive)]

    def todict(self, showinactive=False):
        if showinactive:
            return self._data
        d = OrderedDict()
        for k,v in self.iteritems():
            d[k] = v
        return d

class DefaultSettings(QuickSettings):
    # child classes should define the following
    # basename
    # basedir
    def __init__(self):
        QuickSettings.__init__(self)
        self.init()

    def init(self):
        # supporting applications
        self.supporting_apps = []

        # don't want this to be empty
        self.plugins = QuickSettings()

        #######################################################################
        # ROUTING
        #######################################################################
        self.routing.routes = [
            # a special route for testing purposes
            Rule('/[pysmvt_test]', endpoint='[pysmvt_test]')
        ]

        # note that you shouldn't really need to use the routing prefix if
        # SCRIPT_NAME and PATH_INFO are set correctly as the Werkzeug
        # routing tools (both parsing rules and generating URLs) will
        # take these environment variables into account.
        self.routing.prefix = ''

        # the settings for the Werkzeug routing Map object:
        self.routing.map.default_subdomain=''
        self.routing.map.charset='utf-8'
        self.routing.map.strict_slashes=True
        self.routing.map.redirect_defaults=True
        self.routing.map.converters=None

        #######################################################################
        # DIRECTORIES required by PYSVMT
        #######################################################################
        self.dirs.storage = path.abspath(self.get_storage_dir())
        self.dirs.writeable = path.join(self.dirs.storage, 'writeable')
        self.dirs.static = path.join(self.dirs.storage, 'static')
        self.dirs.data = path.join(self.dirs.writeable, 'data')
        self.dirs.logs = path.join(self.dirs.writeable, 'logs')
        self.dirs.tmp = path.join(self.dirs.writeable, 'tmp')

        #######################################################################
        # SESSIONS
        #######################################################################
        #beaker session options
        #http://beaker.groovie.org/configuration.html
        self.beaker.enabled = True
        self.beaker.type = 'dbm'
        self.beaker.data_dir = path.join(self.dirs.tmp, 'session_cache')
        self.beaker.lock_dir = path.join(self.dirs.tmp, 'beaker_locks')

        #######################################################################
        # TEMPLATES
        #######################################################################
        self.template.default = 'default.html'

        #######################################################################
        # SYSTEM VIEW ENDPOINTS
        #######################################################################
        self.endpoint.sys_error = ''
        self.endpoint.sys_auth_error = ''
        self.endpoint.bad_request_error = ''

        #######################################################################
        # EXCEPTION HANDLING
        #######################################################################
        # an exception will always be logged using python logging
        # If bool(exception_handling) == False, only logging will occur
        # If bool(exception_handling) == True, it is expected to be a list
        # options for handling the exception.  Options are:
        #   - handle: will try to use a 500 error document.  If that doesn't exist
        #       then a generic 500 respose will be returned
        #   - format: takes precedence over 'handle'. it formats the exception and
        #       displays it as part of the response body. Not usually needed b/c
        #       the debugger is better for development, but the benefit is that
        #       you get more info about the request & environ in the output.
        #   - email: an email will be sent using mail_programmers() whenever
        #       an exception is encountered
        # example of all:
        #   self.exception_handling = ['handle', 'format', 'email']
        self.exception_handling = ['handle', 'email']

        #######################################################################
        # DEBUGGING
        #######################################################################
        # only matters when exceptions are not handled above.  Setting interactive =
        # to True will give a python command prompt in the stack trace
        #
        #          ******* SECURITY ALERT **********
        # setting interactive = True would allow ANYONE who has http access to the
        # server to run arbitrary code.  ONLY use in an isolated development
        # environment.
        self.debugger.enabled = False
        self.debugger.interactive = False

        #######################################################################
        # EMAIL ADDRESSES
        #######################################################################
        # the 'from' address used by mail_admins() and mail_programmers()
        # defaults if not set
        self.emails.from_server = ''
        # the default 'from' address used if no from address is specified
        self.emails.from_default = ''
        # a default reply-to header if one is not specified
        self.emails.reply_to = ''

        ### recipient defaults.  Should be a list of email addresses
        ### ('foo@example.com', 'bar@example.com')

        # will always add theses cc's to every email sent
        self.emails.cc_always = None
        # default cc, but can be overriden
        self.emails.cc_defaults = None
        # will always add theses bcc's to every email sent
        self.emails.bcc_always = None
        # default bcc, but can be overriden
        self.emails.bcc_defaults = None
        # programmers who would get system level notifications (code
        # broke, exception notifications, etc.)
        self.emails.programmers = None
        # people who would get application level notifications (payment recieved,
        # action needed, etc.)
        self.emails.admins = None
        # a single or list of emails that will be used to override every email sent
        # by the system.  Useful for debugging.  Original recipient information
        # will be added to the body of the email
        self.emails.override = None

        #######################################################################
        # EMAIL SETTINGS
        #######################################################################
        # used by mail_admins() and mail_programmers()
        self.email.subject_prefix = ''
        # Should we actually send email out to a SMTP server?  Setting this to
        # False can be useful when doing testing.
        self.email.is_live = True

        #######################################################################
        # SMTP SETTINGS
        #######################################################################
        self.smtp.host = 'localhost'
        self.smtp.port = 25
        self.smtp.user = ''
        self.smtp.password = ''
        self.smtp.use_tls = False

        #######################################################################
        # OTHER DEFAULTS
        #######################################################################
        self.default_charset = 'utf-8'
        self.default.file_mode = 0640
        self.default.dir_mode = 0750

        #######################################################################
        # ERROR DOCUMENTS
        #######################################################################
        # you can set endpoints here that will be used if an error response
        # is detected to try and give the user a more consistent experience
        # self.error_docs[404] = 'errorsmod:NotFound'
        self.error_docs

        #######################################################################
        # TESTING
        #######################################################################
        # an application can define functions to be called after the app
        # is initialized but before any test inspection is done or tests
        # are ran.  The import strings given are relative to the application
        # stack.  Some examples:
        #      self.testing.init_callables = (
        #      'testing.setup_db',  # calls setup_db function in myapp.testing
        #      'testing:Setup.doit', # calls doit class method of Setup in myapp.testing
        #      )
        self.testing.init_callables = None

        #######################################################################
        # Log Files
        ######################################################################
        # a fast cutoff switch, if enabled, you still have to enable errors or
        # application below.  It DOES NOT affect the null_handler setting.
        self.logs.enabled = True
        # logs will be logged using RotatingFileHandler
        # maximum log file size is 50MB
        self.logs.max_bytes = 1024*1024*10
        # maximum number of log files to keep around
        self.logs.backup_count = 5
        # will log all WARN and above logs to errors.log in the logs directory
        self.logs.errors.enabled = True
        # will log all application logs (level 25) to application.log.  This will
        # also setup the logging object so you can use log.application().  The
        # application log level is 25, which is greater than INFO but less than
        # WARNING.
        self.logs.application.enabled = True
        # if you don't want application or error logging and don't setup your
        # own, then you may see error messages on stdout like "No handlers could
        # be found for logger ...".  Enable the null_handler to get rid of
        # those messages.  But, you should *really* enable logging of some kind.
        self.logs.null_handler.enabled = False

        # log http requests.  You must put HttpRequestLogger middleware
        # in your WSGI stack, preferrably as the last application so that its
        # the first middleware in the stack
        self.logs.http_requests.enabled = False
        self.logs.http_requests.filters.path_info = None
        self.logs.http_requests.filters.request_method = None

        #######################################################################
        # Static Files
        ######################################################################
        # should we use Werkzeug's SharedData middleware for serving static
        # files?
        self.static_files.enabled = True

        #######################################################################
        # Importing Helper
        ######################################################################
        # when using @asviews, the view modules need to be loaded after the
        # app is initialized so that the routes get setup properly
        self.auto_load_views = False

    def add_plugin(self, appname, namespace, package=None):
        # a little hack to get the default value to hang an application's
        # plugin's off of
        self.pluginmap._data.setdefault(appname, EnabledSettings())
        self.set_dotted('pluginmap.%s.%s.enabled' % (appname, namespace), True)
        if package:
            cvalue = self.get_dotted('pluginmap.%s.%s.packages' % (appname, namespace))
            if not cvalue:
                self.set_dotted('pluginmap.%s.%s.packages' % (appname, namespace), [package])
                return
            cvalue.append(package)

    def get_storage_dir(self):
        ## files should be stored outside the source directory so that your
        ## application can be packaged.  We are assuming that you are in
        ## a virtualenv.  If not, then we default to the directory above
        ## the base directory
        venv_dir = os.getenv('VIRTUAL_ENV')
        if venv_dir:
            return path.join(venv_dir, 'storage-%s' % self.appname)
        return path.join(self.dirs.base, '..', 'storage-%s' % self.appname)

    def apply_test_settings(self):
        """
            changes settings to the defaults for testing
        """
        # nose has good log capturing facilities, so just let it ride
        self.logs.enabled=False
        # don't want pesky error messages
        self.logs.null_handler.enabled = True
        # we want exceptions to come all the way to nose
        self.exception_handling = False
        # ditto
        self.debugger.enabled = False

def appslist(reverse=False):
    if reverse:
        apps = list(settings.supporting_apps)
        apps.reverse()
        apps.append(settings.appname)
        return apps
    return [settings.appname] + settings.supporting_apps
