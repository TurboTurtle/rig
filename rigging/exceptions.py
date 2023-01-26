# Copyright (C) 2019 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>

# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.


class CreateSocketError(Exception):
    """
    Raised when there is an issue with creating or using the rig's uds socket
    """

    def __init__(self, addr=''):
        message = "Cannot create socket %s" % addr
        super(CreateSocketError, self).__init__(message)


class BindSocketError(Exception):
    """
    Raised when the socket exists, but we cannot communicate with it
    """

    def __init__(self):
        message = "Cannot communicate with rig"
        super(BindSocketError, self).__init__(message)


class MissingSocketError(Exception):
    """
    Raised when the socket we attempted to use does not exist
    """

    def __init__(self, addr=''):
        message = "Socket %s does not exist" % addr
        super(MissingSocketError, self).__init__(message)


class SocketExistsError(Exception):
    """
    Raised when we try to create a socket that already exists
    """

    def __init__(self, addr=''):
        message = "Socket %s already exists on filesystem" % addr
        super(SocketExistsError, self).__init__(message)


class CannotConfigureRigError(Exception):
    """
    Raised when a rig fails to set itself up properly.
    """

    def __init__(self, msg=''):
        message = "Rig setup failed: %s" % msg
        super(CannotConfigureRigError, self).__init__(message)


class DestroyRig(Exception):
    """
    Raised when we intentionally destroy a rig, so we can trap the exit of the
    thread pool
    """

    def __init__(self, msg=''):
        message = f"Destroy called on rig: {msg}"
        super(DestroyRig, self).__init__(message)


__all__ = [
    'BindSocketError',
    'CannotConfigureRigError',
    'CreateSocketError',
    'DestroyRig',
    'MissingSocketError',
    'SocketExistsError'
]
