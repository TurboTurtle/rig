import dbus

from rigging.commands import RigCmd


class ListCmd(RigCmd):

    def execute(self):
        bus = dbus.SessionBus()
        for service_name in bus.list_names():
            if service_name.startswith("com.redhat.Rig."):
                rig_id = service_name.split(".")[-1]
                print(rig_id)
