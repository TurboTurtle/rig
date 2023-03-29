# Copyright (C) 2023 Red Hat, Inc., Jake Hunsaker <jhunsake@redhat.com>
#
# This file is part of the rig project: https://github.com/TurboTurtle/rig
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# version 2 of the GNU General Public License.
#
# See the LICENSE file in the source distribution for further information.


import ast
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
from rigging.exceptions import (DBusServiceExistsError,
                                DBusServiceDoesntExistError,
                                DBusMethodDoesntExistError)


class RigDBusMessage:
    result = None
    success = None

    def __init__(self, result=None, success=None):
        self.result = result
        self.success = success

    def serialize(self):
        return {
            'result': str(self.result),
            'success': str(self.success),
        }


class RigDBusCommand:
    name = None

    def __init__(self, command_name):
        self.name = command_name


class RigDBusConnection:
    """
    Used to abstract communication with an existing rig over the dbus
    service created by that particular rig.
    """
    def __init__(self, rig_name):
        """
        :param rig_name: The name of the rig, which correlates to the name
        of the service exported via DBus.
        """
        self.name = rig_name

        # TODO: Check/handle errors
        self._bus = dbus.SessionBus()

        try:
            self._rig = self._bus.get_object(
                        f"com.redhat.Rig.{rig_name}", "/RigControl")
        except dbus.exceptions.DBusException as exc:
            if exc.get_dbus_name() == \
                    "org.freedesktop.DBus.Error.ServiceUnknown":
                raise DBusServiceDoesntExistError(rig_name)
            raise exc

    def _communicate(self, command):
        """
        Send a rig an instruction and then return the result directly to the
        calling command for further handling

        :param command: The command to have the rig perform
        :return: The result of the command
        """
        method = getattr(self._rig, command.name)

        try:
            ret = method(dbus_interface="com.redhat.RigInterface")

            # there is some fragility in the dbus native type subclasses it
            # seems, so try to convert literally, otherwise take the raw value
            # doing this ensures we return a proper message object, whose
            # result attr matches the type of the response (string, dict..)
            try:
                result = ast.literal_eval(ret['result'])
            except Exception:
                result = ret['result']
            try:
                success = ast.literal_eval(ret['success'])
            except Exception:
                success = ret['success']
            return RigDBusMessage(result=result, success=success)

        except dbus.exceptions.DBusException as exc:
            if exc.get_dbus_name() == \
                    "org.freedesktop.DBus.Error.UnknownMethod":
                raise DBusMethodDoesntExistError(f"{command.name}()")
            raise exc

        except Exception as exc:
            print(f"Exception while calling {command} on {self.name}:{exc}")

        return None

    def destroy_rig(self):
        """
        Instruct the rig to self-terminate without triggering any configured
        actions or generating an archive.
        """

        return self._communicate(RigDBusCommand("destroy"))

    def describe(self):
        return self._communicate(RigDBusCommand("describe"))


class RigDBusListener(dbus.service.Object):
    """
    RigDBusListener will:
        - Attach to the DBus session bus.

        - Create a new unique DBus service with the following path format:
            com.redhat.Rig.RIG_NAME

          where RIG_NAME is the name of the rig as defined in the yaml file.

        - Spawn an glib event loop to start receiving DBus messages.

    In order to define new commands:
        - Add a new method to this class and decorate it with
          @dbus.service.method so it's exposed via DBus.

          The method exposed will be available for DBus clients via
          `com.redhat.RigInterface.METHOD_NAME`

        - Once the RigDBusListener instance is created, use
          `map_rig_command()` to bind command names to whatever method
          implements the functionality that must be run when the command is
          called via DBus. See `BaseRig._create_dbus_service()`

        - Whenever a method is called via DBus, the following will happen:

            - RigDBusListener.COMMAND_NAME will receive the request.

            - The RigDBusListener.COMMAND_NAME implementation will look for
              the callback previously defined by accessing `_command_map`
              using the command name as key.

            - The callback will be run, and a RigDBusMessage will be
              sent back to the client as feedback.


    Additional notes:
        Ideally a single, generic, catch-all DBus method should be
        implemented here, however the python-dbus library doesn't seem to
        permit exposing methods to the bus dynamically, hence the need to
        define a new method, decorated with `dbus.service.method` for any
        new command to be exposed via DBus.
    """

    _command_map = None

    def __init__(self, rig_name, logger):
        self._command_map = {}
        self.logger = logger

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._bus = dbus.SessionBus()
        bus_path = f"com.redhat.Rig.{rig_name}"
        if bus_path in self._bus.list_names():
            raise DBusServiceExistsError(bus_path)
        self._bus_name = dbus.service.BusName(
                            f"com.redhat.Rig.{rig_name}", self._bus,
                            allow_replacement=False, replace_existing=False)
        self._loop = GLib.MainLoop()
        super().__init__(self._bus, "/RigControl")

    def map_rig_command(self, command_name, callback):
        self._command_map[command_name] = callback

    def run_listener(self):
        self._loop.run()

    def _get_mapped_method(self, name, err_callback):
        """
        Try to find and return a mapped rig method based on a given method
        name. If none is found, raise an exception.

        :param name: The name that the mapped method was mapped to
        :param err_callback: The callback used by DBus to report an error

        :return: The method mapped from the rig
        """
        try:
            _func = self._command_map[name]
            if not _func:
                msg = RigDBusMessage(
                        f"Command '{name}' defined but not implemented", False)
                err_callback(msg.serialize())
            else:
                return _func
        except Exception:
            msg = RigDBusMessage(f"Command '{name}' not defined by rig", False)
            err_callback(msg.serialize())
        raise KeyError(f"No command '{name}' available")

    @dbus.service.method("com.redhat.RigInterface",
                         in_signature='', out_signature='a{ss}',
                         async_callbacks=('ok', 'err'))
    def destroy(self, ok, err):
        try:
            _func = self._command_map["destroy"]
            if not _func:
                err(RigDBusMessage("Command `destroy` not implemented.",
                    False).serialize())

            self.logger.info("Destroying rig")

            # this callback is expected to terminate the process, so we need
            # to send feedback to the client before the function is called.
            # Using async_callbacks for this, as otherwise the result would
            # need to be returned from this method, and that will never
            # happen if _func() performs thread cleanup and finishes the
            # process.
            ok(RigDBusMessage("destroyed.", True).serialize())
            _func()

        except KeyError:
            self.logger.error("Command `destroy` is not defined.")
            err(DBusMethodDoesntExistError("destroy"))
        except Exception as exc:
            self.logger.error(f"Error when trying to destroy rig: {exc}")
            err(exc)

    @dbus.service.method('com.redhat.RigInterface', in_signature='',
                         out_signature='a{ss}', async_callbacks=('ok', 'err'))
    def describe(self, ok, err):
        """
        Get a short description of the rig in its current state

        :return: dict
        """
        try:
            _func = self._get_mapped_method('describe', err)
            _info = _func()
            ok(RigDBusMessage(_info, True).serialize())
        except Exception as error:
            msg = f"Could not get description: {error}"
            self.logger.error(msg)
            err(Exception(msg))
