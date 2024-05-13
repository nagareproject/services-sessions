# Encoding: utf-8

# --
# Copyright (c) 2008-2024 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

from nagare import local


def get_session():
    return getattr(local.worker, 'nagare_session', None)


def set_session(session):
    local.worker.nagare_session = session
