# -*- coding: utf-8 -*-
from os import path
from werkzeug.routing import Rule
from pysmvt.config import DefaultSettings

basedir = path.dirname(path.dirname(__file__))
app_package = path.basename(basedir)

class Default(DefaultSettings):
    def init(self):
        self.dirs.base = basedir
        self.app_package = app_package
        DefaultSettings.init(self)

class Testruns(Default):
    def init(self):
        Default.init(self)

        self.routing.routes.extend([
            Rule('/', endpoint='tests:Index')
        ])

        self.add_plugin(app_package, 'tests')

        # don't use exception catching, debuggers, logging, etc.
        self.apply_test_settings()

        self.emails.programmers = ['you@example.com']
        self.email.subject_prefix = '[pysvmt test app] '

    def get_storage_dir(self):
        return path.join(basedir, '..', 'test-output', app_package)
