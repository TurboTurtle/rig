Summary: Monitor a system for events and trigger specific actions
Name: rig
Version: 1.0
Release: 1
Source0: http://people.redhat.com/jhunsake/rig/%{name}-%{version}.tar.gz
License: GPLv2
BuildArch: noarch
Requires: python3
Requires: python3-psutil
Requires: python3-systemd

BuildRequires: python3-devel
BuildRequires: python3-setuptools

%description
Rig is a utility designed to watch or monitor specific system resources (e.g.
log files, journals, system activity, etc...) and then take specific action
when the trigger condition is met. Its primary aim is to assist in troubleshooting
and data collection for randomly occurring events.

%prep
%setup -q

%build
%py3_build

%install
mkdir -p ${RPM_BUILD_ROOT}%{_mandir}/man1
install -p -m644 man/en/rig.1 ${RPM_BUILD_ROOT}%{_mandir}/man1/
%py3_install

%check
%{__python3} setup.py test

%files
%{_bindir}/rig
%{_mandir}/man1/*

%{python3_sitelib}/*

%license LICENSE

%changelog
* Tue Jul 28 2020 Jake Hunsaker <jhunsake@redhat.com> - 1.0-1
- Version 1.0 release
