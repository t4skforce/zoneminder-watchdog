#!/usr/bin/python3
# -*- coding: utf-8 -*-
# https://zoneminder.readthedocs.io/en/stable/api.html
#
# apt-get install python3-requests python3-pillow
#

import logging
import argparse
import requests
import hashlib
from PIL import Image
from io import BytesIO
import pickle
import os
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s:%(lineno)d] %(message)s"
)
log = logging.getLogger("zoneminder")
import urllib3
urllib3.disable_warnings()
logging.getLogger("requests.packages.urllib3.connectionpool").setLevel(logging.WARNING)

DATA_FILE = 'zoneminder.pickle'

parser = argparse.ArgumentParser(description='Watch zoneminder camera connection')
parser.add_argument('--url',type=str,default='http://127.0.0.1/zm/',required=False,help='Zoneminder URL')
parser.add_argument('--username',type=str,default='admin',required=False,help='Username')
parser.add_argument('--password',type=str,default='admin',required=False,help='Password')
parser.add_argument('--interval',type=int,default=300,required=False,help='Interval seconds')
args = parser.parse_args()

if args.url.endswith('/'): args.url=args.url[:-1]
class Config(object):
    def __init__(self, initial_data):
        for key in initial_data:
            setattr(self, key, initial_data[key])
url = Config({
    'login':'{url}/index.php'.format(url=args.url),
    'monitors':'{url}/api/monitors.json'.format(url=args.url),
    'monitor':'{url}/cgi-bin/nph-zms'.format(url=args.url),
    'edit':'{url}/api/monitors/{monId}.json'.format(url=args.url,monId='{monId}')
})

def restart(s, monId):
    r = s.put(url.edit.format(monId=monId), data={'Monitor[Enabled]':'0'}, verify=False)
    if r.status_code != 200: raise Exception('Could not log into {url} response code {code:d}'.format(url=url.login,code=r.status_code))
    r = s.put(url.edit.format(monId=monId), data={'Monitor[Enabled]':'1'}, verify=False)
    if r.status_code != 200: raise Exception('Could not log into {url} response code {code:d}'.format(url=url.login,code=r.status_code))

log.info('Started zoneminder-watchdog.')

while True:
    time.sleep(args.interval)
    s = requests.Session()
    try:
        r = s.post(url.login, data = {
            'username':args.username,
            'password':args.password,
            'action':'login',
            'view':'console'
        }, verify=False)
        if r.status_code != 200: raise Exception('Could not log into {url} response code {code:d}'.format(url=url.login,code=r.status_code))
        r = s.get(url.monitors,verify=False)
        if r.status_code != 200: raise Exception('Could not load monitors {url} response code {code:d}'.format(url=url.monitors,code=r.status_code))
        cameras = {}
        if os.path.isfile(DATA_FILE):
            with open(DATA_FILE, 'rb') as f:
                cameras = pickle.load(f)
        d = r.json()
        for mon in d.get('monitors',[]):
            mon = mon.get('Monitor',{})
            monId = mon.get('Id',None)
            enabled = not mon.get('Function',None) in [None,'None']
            if not monId is None and enabled is True:
                r = s.get(url.monitor,params = {
                    'mode':'single',
                    'monitor':monId,
                    'user':args.username,
                    'pass':args.password
                }, verify=False)
                if r.status_code != 200:
                    log.warn('monId:{monId} requires restarting response code {code:d}'.format(monId=monId,code=r.status_code))
                    restart(s,monId)
                else:
                    try:
                        img = Image.open(BytesIO(r.content))
                        h = hashlib.sha1(img.tobytes()).hexdigest()
                        issame = cameras.get(monId,None) == h
                        cameras[monId]=h
                        isblack = img.convert("L").getextrema() == (0, 0)
                        if issame:
                            log.info('monId:{monId} requires restarting error:{error}'.format(monId=monId,error='image is exact same as before, no update'))
                            restart(s,monId)
                        elif isblack:
                            log.info('monId:{monId} requires restarting error: {error}'.format(monId=monId,error='image is black, possibly connection lost'))
                            restart(s,monId)
                        else:
                            log.info('monId:{monId} check OK ({hash})'.format(monId=monId,hash=h))
                    except Exception as e:
                        log.exception('monId:{monId} requires restarting error:{error}'.format(monId=monId,error=str(e)))
                        restart(s,monId)
        with open(DATA_FILE, 'wb') as f:
            pickle.dump(cameras, f)
    except Exception as e:
        log.exception(e)
