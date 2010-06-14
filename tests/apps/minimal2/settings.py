from os import path

from pysmvt.config import DefaultSettings

basedir = path.dirname(__file__)
appname = path.basename(basedir)

class Default(DefaultSettings):
    def init(self):
        self.dirs.base = basedir
        self.appname = appname
        DefaultSettings.init(self)

        # since this is a quick start app, we want our views.py file to get
        # loaded
        self.auto_load_views = True

    def get_storage_dir(self):
        return path.join(basedir, '..', 'test-output', appname)

class Dispatching(Default):

    def init(self):
        Default.init(self)
        self.apply_test_settings()
        self.static_files.enabled = False

class Test(Default):
    def init(self):
        Default.init(self)

        self.apply_test_settings()
        print 'Test settings'

class Test2(Default):
    def init(self):
        Default.init(self)

        self.apply_test_settings()
        print 'Test2 settings'

class TestStorageDir(Default):
    def init(self):
        Default.init(self)

        self.apply_test_settings()
        self.auto_create_writeable_dirs = False

    def get_storage_dir(self):
        return DefaultSettings.get_storage_dir(self)

class NoAutoImportView(Default):
    def init(self):
        Default.init(self)

        self.apply_test_settings()

        # we just want to make sure turning the setting off works too
        self.auto_load_views = False
