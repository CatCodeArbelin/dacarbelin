import asyncio

from app.routers import web


def test_set_view_cookie_valid_mode():
    response = asyncio.run(web.set_view('mobile'))

    assert response.status_code == 302
    assert 'site_view=mobile' in response.headers.get('set-cookie', '')


def test_set_view_cookie_invalid_mode_falls_back_to_auto():
    response = asyncio.run(web.set_view('unknown'))

    assert response.status_code == 302
    assert 'site_view=auto' in response.headers.get('set-cookie', '')


def test_template_context_resolves_mobile_for_forced_full():
    scope = {
        'type': 'http',
        'method': 'GET',
        'path': '/',
        'headers': [(b'cookie', b'site_view=full'), (b'user-agent', b'iPhone')],
    }
    request = web.Request(scope)

    context = web.template_context(request)

    assert context['site_view'] == 'full'
    assert context['is_mobile_view'] is False
    assert context['site_view_switch_mode'] == 'mobile'


def test_template_context_resolves_mobile_by_auto_user_agent():
    scope = {
        'type': 'http',
        'method': 'GET',
        'path': '/',
        'headers': [(b'cookie', b'site_view=auto'), (b'user-agent', b'Android Chrome')],
    }
    request = web.Request(scope)

    context = web.template_context(request)

    assert context['site_view'] == 'auto'
    assert context['is_mobile_view'] is True
    assert context['site_view_switch_mode'] == 'full'
