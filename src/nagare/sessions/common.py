# --
# Copyright (c) 2008-2024 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

"""Base classes for the sessions management."""

import sys
import gzip
import zlib
import random
import copyreg
from types import LambdaType, ModuleType, FunctionType
from pickle import Pickler, Unpickler
from marshal import dumps, loads
from importlib import import_module

from nagare.server import reference
from nagare.services import plugin
from nagare.server.services import SelectionService

from . import serializer

try:
    import stackless  # noqa: F401
except ModuleNotFoundError:

    def ll(module, code, defaults, closure):
        mglobals = sys.modules[module].__dict__
        fglobals = {k: v for k, v in mglobals.items() if not (k.startswith('__') and k.endswith('__'))}
        fglobals['__builtins__'] = mglobals['__builtins__']

        lambda_ = LambdaType(
            loads(code),  # noqa: S302
            fglobals,
            None,
            defaults,
            closure and tuple((lambda x: lambda: x)(cell).__closure__[0] for cell in closure),
        )
        lambda_.__module__ = module
        return lambda_

    def lm(module_name):
        return import_module(module_name)

    class Pickler(Pickler):
        def reducer_override(self, obj):
            if (getattr(obj, '__name__', '') == '<lambda>') or (
                isinstance(obj, FunctionType) and ('.<locals>.' in obj.__qualname__)
            ):
                return ll, (
                    obj.__module__,
                    dumps(obj.__code__),
                    obj.__defaults__,
                    obj.__closure__ and [cell.cell_contents for cell in obj.__closure__],
                )

            return NotImplemented

    copyreg.pickle(ModuleType, lambda m: (lm, (m.__name__,)))


class Compressor(object):
    @classmethod
    def compress(cls, data):
        compressed_data = cls._compress(data)
        return compressed_data if len(compressed_data) < len(data) else data

    @classmethod
    def decompress(cls, data):
        return cls._decompress(data) if cls.is_compressed(data) else data

    @staticmethod
    def is_compressed(data):
        raise NotImplementedError()

    @staticmethod
    def _compress(cls, data):
        raise NotImplementedError()

    @staticmethod
    def _decompress(cls, data):
        raise NotImplementedError()


class GZipCompressor(Compressor):
    _compress = gzip.compress
    _decompress = gzip.decompress

    @staticmethod
    def is_compressed(data):
        return data and (data[0] == 0o37) and (data[1] == 0o213)


class ZLibCompressor(Compressor):
    _compress = zlib.compress
    _decompress = zlib.decompress

    @staticmethod
    def is_compressed(data):
        return data and (data[0] == 0x78) and ((data[0] * 256 + data[1]) % 31 == 0)


