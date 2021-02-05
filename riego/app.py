import asyncio
import configargparse
import pkg_resources
import os
import pathlib
# import logging
# import sys
import socket
from typing import Dict, Any

import riego.logger
from riego.model.base import Database
import riego.mqtt_gmqtt as riego_mqtt
import riego.boxes
#import riego.valves
#import riego.parameters
#import riego.timer


from riego.web.websockets import Websockets
from riego.web.routes import setup_routes
from riego.web.error_pages import setup_error_pages

from aiohttp import web
import jinja2
import aiohttp_jinja2
import aiohttp_debugtoolbar

import base64
from cryptography import fernet
from aiohttp_session import setup as setup_session, get_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage


from riego.__init__ import __version__


async def on_startup(app):
    app['log'].debug("on_startup")
    if app['options'].enable_asyncio_debug:
        asyncio.get_event_loop().set_debug(True)


async def on_shutdown(app):
    app['log'].debug("on_shutdown")


async def on_cleanup(app):
    app['log'].debug("on_cleanup")


async def alert_ctx_processor(request: web.Request) -> Dict[str, Any]:
    # Jinja2 context processor
    session = await get_session(request)
    alert = session.get("alert")
    session['alert'] = None
    session.changed()
    return {"alert": alert}


def main():
    p = configargparse.ArgParser(
        default_config_files=['/etc/riego/conf.d/*.conf', '~/.riego.conf',
                              'riego.conf'])
    p.add('-c', '--config', is_config_file=True, env_var='RIEGO_CONF',
          required=False, help='config file path')
    p.add('-d', '--database', help='Path and name for DB file',
          default='db/riego.db')
    p.add('-e', '--event_log', help='Full path and name for event logfile',
          default='log/event.log')
    p.add('--event_log_max_bytes', help='Maximum Evet Log Size in bytes',
          default=1024*300, type=int)
    p.add('--event_log_backup_count', help='How many files to rotate',
          default=3, type=int)
    p.add('-m', '--mqtt_host', help='IP adress of mqtt host',
          default='127.0.0.1')
    p.add('-p', '--mqtt_port', help='Port of mqtt service',
          default=1883, type=int)
    p.add('--mqtt_client_id', help='Client ID for MQTT-Connection',
          default=f'riego_ctrl_{socket.gethostname()}')
    p.add('--mqtt_subscription_topic', help='MQTT Topic that we are listening',
          default='riego/#')
    p.add('--database_migrations_dir',
          help='path to database migrations directory',
          default=pkg_resources.resource_filename('riego', 'migrations'))
    p.add('--base_dir', help='Change only if you know what you are doing',
          default=pathlib.Path(__file__).parent)
    p.add('--http_server_bind_address',
          help='http-server bind address', default='0.0.0.0')
    p.add('--http_server_bind_port', help='http-server bind port',
          default=8080, type=int)
    p.add('--http_server_static_dir',
          help='Serve static html files from this directory',
          default=pkg_resources.resource_filename('riego.web', 'static'))
    p.add('--http_server_template_dir',
          help='Serve template files from this directory',
          default=pkg_resources.resource_filename('riego.web', 'templates'))
    p.add('--websocket_path', help='url path for websocket',
          default="/ws")
    p.add('--time_format', help='Store and display time',
          default="%Y-%m-%d %H:%M:%S")
    p.add('--mqtt_cmnd_prefix', help='',
          default="cmnd")
    p.add('--mqtt_result_subscription', help='used by class valves',
          default="stat/+/RESULT")

    p.add('--mqtt_lwt_subscription', help='used by class boxes',
          default="tele/+/LWT")
    p.add('--mqtt_state_subscription', help='used by class boxes',
          default="tele/+/STATE")
    p.add('--mqtt_info1_subscription', help='used by class boxes',
          default="tele/+/INFO1")
    p.add('--mqtt_info2_subscription', help='used by class boxes',
          default="tele/+/INFO2")

    p.add('--mqtt_sensor_subscription', help='yet not used',
          default="tele/+/SENSOR")

    p.add('--mqtt_keyword_ON', help='',
          default="ON")
    p.add('--mqtt_keyword_OFF', help='',
          default="OFF")

    p.add('--enable_aiohttp_debug_toolbar', action='store_true')
    p.add('--enable_asyncio_debug', action='store_true')
    p.add('--enable_timer_dev_mode', action='store_true')

    p.add('-v', '--verbose', help='verbose', action='store_true')
    p.add('--version', help='Print version and exit', action='store_true')
    p.add('--defaults', help='Print options with default values and exit',
          action='store_true')

    options = p.parse_args()

    try:
        with open('riego.conf', 'xt') as f:
            for item in vars(options):
                f.write(f'# {item}={getattr(options, item)}\n')
    except IOError:
        pass

    if options.defaults:
        for item in vars(options):
            print(f'# {item}={getattr(options, item)}')
        exit(0)

    if options.version:
        print('Version: ', __version__)
        exit(0)

    if options.verbose:
        print(p.format_values())

#    if sys.version_info >= (3, 8):
#        asyncio.DefaultEventLoopPolicy = asyncio.WindowsSelectorEventLoopPolicy  # noqa: E501

    if os.name == "posix":
        import uvloop  # pylint: disable=import-error
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

    app = web.Application()

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.on_cleanup.append(on_cleanup)

    app['version'] = __version__
    app['options'] = options
    app['log'] = riego.logger.create_log(options)
#    app['event_log'] = riego.logger.create_event_log(options)
    app['websockets'] = Websockets(app)
    app['db'] = Database(app)
    app['mqtt'] = riego_mqtt.Mqtt(app)
    app['boxes'] = riego.boxes.Boxes(app)
#    app['valves'] = riego.valves.Valves(app)
#    app['parameters'] = riego.parameters.Parameters(app)
#    app['timer'] = riego.timer.Timer(app)

    fernet_key = fernet.Fernet.generate_key()
    secret_key = base64.urlsafe_b64decode(fernet_key)
    setup_session(app, EncryptedCookieStorage(secret_key))

    loader = jinja2.FileSystemLoader(options.http_server_template_dir)
    aiohttp_jinja2.setup(app,
                         loader=loader,
                         # enable_async=True,
                         # context_processors=[alert_ctx_processor],
                         )

    setup_routes(app)
    setup_error_pages(app)

    if options.enable_aiohttp_debug_toolbar:
        aiohttp_debugtoolbar.setup(
            app, check_host=False, intercept_redirects=False)

    app['log'].info("Start")

    web.run_app(app,
                host=options.http_server_bind_address,
                port=options.http_server_bind_port)
