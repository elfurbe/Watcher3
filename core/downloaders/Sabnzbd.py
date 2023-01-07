import json
import logging
import urllib

import core
from core.helpers import Url

logging = logging.getLogger(__name__)


def test_connection(data):
    ''' Tests connectivity to Sabnzbd
    :para data: dict of Sab server information

    Tests if we can get Sab's stats using server info in 'data'

    Return True on success or str error message on failure
    '''

    logging.info('Testing connection to SABnzbd.')

    host = data['host']
    port = data['port']
    api = data['api']

    url = f'http://{host}:{port}/sabnzbd/api?apikey={api}&mode=server_stats'

    try:
        response = Url.open(url).text
        if 'error' in response:
            return response
        return True
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        logging.error('Sabnzbd connection test failed.', exc_info=True)
        return f'{e}.'


def add_nzb(data):
    ''' Adds nzb file to sab to download
    :param data: dict of nzb information

    Returns dict {'response': True, 'downloadid': 'id'}
                    {'response': False, 'error': 'exception'}

    '''

    logging.info('Sending NZB {} to SABnzbd.'.format(data['title']))

    conf = core.CONFIG['Downloader']['Usenet']['Sabnzbd']

    host = conf['host']
    port = conf['port']
    api = conf['api']

    base_url = f'http://{host}:{port}/sabnzbd/api?apikey={api}'

    mode = 'addurl'
    name = urllib.parse.quote(data['guid'])
    nzbname = data['title']
    cat = conf['category']
    priority_keys = {
        'Paused': '-2',
        'Low': '-1',
        'Normal': '0',
        'High': '1',
        'Forced': '2'
    }
    priority = priority_keys[conf['priority']]

    command_url = f'&mode={mode}&name={name}&nzbname={nzbname}&cat={cat}&priority={priority}&output=json'

    url = base_url + command_url

    try:
        response = json.loads(Url.open(url).text)

        if response['status'] is True and len(response['nzo_ids']) > 0:
            downloadid = response['nzo_ids'][0]
            logging.info(f'NZB sent to SABNzbd - downloadid {downloadid}.')
            return {'response': True, 'downloadid': downloadid}
        else:
            logging.error(f'Unable to send NZB to Sabnzbd. {response}')
            return {'response': False, 'error': 'Unable to add NZB.'}

    except Exception as e:
        logging.error('Unable to send NZB to Sabnzbd.', exc_info=True)
        return {'response': False, 'error': str(e)}


def cancel_download(downloadid):
    ''' Cancels download in client
    downloadid: int download id

    Returns bool
    '''
    logging.info(f'Cancelling download # {downloadid} in SABnzbd.')

    conf = core.CONFIG['Downloader']['Usenet']['Sabnzbd']

    host = conf['host']
    port = conf['port']
    api = conf['api']

    url = f'http://{host}:{port}/sabnzbd/api?apikey={api}&mode=queue&name=delete&value={downloadid}&output=json'

    try:
        response = json.loads(Url.open(url).text)
        return response.get('status', False)
    except Exception as e:
        logging.error('Unable to cancel download.', exc_info=True)
        return False
