# --
# Copyright (c) 2008-2020 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --


class SessionError(LookupError):
    pass


class CriticalSessionError(SessionError):
    pass


class LockError(CriticalSessionError):
    """Raised when an exclusive lock on a session can't be acquired
    """
    pass


class StorageError(CriticalSessionError):
    """Raised when the serialized session can't be stored / retreived
    """
    pass


class InvalidSessionError(SessionError):
    pass


class ExpirationError(InvalidSessionError):
    """Raised when a session or a state id is no longer valid
    """
    pass


class SessionSecurityError(InvalidSessionError):
    """Raised when the secure id of a session is not valid
    """
    pass


class StateError(InvalidSessionError):
    """Raise when a state can't be deserialized
    '"""
    pass
