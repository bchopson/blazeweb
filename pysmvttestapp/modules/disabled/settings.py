from werkzeug.routing import Rule

from pysmvt.config import QuickSettings

class Settings(QuickSettings):
    
    def __init__(self):
        QuickSettings.__init__(self)
        
        self.routes = ([
            Rule('/disabled/notthere', endpoint='disabled:NotThere'),
        ])
        
        # no more values can be added
        self.lock()