class Sessions(plugin.Plugin):
    """The sessions managers."""

    PLUGIN_CATEGORY = 'nagare.sessions'

    CONFIG_SPEC = dict(
        plugin.Plugin.CONFIG_SPEC,
        debug='boolean(default=False)',
        pickler='string(default="nagare.sessions.common:Pickler")',
        unpickler='string(default="nagare.sessions.common:Unpickler")',
        serializer='string(default="nagare.sessions.serializer:Dummy")',
        compressor='string(default="nagare.sessions.common:ZLibCompressor")',
        min_compress_len='integer(default=0)',
    )

    def __init__(
        self,
        name,
        dist,
        debug=False,
        pickler=Pickler,
        unpickler=Unpickler,
        serializer=serializer.Dummy,
        compressor=ZLibCompressor,
        min_compress_len=0,
        publisher_service=None,
        **config,
    ):
        """Initialization.

        In:
          - ``serializer`` -- serializer / deserializer of the states
          - ``pickler`` -- pickler used by the serializer
          - ``unpickler`` -- unpickler used by the serializer
        """
        super(Sessions, self).__init__(
            name,
            dist,
            debug=debug,
            pickler=pickler,
            unpickler=unpickler,
            serializer=serializer,
            compressor=compressor,
            min_compress_len=min_compress_len,
            **config,
        )

        publisher = publisher_service.service
        self.check_concurrence(publisher.has_multi_processes, publisher.has_multi_threads)

        pickler = reference.load_object(pickler)[0] if isinstance(pickler, str) else pickler
        unpickler = reference.load_object(unpickler)[0] if isinstance(unpickler, str) else unpickler
        serializer = reference.load_object(serializer)[0] if isinstance(serializer, str) else serializer
        self.serializer = serializer(pickler, unpickler, debug, self.logger)
        self.debug = debug
        self.compressor = reference.load_object(compressor)[0] if isinstance(compressor, str) else compressor
        self.min_compress_len = min_compress_len

    @staticmethod
    def generate_id():
        return random.randint(1000000000000000, 9999999999999999)

    def handle_start(self, app):
        pass

    def handle_reload(self):
        pass

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
        """Create a new session.

        Return:
          - id of the session
          - id of the state
          - secure token associated to the session
          - session lock
        """
        return self._create(self.generate_session_id(), secure_token or self.generate_secure_token())

    def fetch(self, session_id, state_id):
        """Retrieve the objects graph of a state.

        In:
          - ``session_id`` -- session id of this state
          - ``state_id`` -- id of this state

        Return:
          - id of the latest state
          - secure number associated to the session
          - objects graph
        """
        self.logger.debug('fetching session {} - state {}'.format(session_id, state_id))
        new_state_id, secure_token, session_data, state_data = self._fetch(session_id, state_id)
        return (new_state_id, secure_token, self.serializer.loads(session_data, self.compressor.decompress(state_data)))

    def store(self, session_id, state_id, secure_token, use_same_state, data):
        """Store the state.

        In:
          - ``session_id`` -- session id of this state
          - ``state_id`` -- id of this state
          - ``secure_id`` -- the secure number associated to the session
          - ``use_same_state`` -- is a copy of this state to be created?
          - ``data`` -- the objects graph
        """
        self.logger.debug('storing session %s - state %s', session_id, state_id)

        session_data, state_data = self.serializer.dumps(data, not use_same_state)
        state_data_len = len(state_data)
        if self.min_compress_len and state_data_len > self.min_compress_len:
            state_data = self.compressor.compress(state_data)
            if self.debug:
                self.logger.debug(
                    '%d -> %d state bytes (compression %d%%) for session %s - state %s',
                    state_data_len,
                    len(state_data),
                    100 - (len(state_data) * 100 // state_data_len),
                    session_id,
                    state_id,
                )

        self._store(session_id, state_id, secure_token, use_same_state, session_data, state_data)

    # -------------------------------------------------------------------------

    def check_concurrence(self, multi_processes, multi_threads):
        raise NotImplementedError()

    @staticmethod
    def check_session_id(session_id):
        """Test if a session exist.

        In:
          - ``session_id`` -- id of a session

        Return:
          - is ``session_id`` the id of an existing session?
        """
        raise NotImplementedError()

    def create_lock(self, session_id):
        """Create a new lock for a session.

        In:
          - ``session_id`` -- session id

        Return:
          - the lock
        """
        raise NotImplementedError()

    def get_lock(self, session_id):
        """Retrieve the lock of a session.

        In:
          - ``session_id`` -- session id

        Return:
          - the lock
        """
        raise NotImplementedError()

    def _create(self, session_id, secure_id):
        """Create a new session.

        In:
          - ``session_id`` -- id of the session
          - ``secure_id`` -- the secure number associated to the session
          - ``lock`` -- the lock of the session
        """
        raise NotImplementedError()

    def delete(self, session_id):
        """Delete a session.

        In:
          - ``session_id`` -- id of the session to delete
        """
        raise NotImplementedError()

    def _fetch(self, session_id, state_id):
        """Retrieve a state with its associated objects graph.

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
        """Store a state and its associated objects graph.

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
        type='string(default="memory", help="name of the session entry-point, registered under [nagare.sessions]")',
    )
    LOAD_PRIORITY = 90

    @property
    def DESC(self):
        return 'Proxy to the <%s> sessions manager' % self.selector

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
