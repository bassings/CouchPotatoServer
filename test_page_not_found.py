class DummyRequest:
    def __init__(self, uri):
        self.uri = uri


class DummyHandler:
    def __init__(self, uri):
        self.request = DummyRequest(uri)
        self.status = None
        self.redirect_to = None
        self.written = None

    def set_status(self, code):
        self.status = code

    def write(self, data):
        self.written = data

    def redirect(self, url):
        self.redirect_to = url


def test_page_not_found_redirects_non_api(monkeypatch):
    from couchpotato import page_not_found
    from couchpotato.environment import Env

    Env.set('web_base', '/base/')
    h = DummyHandler('/base/some/path')
    page_not_found(h)

    assert h.redirect_to == '/base/#some/path'
    assert h.status is None


def test_page_not_found_sets_404_for_api(monkeypatch):
    from couchpotato import page_not_found
    from couchpotato.environment import Env

    Env.set('web_base', '/base/')
    h = DummyHandler('/base/api/bad')
    page_not_found(h)

    assert h.status == 404
    assert isinstance(h.written, str)

