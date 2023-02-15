import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
from rigging.exceptions import DestroyRig
from rigging.connection import RigConnection

class RigDBusConnection(RigConnection):
    def __init__(self, rig_name):
        self.name = rig_name

        self._bus = dbus.SessionBus()
        self._rig = self._bus.get_object(
                        f"com.redhat.Rig.{rig_name}", f"/RigControl")


    def _create_instruction(self, instruction):
        return instruction.capitalize()

    def _communicate(self, command):
        method = getattr(self._rig, command)
        if method is None:
            pass # TODO: raise InvalidMethod?

        try:
            ret = method(dbus_interface="com.redhat.RigInterface")
            result = ret.get("result")
            success = ret.get("success")

            print(f"{command}() result {result} success {success}")
        except Exception as exc:
            print(f"Exception caught while calling {command} on {self.name}:{exc}")


class RigDBusListener(dbus.service.Object):

    def __init__(self, rig_name, *args, **kwargs):
        self.name = rig_name

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._bus = dbus.SessionBus()
        self._bus_name = dbus.service.BusName(
                            f"com.redhat.Rig.{rig_name}", self._bus)
        #print("Bus created", self._bus_name)
        self._loop = GLib.MainLoop()
        super().__init__(self._bus, f"/RigControl", *args, **kwargs)

    def run_listener(self):
        self._loop.run()

    @dbus.service.method("com.redhat.RigInterface",
                        in_signature='', out_signature='a{ss}')
    def destroy(self):
        print("Destroying rig")
        # TODO: set variable or run callback
        return {
            "result": "destroyed",
            "success": "true",
        }

if __name__ == '__main__':
    import sys
    import os
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--connect", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("-n", "--name")
    parser.add_argument("-c", "--command", choices=["destroy"])

    args = parser.parse_args()

    if (args.listen or args.connect) and not args.name:
        print("`--name` is required when listening or connecting")
        os.exit()

    if args.listen:
        print(f"Listening as `{args.name}`")
        l = RigDBusListener(args.name)
        l.run_listener()

    elif args.connect:
        conn = RigDBusConnection(args.name)
        if args.command:
            if args.command == "destroy":
                conn.destroy_rig()
            else:
                print(f"Unknown command `{args.command}`")
        else:
            print("No `--command` specified")

    elif args.list:
        bus = dbus.SessionBus()
        for service_name in bus.list_names():
            if service_name.startswith("com.redhat.Rig."):
                rig_name = service_name.split(".")[-1]
                print(f'· {rig_name} ({str(service_name)})')

    else:
        print("Nothing to do. Hint: use --listen or --connect (or --help)")
