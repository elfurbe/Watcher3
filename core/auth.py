import cherrypy
import core
import logging
from mako.template import Template

LOGIN_URL = '/auth/'

logging = logging.getLogger(__name__)


def check_credentials(username, password):
    ''' Verifies credentials for username and password.
    username (str): name to check against config
    password (str): password to check against config

    Returns bool
    '''
    l = [(core.CONFIG['Server']['authuser'], core.CONFIG['Server']['authpass'])]

    if core.CONFIG['Server']['adminrequired']:
        l.append((core.CONFIG['Server']['adminuser'], core.CONFIG['Server']['adminpass']))

    if (username, password) in l:
        return True
    else:
        return False


def is_admin(username):
    ''' check_auth method to verify if logged in user is admin
    username (str): username to check against config

    Returns bool
    '''
    return True if username == core.CONFIG['Server']['adminuser'] else False


def check_auth(*args, **kwargs):
    ''' Checks auth against required tests

    Uses methods decorated by self.require() to check auth conditions

    A tool that looks in config for 'auth.require'. If found and it is
        not None, a login is required and the entry is evaluated as a
        list of conditions that the user must fulfill

    If all checks are passed the page is loaded. If checks fail the
        user is internally redirected to the login page.

    Does not return
    '''

    conditions = cherrypy.request.config.get('auth.require')
    if conditions is not None:
        username = cherrypy.session.get(core.SESSION_KEY)
        if username:
            cherrypy.request.login = username
            for condition in conditions:
                # A condition is just a callable that returns true or false
                if not condition(username):
                    raise cherrypy.InternalRedirect(LOGIN_URL)
        else:
            raise cherrypy.InternalRedirect(LOGIN_URL)


cherrypy.tools.auth = cherrypy.Tool('before_handler', check_auth)


def require(*conditions):
    ''' A decorator that appends conditions to the auth.require config variable.
    '''
    def decorate(f):
        if not hasattr(f, '_cp_config'):
            f._cp_config = dict()
        if 'auth.require' not in f._cp_config:
            f._cp_config['auth.require'] = []
        f._cp_config['auth.require'].extend(conditions)
        return f
    return decorate


class AuthController:

    _cp_config = {
        'auth.require': None
    }

    def __init__(self):
        self.login_form = Template(filename='templates/login.html', module_directory=core.MAKO_CACHE)

    @cherrypy.expose
    def default(self):
        return self.login_form.render(url_base=core.URL_BASE, uitheme=core.CONFIG['Server']['uitheme'])

    def on_login(self, username, origin_ip):
        ''' Called on successful login
        username (str): username that logged in
        origin_ip (str): ip address of user

        Used to call various methods when a user successfully logs in

        Does not return
        '''

        logging.info(f'Successful login from {origin_ip}')

    def on_logout(self, username, origin_ip):
        ''' Called on logout
        username (str): username that logged out

        Used to call various methods when a user logs out

        Does not return
        '''

        logging.info(f'Logging out IP {origin_ip}')

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def login(self, username=None, password=None):
        ''' Tests user data against check_credentials
        username (str): submitted username      <optional - default None>
        password (str): submitted password      <optional - default None>

        Checks creds against check_credentials()
        Executes on_login() with username and origin_ip

        Returns bool
        '''

        if not username or not password:
            return False

        if 'X-Forwarded-For' in cherrypy.request.headers:
            origin_ip = cherrypy.request.headers['X-Forwarded-For']
        else:
            origin_ip = cherrypy.request.headers['Remote-Addr']

        if check_credentials(username, password) is False:
            logging.warning(f'Failed login attempt {username}:{password} from {origin_ip}')
            return False
        else:
            cherrypy.session.acquire_lock()
            cherrypy.session[core.SESSION_KEY] = cherrypy.request.login = username
            cherrypy.session.release_lock()
            self.on_login(username, origin_ip)
            return True

    @cherrypy.expose
    def logout(self):
        ''' Logs out user

        Clears session for user

        CP knows the user's session, so all we need to do is
            clear the session key.

        Internally redirects user to login page.

        If login is required for entire web-ui, returns url to login page
        If login is *not* required for web-ui (ie logging out admin for Settings pages), returns base url

        Returns str url path to login page
        '''

        username = cherrypy.session.get(core.SESSION_KEY, None)
        cherrypy.session.acquire_lock()
        cherrypy.session[core.SESSION_KEY] = None
        cherrypy.session.release_lock()
        if username:
            cherrypy.request.login = None
            if 'X-Forwarded-For' in cherrypy.request.headers:
                origin_ip = cherrypy.request.headers['X-Forwarded-For']
            else:
                origin_ip = cherrypy.request.headers['Remote-Addr']
            self.on_logout(username, origin_ip)

        return core.URL_BASE + (LOGIN_URL if core.CONFIG['Server']['authrequired'] else '/')
