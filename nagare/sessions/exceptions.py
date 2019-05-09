# --
# Copyright (c) 2008-2019 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --


class SessionError(LookupError):
    pass


class ExpirationError(SessionError):
    """Raised when a session or a state id is no longer valid
    """
    pass


class SessionSecurityError(SessionError):
    """Raised when the secure id of a session is not valid
    """
    pass


class StateError(SessionError):
    """Raise when a state can't be deserialized
    '"""
    pass
