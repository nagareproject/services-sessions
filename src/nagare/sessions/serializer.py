# --
# Copyright (c) 2014-2026 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import copyreg
from io import BytesIO

from .exceptions import StateError


class DummyFile:
    """A write-only file that does nothing."""

    def write(self, data):
        pass


class Result:
    def __init__(self):
        self.session_data = {}
        self.callbacks = {}
        self.components = 0


class Dummy:
    def __init__(self, pickler, unpickler, debug, logger):
        """Initialization.

        - ``pickler`` -- pickler to use
        - ``unpickler`` -- unpickler to use
        """
        self.pickler = pickler
        self.unpickler = unpickler
        self.debug = debug
        self.logger = logger
        self.persistent_id = None
        self.dispatch_table = lambda *args: {}

    def _dumps(self, pickler, data, clean_callbacks):
        """Serialize an objects graph.

        In:
          - ``pickler`` -- pickler to use
          - ``data`` -- the objects graph
          - ``clean_callbacks`` -- do we have to forget the old callbacks?

        Out:
          - data to keep into the session
          - data to keep into the state
        """
        result = Result()

        if self.persistent_id:
            pickler.persistent_id = lambda o: self.persistent_id(o, clean_callbacks, result)

        pickler.dispatch_table = copyreg.dispatch_table | self.dispatch_table(clean_callbacks, result)

        # Serialize the objects graph and extract all the callbacks
        pickler.dump(data)

        return result.session_data, result.components, result.callbacks

    def dumps(self, data, clean_callbacks):
        """Serialize an objects graph.

        In:
          - ``data`` -- the objects graph
          - ``clean_callbacks`` -- do we have to forget the old callbacks?

        Out:
          - data kept into the session
          - data kept into the state
        """
        pickler = self.pickler(DummyFile(), protocol=-1)
        session_data, components, callbacks = self._dumps(pickler, data, clean_callbacks)

        # This dummy serializer returns the data untouched
        return None, (data, callbacks)

    def loads(self, session_data, state_data):
        """Deserialize an objects graph.

        In:
          - ``session_data`` -- data from the session
          - ``state_data`` -- data from the state

        Out:
          - the objects graph
          - the callbacks
        """
        return state_data


class Pickle(Dummy):
    def dumps(self, data, clean_callbacks):
        """Serialize an objects graph.

        In:
          - ``data`` -- the objects graph
          - ``clean_callbacks`` -- do we have to forget the old callbacks?

        Out:
          - data kept into the session
          - data kept into the state
        """
        f = BytesIO()
        pickler = self.pickler(f, protocol=-1)

        # Pickle the data
        session_data, components, callbacks = self._dumps(pickler, data, clean_callbacks)

        pickler.persistent_id = lambda o: None
        pickler.dump(callbacks)

        # The pickled data are returned
        state_data = f.getvalue()

        f = BytesIO()
        self.pickler(f, protocol=-1).dump(session_data)
        session_data = f.getvalue()

        if self.debug:
            if components:
                self.logger.debug(
                    '%d components - %d callbacks - %d session bytes - %d state bytes',
                    components,
                    len(callbacks),
                    len(session_data),
                    len(state_data),
                )
            else:
                self.logger.debug('%d state bytes', len(state_data))

        return session_data, state_data

    def loads(self, session_data, state_data):
        """Deserialize an objects graph.

        In:
          - ``session_data`` -- data from the session
          - ``state_data`` -- data from the state

        Out:
          - the objects graph
          - the callbacks
        """
        p = self.unpickler(BytesIO(state_data))
        if session_data:
            session_data = self.unpickler(BytesIO(session_data)).load()
            p.persistent_load = lambda i: session_data.get(int(i))

        try:
            return p.load(), p.load()
        except Exception as e:
            raise StateError(repr(e))
