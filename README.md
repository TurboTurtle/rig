# rig
A lightweight, flexible, easy to use system monitoring and event handling utility

# Description
rig is designed to aid system administrators and support engineers in diagnostic data collection for issues that are seemingly
random in their occurrence, or occur at inoportune times for human intervention when collecting data about the event.

# Design
rig operates on a trigger -> reaction stance, which can be referred to as "monitors" or "triggers" and "actions" respectively and
a single instance of rig watching for an event is also known a "a rig". Rigs run as detached processes until either the trigger condition
is met, the user destroys the rig, or the system is rebooted. Rigs do *not* persist through reboots.

In the most basic of terms, rigs are launched to monitor a resource (such as log files, network activity, etc...) and when the trigger
condition specified by the user is met, configured actions are taken.

For example, a system administrator might be investigating an issue where a service is appearing to hang after a specific log message
is recorded and wants to collect a coredump of the process while it is in this hung state for further analysis. They may launch
a rig like the following to do this:

~~~
# rig logs --message "This is my test message" --gcore `pidof myservice`
~~~

The above will create a rig that monitors the system journal (for distributions using journald) _and_ `/var/log/messages` by default
for any new entry that matches the string `This is my test message`. When either the journal or the messages file gets a new entry with
this content, the rig is considered to be "triggered" and the configured actions will be taken. In this case, that action is to use `gcore`
to collect a coredump of the `myservice` process.


# Supported Monitors and Actions

Generally speaking, rig resource monitors are pluggable, as are actions. Rigs will monitor only one resource per rig, but can take 
any number of actions.

To get a list of supported monitors run `rig --help`:

~~~
usage: 
    rig <resource or subcmd> <options>

    <subcmd> may be one of the following:

    list    -   Get a list of current rigs
    destroy -   Destroy a specified rig

    <resource> may be any of the following:
    logs    -   Configure a rig to watch log file(s) and/or journal(s) 
~~~

And for any actions supported for the monitor in question, use `rig <resource> --help`:


~~~
usage: 
    rig logs <options>

    Valid actions:

    sosreport 	 Generate a sosreport when triggered
    gcore        Use gcore to generate a coredump for specified PID(s)
~~~


# Requirements
rig is a **Python 3 only** utility. There is no support for a python-2.x runtime.

Additionally rig **must** be run as the *root* user.
