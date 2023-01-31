# --
# Copyright (c) 2008-2023 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --


class SessionError(LookupError):
    def name(self):
        return self.__class__.__name__


# =================================================================================


class CriticalSessionError(SessionError):
    pass


class LockError(CriticalSessionError):
    """Raised when an exclusive lock on a session can't be acquired."""


class StateError(CriticalSessionError):
    """Raise when a state can't be deserialized."""


class StorageError(CriticalSessionError):
    """Raised when the serialized session can't be stored / retreived."""


# =================================================================================


class InvalidSessionError(SessionError):
    pass


class ExpirationError(InvalidSessionError):
    """Raised when a session or a state id is no longer valid."""


class SessionSecurityError(InvalidSessionError):
    """Raised when the secure id of a session is not valid."""
