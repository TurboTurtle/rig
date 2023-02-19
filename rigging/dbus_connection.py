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

class RigDBusCommand:
    name = None

class RigDBusCommandDestroy(RigDBusCommand):
    name = "destroy"

class RigDBusConnection:
    """
    Used to abstract communication with an existing rig over the dbus
    service created by that particular rig.
    """
    def __init__(self, rig_name):
        """
        :param rig_name: The name of the rig, which correlates to the name
        of the socket
        """
        self.name = rig_name

        # TODO: Check/handle errors
        self._bus = dbus.SessionBus()
        try:
            self._rig = self._bus.get_object(
                        f"com.redhat.Rig.{rig_name}", f"/RigControl")
        except dbus.exceptions.DBusException as exc:
            if exc.get_dbus_name() == "org.freedesktop.DBus.Error.ServiceUnknown":
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
            return RigDBusMessage(**ret)

        except dbus.exceptions.DBusException as exc:
            if exc.get_dbus_name() == "org.freedesktop.DBus.Error.UnknownMethod":
                raise DBusMethodDoesntExistError(f"{command.name}()")
            raise exc

        except Exception as exc:
            print(f"Exception caught while calling {command} on {self.name}:{exc}")

        return None

    def destroy_rig(self):
        """
        Instruct the rig to self-terminate without triggering any configured
        actions or generating an archive.
        """

        return self._communicate(RigDBusCommandDestroy())


class RigDBusListener(dbus.service.Object):

    def __init__(self, rig_name, *args, **kwargs):
        self.name = rig_name

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._bus = dbus.SessionBus()
        bus_path = f"com.redhat.Rig.{rig_name}"
        if bus_path in self._bus.list_names():
            raise DBusServiceExistsError(bus_path)
        self._bus_name = dbus.service.BusName(
                            f"com.redhat.Rig.{rig_name}", self._bus,
                            allow_replacement=False, replace_existing=False)
        self._loop = GLib.MainLoop()
        super().__init__(self._bus, f"/RigControl", *args, **kwargs)

    def run_listener(self):
        self._loop.run()

    @dbus.service.method("com.redhat.RigInterface",
                        in_signature='', out_signature='a{ss}')
    def destroy(self):
        print("Destroying rig")
        # TODO: Actually destroy rig: set variable or run callback 
        # (was raise DestroyRig
        return RigDBusMessage("destroyed", True)
