from os import path
import logging

from jinja2 import FileSystemLoader, Environment, TemplateNotFound
from blazeutils.datetime import safe_strftime
from blazeutils.strings import case_cw2us

from blazeweb.globals import ag
from blazeweb.hierarchy import findfile, FileNotFound

log = logging.getLogger(__name__)

class JinjaBase(object):

    def __init__(self, endpoint):

        # setup some needed attributes.  We have to do this at runtime instead
        # of putting them as class attributes b/c the class atrributes are
        # shared among instantiated classes
        self.templateName = None
        self.tpl_extension = None
        self._templateValues = {}

        app_mod_name = endpoint.split(':')[0]

        # change jinja tag style
        self.setOptions()

        # Setup Jinja template environment only once per process
        if hasattr(ag, 'templateEnv'):
            self.jinjaTemplateEnv = ag.templateEnv
        else:
            ag.jinjaTemplateEnv = self.templateEnv = Environment(**self._jinjaEnvOptions)
            ag.jinjaTemplateEnv.filters['strftime'] = safe_strftime

        # setup the AppTemplateLoader for each view that uses a template
        self.templateEnv.loader = AppTemplateLoader(app_mod_name)

    def setOptions(self):
        #jinja stuff has to be setup before we call parent init
        self._jinjaEnvOptions = {
                'block_start_string' : '<%',
                'block_end_string' : '%>',
                'variable_start_string' : '<{',
                'variable_end_string' : '}>',
                'comment_start_string' : '<#',
                'comment_end_string' : '#>',
            }

    def render(self):
        template = self.templateEnv.get_template(self.templateName + '.' + self.tpl_extension)
        return template.render(self._templateValues)

    def assign(self, key, value):
        self._templateValues[key] = value

class JinjaHtmlBase(JinjaBase):

    def __init__(self, modulePath):

        # call parent init
        JinjaBase.__init__(self, modulePath)

        #setup my own initilization values
        self.tpl_extension = 'html'

class AppTemplateLoader(FileSystemLoader):
    """
        A modification of Jinja's FileSystemLoader to take into account how
        blazeweb apps can inherit from other apps
    """

    def __init__(self, modname, encoding='utf-8'):
        self.encoding = encoding
        self.modname = modname

    def find_template_path(self, template):
        # try module level first
        try:
            if ':' not in template:
                endpoint = '%s:templates/%s' % (self.modname, template)
            return findfile(endpoint)
        except FileNotFound:
            pass
        # try app level second if module wasn't specified
        try:
            if ':' not in template:
                endpoint = 'templates/%s' % template
                return findfile(endpoint)
        except FileNotFound:
            pass

    def get_source(self, environment, template):
        log.debug('get_source() processing: %s' % template)
        fpath = self.find_template_path(template)
        if not fpath:
            # in view.py, we default a template name to the name of the view class
            # which results in a CapWordsFileName.  But file names should be
            # underscore_notation.  This needs to be fixed in view.py eventually,
            # but that requires us to update all our template file names.  So
            # I am doing it here as a hack.  We can depricate the old later.
            log.debug('could not locate template file, trying underscore version')
            utemplate = case_cw2us(template)
            if utemplate == template:
                log.debug('underscore version was the same')
                raise TemplateNotFound(template)
            fpath = self.find_template_path(utemplate)
            if not fpath:
                raise TemplateNotFound(template)
        f = file(fpath)
        try:
            contents = f.read().decode(self.encoding)
        finally:
            f.close()
        old = path.getmtime(fpath)
        return contents, fpath, lambda: path.getmtime(fpath) == old