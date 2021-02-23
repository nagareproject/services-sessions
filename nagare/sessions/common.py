# --
# Copyright (c) 2008-2021 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

"""Base classes for the sessions management"""

import random
try:
    from cPickle import Pickler, Unpickler
except ImportError:
    from pickle import Pickler, Unpickler

from nagare.services import plugin
from nagare.server import reference
from nagare.server.services import SelectionService

from . import serializer


class Sessions(plugin.Plugin):
    """The sessions managers
    """
    PLUGIN_CATEGORY = 'nagare.sessions'

    CONFIG_SPEC = dict(
        plugin.Plugin.CONFIG_SPEC,
        debug='boolean(default=False)',
        pickler='string(default="nagare.sessions.common:Pickler")',
        unpickler='string(default="nagare.sessions.common:Unpickler")',
        serializer='string(default="nagare.sessions.serializer:Dummy")',
        reset_on_reload='boolean(default=True)'
    )

    def __init__(
        self,
        name, dist,
        debug=False,
        pickler=Pickler, unpickler=Unpickler,
        serializer=serializer.Dummy,
        reset_on_reload=True,
        publisher_service=None,
        **config
    ):
        """Initialization

        In:
          - ``serializer`` -- serializer / deserializer of the states
          - ``pickler`` -- pickler used by the serializer
          - ``unpickler`` -- unpickler used by the serializer
        """
        super(Sessions, self).__init__(
            name, dist,
            debug=debug,
            pickler=pickler, unpickler=unpickler,
            serializer=serializer,
            reset_on_reload=reset_on_reload,
            **config
        )

        publisher = publisher_service.service
        self.check_concurrence(publisher.has_multi_processes, publisher.has_multi_threads)

        pickler = reference.load_object(pickler)[0] if isinstance(pickler, str) else pickler
        unpickler = reference.load_object(unpickler)[0] if isinstance(unpickler, str) else unpickler
        serializer = reference.load_object(serializer)[0] if isinstance(serializer, str) else serializer
        self.serializer = serializer(pickler, unpickler, debug, self.logger)

        self.reset_on_reload = reset_on_reload

    @staticmethod
    def generate_id():
        return random.randint(1000000000000000, 9999999999999999)

    def handle_start(self, app):
        pass

    def reload(self):
        pass

    def handle_reload(self):
        if self.reset_on_reload:
            self.reload()

    def set_persistent_id(self, persistent_id):
        self.serializer.persistent_id = persistent_id

    def set_dispatch_table(self, dispatch_table):
        self.serializer.dispatch_table = dispatch_table

    def generate_secure_token(self):
        return b'%d' % self.generate_id()

    def generate_session_id(self):
        session_id = self.generate_id()
        while self.check_session_id(session_id):
            session_id = self.generate_id()

        return session_id

    def create(self, secure_token):
        """Create a new session

        Return:
          - id of the session
          - id of the state
          - secure token associated to the session
          - session lock
        """
        return self._create(self.generate_session_id(), secure_token or self.generate_secure_token())

    def fetch(self, session_id, state_id):
        """Retrieve the objects graph of a state

        In:
          - ``session_id`` -- session id of this state
          - ``state_id`` -- id of this state

        Return:
          - id of the latest state
          - secure number associated to the session
          - objects graph
        """
        new_state_id, secure_token, session_data, state_data = self._fetch(session_id, state_id)
        return new_state_id, secure_token, self.serializer.loads(session_data, state_data)

    def store(self, session_id, state_id, secure_token, use_same_state, data):
        """Store the state

        In:
          - ``session_id`` -- session id of this state
          - ``state_id`` -- id of this state
          - ``secure_id`` -- the secure number associated to the session
          - ``use_same_state`` -- is a copy of this state to be created?
          - ``data`` -- the objects graph
        """
        session_data, state_data = self.serializer.dumps(data, not use_same_state)
        self._store(session_id, state_id, secure_token, use_same_state, session_data, state_data)

    # -------------------------------------------------------------------------

    def check_concurrence(self, multi_processes, multi_threads):
        raise NotImplementedError()

    @staticmethod
    def check_session_id(session_id):
        """Test if a session exist

        In:
          - ``session_id`` -- id of a session

        Return:
          - is ``session_id`` the id of an existing session?
        """
        raise NotImplementedError()

    def create_lock(self, session_id):
        """Create a new lock for a session

        In:
          - ``session_id`` -- session id

        Return:
          - the lock
        """
        raise NotImplementedError()

    def get_lock(self, session_id):
        """Retrieve the lock of a session

        In:
          - ``session_id`` -- session id

        Return:
          - the lock
        """
        raise NotImplementedError()

    def _create(self, session_id, secure_id):
        """Create a new session

        In:
          - ``session_id`` -- id of the session
          - ``secure_id`` -- the secure number associated to the session
          - ``lock`` -- the lock of the session
        """
        raise NotImplementedError()

    def delete(self, session_id):
        """Delete a session

        In:
          - ``session_id`` -- id of the session to delete
        """
        raise NotImplementedError()

    def _fetch(self, session_id, state_id):
        """Retrieve a state with its associated objects graph

        In:
          - ``session_id`` -- session id of this state
          - ``state_id`` -- id of this state

        Return:
          - id of the more recent stored state
          - secure number associated to the session
          - data kept into the session
          - data kept into the state
        """
        raise NotImplementedError()

    def _store(self, session_id, state_id, secure_id, use_same_state, session_data, state_data):
        """Store a state and its associated objects graph

        In:
          - ``session_id`` -- session id of this state
          - ``state_id`` -- id of this state
          - ``secure_id`` -- the secure number associated to the session
          - ``use_same_state`` -- is this state to be stored in the previous snapshot?
          - ``session_data`` -- data to keep into the session
          - ``state_data`` -- data to keep into the state
        """
        raise NotImplementedError()


class SessionsSelection(SelectionService):
    ENTRY_POINTS = 'nagare.sessions'
    CONFIG_SPEC = dict(
        SelectionService.CONFIG_SPEC,
        type='string(default="memory", help="name of the session entry-point, registered under [nagare.sessions]")'
    )
    LOAD_PRIORITY = 90

    @property
    def DESC(self):
        return 'Proxy to the <%s> sessions manager' % self.type

    @property
    def plugin_config(self):
        return dict(super(SessionsSelection, self).plugin_config, type=self.type)

    def handle_start(self, app):
        self.service.handle_start(app)

    def handle_reload(self):
        self.service.handle_reload()

    def set_persistent_id(self, persistent_id):
        self.service.set_persistent_id(persistent_id)

    def set_dispatch_table(self, dispatch_table):
        self.service.set_dispatch_table(dispatch_table)

    def delete(self, session_id):
        self.service.delete(session_id)
