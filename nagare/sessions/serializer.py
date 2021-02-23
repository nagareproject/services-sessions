# --
# Copyright (c) 2008-2021 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import sys

try:
    import copy_reg as copyreg
except ImportError:
    import copyreg

try:
    from cStringIO import StringIO as BuffIO
except ImportError:
    from io import BytesIO as BuffIO

from .exceptions import StateError


PY2 = (sys.version_info.major == 2)


class DummyFile(object):
    """A write-only file that does nothing"""
    def write(self, data):
        pass


class Result(object):
    def __init__(self):
        self.session_data = {}
        self.tasklets = set()
        self.callbacks = {}
        self.components = 0


class Dummy(object):
    def __init__(self, pickler, unpickler, debug, logger):
        """Initialization

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
        """Serialize an objects graph

        In:
          - ``pickler`` -- pickler to use
          - ``data`` -- the objects graph
          - ``clean_callbacks`` -- do we have to forget the old callbacks?

        Out:
          - data to keep into the session
          - data to keep into the state
        """
        result = Result()

        # Serialize the objects graph and extract all the callbacks
        def persistent_id(o):
            return self.persistent_id(o, clean_callbacks, result)

        if PY2:
            if self.persistent_id:
                pickler.inst_persistent_id = persistent_id
        else:
            if self.persistent_id:
                pickler.persistent_id = persistent_id

            dispatch_table = copyreg.dispatch_table.copy()
            dispatch_table.update(self.dispatch_table(clean_callbacks, result))
            pickler.dispatch_table = dispatch_table

        pickler.dump(data)

        return result.session_data, result.components, result.callbacks, result.tasklets

    def dumps(self, data, clean_callbacks):
        """Serialize an objects graph

        In:
          - ``data`` -- the objects graph
          - ``clean_callbacks`` -- do we have to forget the old callbacks?

        Out:
          - data kept into the session
          - data kept into the state
        """
        pickler = self.pickler(DummyFile(), protocol=-1)
        session_data, components, callbacks, tasklets = self._dumps(pickler, data, clean_callbacks)

        # This dummy serializer returns the data untouched
        return None, (data, callbacks)

    def loads(self, session_data, state_data):
        """Deserialize an objects graph

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
        """Serialize an objects graph

        In:
          - ``data`` -- the objects graph
          - ``clean_callbacks`` -- do we have to forget the old callbacks?

        Out:
          - data kept into the session
          - data kept into the state
        """
        f = BuffIO()
        pickler = self.pickler(f, protocol=-1)

        # Pickle the data
        session_data, components, callbacks, tasklets = self._dumps(pickler, data, clean_callbacks)

        # Pickle the callbacks
        if PY2:
            pickler.inst_persistent_id = lambda o: None
        else:
            pickler.persistent_id = lambda o: None
        pickler.dump(callbacks)

        # Kill all the blocked tasklets, which are now serialized
        for t in tasklets:
            t.kill()

        # The pickled data are returned
        state_data = f.getvalue()

        f = BuffIO()
        self.pickler(f, protocol=-1).dump(session_data)
        session_data = f.getvalue()

        if self.debug:
            if components:
                self.logger.debug(
                    '%d tasklets - %d components - %d callbacks - %d session bytes - %d state bytes',
                    len(tasklets), components, len(callbacks), len(session_data), len(state_data)
                )
            else:
                self.logger.debug('%d state bytes', len(state_data))

        return session_data, state_data

    def loads(self, session_data, state_data):
        """Deserialize an objects graph

        In:
          - ``session_data`` -- data from the session
          - ``state_data`` -- data from the state

        Out:
          - the objects graph
          - the callbacks
        """
        p = self.unpickler(BuffIO(state_data))
        if session_data:
            session_data = self.unpickler(BuffIO(session_data)).load()
            p.persistent_load = lambda i: session_data.get(int(i))

        try:
            return p.load(), p.load()
        except Exception as e:
            raise StateError(e.args[0])
