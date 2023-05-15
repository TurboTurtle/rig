import os

from setuptools import setup, find_packages
from rigging import __version__ as VERSION

def get_man_pages(section):
    """Helper to always include all man pages in dist tarball"""
    _dir = 'man/en/'
    return [
        os.path.join(_dir, m) for m in os.listdir(_dir) if m.endswith(section)
    ]

setup(
    name='rig',
    version=VERSION,
    description='Monitor a system for events and trigger specific actions',
    long_description=("Rig is a utility designed to watch or monitor specific "
                      "system resources (e.g. log files, journals, network "
                      "activity, etc...) and then take specific action when "
                      "the trigger condition is met. Its primary aim is to "
                      "assist in troubleshooting and data colelction for "
                      "randomly occurring events."),
    author='Jake Hunsaker',
    author_email='jhunsake@redhat.com',
    license='GPLv2',
    url='https://github.com/TurboTurtle/rig',
    classifiers=[
                'Intended Audience :: System Administrators',
                'Topic :: System :: Systems Administration',
                ('License :: OSI Approved :: GNU General Public License v2 '
                 "(GPLv2)"),
                ],
    packages=find_packages(),
    install_requires=['psutil > 5', 'systemd-python'],
    scripts=['rig'],
    data_files=[
        ('share/licenses/rig', ['LICENSE']),
        ('share/man/man1/', get_man_pages('1')),
        ('share/man/man7/', get_man_pages('7'))
    ])
