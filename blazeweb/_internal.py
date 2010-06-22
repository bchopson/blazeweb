
###
### json code from Flask:
###

# try to load the best simplejson implementation available.  If JSON
# is not installed, we add a failing class.
json_available = True
try:
    import simplejson as json
except ImportError:
    try:
        import json
    except ImportError:
        json_available = False

def _assert_have_json():
    """Helper function that fails if JSON is unavailable."""
    if not json_available:
        raise RuntimeError('simplejson required but not installed')