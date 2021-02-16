import aiohttp_jinja2
from aiohttp import web

from riego.model.parameters import get_parameters
from riego.db import get_db
from riego.web.users import User

import asyncio
import sys
import json

from riego.__init__ import __version__
from pkg_resources import packaging

router = web.RouteTableDef()


def setup_routes_system(app):
    app.add_routes(router)


@router.get("/system", name='system')
@aiohttp_jinja2.template('system/index.html')
async def system_index(request):
    text = ''
    installed_version = await _check_installed()
    if not packaging.version.parse(installed_version) == packaging.version.parse(__version__):  # noqa: E501
        text = '''Diese Riego Instanz läuft in der Version {}
                und entspricht nicht der installierten Version {}.'''  # noqa: E501
        text = text.format(__version__, installed_version)

    user = await User(request=request, db=get_db()).get_user()
    return {"text": text, 'user': user}


@router.get("/system/check_update", name='system_check_update')
@aiohttp_jinja2.template('system/index.html')
async def system_check_update(request):
    update = await _check_update("No update")
    return {'text':  update}


@router.get("/system/do_update", name='system_do_update')
@aiohttp_jinja2.template('system/index.html')
async def system_do_update(request):
    await _do_update()
    return {'text': "Restart erforderlich"}


@router.get("/system/restart", name='system_restart')
@aiohttp_jinja2.template('system/index.html')
async def system_restart(request):
    # TODO shedule exit for a few seconds and return a redirect
    asyncio.get_event_loop().call_later(1, exit, 0)
    raise web.HTTPSeeOther(request.app.router['system'].url_for())


@router.get("/system/log_file", name='system_log_file')
@aiohttp_jinja2.template('system/index.html')
async def system_log_file(request):
    with open(request.app['options'].log_file, "rt") as fp:
        return web.Response(body=fp.read(), content_type="text/plain")
        # return {'text': fp.read()}


@router.get("/system/parameters", name='system_parameters')
@aiohttp_jinja2.template("system/parameters.html")
async def parameters(request: web.Request):
    items = {}
    items['max_duration'] = get_parameters().max_duration
    items['start_time_1'] = get_parameters().start_time_1
    items['smtp_hostname'] = get_parameters().smtp_hostname
    items['smtp_port'] = get_parameters().smtp_port
    items['smtp_security'] = get_parameters().smtp_security
    items['smtp_user'] = get_parameters().smtp_user
    items['smtp_password'] = get_parameters().smtp_password
    items['smtp_from'] = get_parameters().smtp_from

    return {"items": items}


@router.post("/system/parameters")
@aiohttp_jinja2.template("system/parameters.html")
async def parameters_apply(request: web.Request):
    parameters = get_parameters()
    items = await request.post()
    for item in items:
        if getattr(parameters, item, None) is not None:
            setattr(parameters, item, items[item])
    return {"items": items}


async def _check_installed():
    version = "0.0.0"
    proc = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'pip', 'list', "--format=json",
        "--disable-pip-version-check",
        "--no-color",
        "--no-python-version-warning",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    stdout, stderr = await proc.communicate()
    data = json.loads(stdout)
    for item in data:
        if item['name'] == 'riego':
            version = item['version']
            break
    return version


async def _check_update(latest_version=None):
    proc = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'pip', 'list', "-o", "--format=json",
        "--disable-pip-version-check",
        "--no-color",
        "--no-python-version-warning",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    stdout, stderr = await proc.communicate()
    data = json.loads(stdout)
    for item in data:
        if item['name'] == 'riego':
            latest_version = item['latest_version']
            break
    return latest_version


async def _do_update():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'pip', 'install', "riego", "--upgrade",
        "--disable-pip-version-check",
        "--no-color",
        "--no-python-version-warning",
        "-q", "-q", "-q")
    await proc.wait()
    return proc.returncode
