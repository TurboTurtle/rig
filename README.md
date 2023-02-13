**rig is currently undergoing a major re-write and re-design to v2.**

As such, some functionality may not be present from v1 to v2 and users should familiarize themselves with the
project if they wish to use v2 prior to it being officially packaged in any manner.

# rig
A lightweight, flexible, easy to use system monitoring and event handling utility

# Description
rig is designed to aid system administrators and support engineers in diagnostic data collection for issues that are seemingly
random in their occurrence, or occur at inopportune times for human intervention when collecting data about the event.

# Design
rig operates on an event->reaction model. The specifics of what events trigger what (re)actions are defined in a **rigfile** - that is, a yaml-formatted
file that is parsed by the rig CLI.

Rigs run as detached processes until either the trigger condition is met, the user destroys the rig, or the system is rebooted.

Rigs do *not* persist through reboots.

In the most basic of terms, rigs are launched to monitor a resource (such as log files, network activity, etc...) and when the trigger
condition specified by the user is met, configured actions are taken. Actions are chainable which means sysadmins and support representatives
can orchestrate a large amount of data collection all from the same point in time.

For example, a system administrator might be investigating an issue where a service is appearing to hang after a specific log message
is recorded and wants to collect a coredump of the process while it is in this hung state for further analysis. They may launch
a rig like the following to do this:

~~~
---
# my_rigfile.yaml
name: my_first_rig
monitors:
  logs:
    message: "this is my test message"
actions:
  gcore:
    procs:
      - my_failing_service
...

# rig create -f my_rigfile.yml
~~~

The above will create a rig that monitors the system journal (for distributions using journald) _and_ `/var/log/messages` by default
for any new entry that matches the string `this is my test message`. When either the journal or the messages file gets a new entry with
this content, the rig is considered to be "triggered" and the configured actions will be taken. In this case, that action is to use `gcore`
to collect a coredump of the `my_failing_service` process.


# Supported Monitors and Actions

A rig can watch any number of conditions via the supported `monitors`, and similarly take any number of supported `actions` in response to
the monitored condition being met.

# Deterministic Sequence of Actions

As stated earlier, a rig can have any number of actions chained together in response to an event. The actions will be run _serially_ in order of
the action's priority weight. These weights are set in the action's class, and are currently not user controllable. Because of this priority weighting system
chaining actions together will always result in the same order of execution regardless of the order of the actions in the rigfile.

Care is taken to be sure that these weights are set in a logical manner. Actions that are time-sensitive in the sense that they need to be executed as close to
the time of the triggering event as possible will be run first. Actions that are not as time-sensitive or those that may change system state will be run later or last as appropriate.

For example, the `gcore` action will be fired before any other actions, since a user would likely want the application's core dump to be taken as close to the triggering event
as possible, whereas the `kdump` action will always fire _last_ as this action will reboot the system and prevent further action by rig.

# Requirements
rig is a **Python 3 only** utility. There is no support for a python-2.x runtime. While it may very well work, issues reported for python 2.x will be closed.

Additionally rig **must** be run as the *root* user.

Every attempt to will be made to keep rigs and actions limited to the Python 3 Standard Library, however exceptions to this are inevitable. In such case, rigs and actions
will be restricted to modules that are available for the **RHEL 8 and later** family of distributions.

A current list of all module requirements outside of the Python 3 Standard Library is as followings:

- python3-psutil 5 or newer
- python3-systemd


Note that many actions will call external tools. These are not considered hard requirements as users may very well never use those specific actions.
