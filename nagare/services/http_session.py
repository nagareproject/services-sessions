# --
# Copyright (c) 2008-2019 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

from contextlib import contextmanager

from nagare.services import plugin
from nagare.session import set_session
from nagare.sessions import exceptions


class Session(object):
    def __init__(self, session_service, is_new, secure_token, session_id, state_id, use_same_state):
        self.session = session_service
        self.is_new = is_new
        self.secure_token = secure_token
        self.session_id = session_id
        self.state_id = self.previous_state_id = state_id
        self.use_same_state = use_same_state

        self.data = {}

    def get_lock(self):
        return self.session.get_lock(self.session_id)

    def create(self):
        self.session_id, self.state_id, self.secure_token, lock = self.session.create(self.secure_token)
        self.previous_state_id = self.state_id

        return lock

    def fetch(self):
        if self.is_new:
            callbacks = {}
        else:
            new_state_id, self.secure_token, data = self.session.fetch(self.session_id, self.state_id)
            if not self.use_same_state:
                self.state_id, self.previous_state_id = new_state_id, self.state_id
            self.data, callbacks = data

        return self.data, callbacks

    def store(self):
        state_id = self.previous_state_id if self.use_same_state else self.state_id
        self.session.store(self.session_id, state_id, self.secure_token, self.use_same_state, self.data)

    @contextmanager
    def enter(self):
        lock = self.create() if self.is_new else self.get_lock()

        with lock as status:
            if not status:
                raise exceptions.LockError('Session {}, state {}'.format(self.session_id, self.state_id))

            yield self.fetch()
            self.store()


class SessionService(plugin.Plugin):
    LOAD_PRIORITY = 100
    CONFIG_SPEC = dict(
        plugin.Plugin.CONFIG_SPEC,
        states_history='boolean(default=False)',

        session_cookie={
            'name': 'string(default="nagare-session")',
            'secure': 'boolean(default=False)',
            'httponly': 'boolean(default=True)',
            'max_age': 'integer(default=None)'
        },

        security_cookie={
            'name': 'string(default="nagare-token")',
            'secure': 'boolean(default=False)',
            'httponly': 'boolean(default=True)',
            'max_age': 'integer(default=None)'
        }
    )

    def __init__(
        self,
        name, dist,
        states_history,
        session_cookie, security_cookie,
        local_service, session_service
    ):
        super(SessionService, self).__init__(name, dist)

        self.states_history = states_history

        self.session_cookie = session_cookie
        self.security_cookie = security_cookie
        self.local = local_service
        self.session = session_service.service

    def get_cookie(self, request, name):
        cookie = request.cookies.get(name)
        return (None, None) if (cookie is None) or (':' not in cookie) else cookie.split(':')

    def get_security_cookie(self, request):
        data, _ = self.get_cookie(request, self.security_cookie['name'])
        return (data or '').encode('ascii')

    def get_session_cookie(self, request):
        data, _ = self.get_cookie(request, self.session_cookie['name'])
        return int(data) if data else 0

    def set_cookie(self, request, response, name, data, **config):
        if name:
            response.set_cookie(name, data + ':' + request.script_name, path=request.script_name, **config)

    def set_security_cookie(self, request, response, secure_token):
        self.set_cookie(request, response, data=secure_token.decode('ascii'), **self.security_cookie)

    def set_session_cookie(self, request, response, session_id):
        self.set_cookie(request, response, data=str(session_id), **self.session_cookie)

    def delete_cookie(self, request, response, name, **config):
        if name:
            response.delete_cookie(name, **config)

    def delete_security_cookie(self, request, response):
        security_cookie_path = self.get_cookie(request, self.security_cookie['name'])[1]
        self.delete_cookie(request, response, self.security_cookie['name'], path=security_cookie_path)

    def delete_session_cookie(self, request, response):
        session_cookie_path = self.get_cookie(request, self.session_cookie['name'])[1]
        self.delete_cookie(request, response, self.session_cookie['name'], path=session_cookie_path)

    def extract_state_ids(self, request):
        """Search the session id and the state id into the request cookies and parameters

        In:
          - ``request`` -- the web request

        Return:
          - session id
          - state id
        """
        try:
            return (
                self.get_session_cookie(request) or int(request.params['_s']),
                int(request.params['_c']) if self.states_history else 0
            )
        except (KeyError, ValueError, TypeError):
            return None, None

    def get_state_ids(self, request):
        session_id, state_id = self.extract_state_ids(request)

        return (False, session_id, state_id) if session_id is not None else (True, None, None)

    def _handle_request(self, chain, session, **params):
        set_session(session)
        return chain.next(session=session, **params)

    def handle_request(self, chain, request, response, **params):
        new_session, session_id, state_id = self.get_state_ids(request)
        use_same_state = request.is_xhr or not self.states_history
        secure_token = self.get_security_cookie(request)
        session = Session(self.session, new_session, secure_token, session_id, state_id, use_same_state)

        try:
            with session.enter() as (data, callbacks):
                if not session.is_new and secure_token and (session.secure_token != secure_token):
                    raise exceptions.SessionSecurityError()

                self.set_security_cookie(request, response, session.secure_token)
                self.set_session_cookie(request, response, session.session_id)

                response = self._handle_request(
                    chain,
                    request=request, response=response,
                    session_id=session.session_id,
                    previous_state_id=session.previous_state_id,
                    state_id=session.state_id,
                    session=data, callbacks=callbacks,
                    **params
                )

                use_same_state = use_same_state or getattr(response, 'use_same_state', False)
                session.use_same_state = use_same_state or not self.states_history

                return response
        except exceptions.InvalidSessionError:
            response = request.create_redirect_response()

            self.delete_security_cookie(request, response)
            self.delete_session_cookie(request, response)

            raise response
