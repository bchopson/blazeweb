from __future__ import with_statement
import logging
from os import path

from jinja2 import Environment, TemplateNotFound, BaseLoader
from jinja2.utils import Markup

from blazeweb.globals import settings
from blazeweb.hierarchy import FileNotFound, findfile, split_endpoint
import blazeweb.templating as templating

log = logging.getLogger(__name__)

class Translator(templating.EngineBase):

    def __init__(self):
        self.env = Environment(
            loader=self.create_loader(),
            **self.get_settings()
            )
        self.init_globals()
        self.init_filters()

    def create_loader(self):
        return HierarchyLoader()

    def get_settings(self):
        def guess_autoescape(template_name):
            if template_name is None or '.' not in template_name:
                return False
            ext = template_name.rsplit('.', 1)[1]
            return ext in ('html', 'htm', 'xml')
        jsettings = settings.jinja
        if isinstance(jsettings.autoescape, (list, tuple)):
            jsettings.autoescape = guess_autoescape
        return jsettings.todict()

    def init_globals(self):
        self.env.globals.update(self.get_globals())

    def init_filters(self):
        self.env.filters.update(self.get_filters())

    def render_template(self, endpoint, context):
        self.update_context(context)
        return self.env.get_template(endpoint).render(context)

    def mark_safe(self, value):
        """ when a template has auto-escaping enabled, mark a value as safe """
        return Markup(value)

class HierarchyLoader(BaseLoader):
    """
        A modification of Jinja's FileSystemLoader to take into account
        the hierarchy.
    """

    def __init__(self, encoding=settings.default.charset):
        self.encoding = encoding

    def find_template_path(self, endpoint):
        # try module level first
        try:
            plugin, template = split_endpoint(endpoint)
            endpoint = path.join('templates', template)
            if plugin:
                endpoint = '%s:%s' % (plugin, endpoint)
            return findfile(endpoint)
        except FileNotFound:
            pass
        ## try app level second if module wasn't specified
        #try:
        #    if ':' not in template:
        #        endpoint = 'templates/%s' % template
        #    return findfile(endpoint)
        #except FileNotFound:
        #    pass

    def get_source(self, environment, endpoint):
        log.debug('get_source() processing: %s' % endpoint)
        fpath = self.find_template_path(endpoint)
        if not fpath:
            raise TemplateNotFound(endpoint)
        with open(fpath) as f:
            contents = f.read().decode(self.encoding)
        old = path.getmtime(fpath)
        return contents, fpath, lambda: path.getmtime(fpath) == old