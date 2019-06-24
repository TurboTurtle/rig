Summary: Monitor a system for events and trigger specific actions
Name: rig
Version: 0.0.3
Release: 1
Source0: http://people.redhat.com/jhunsake/rig/%{name}-%{version}.tar.gz
License: GPLv2
BuildArch: noarch
Requires: python3
Requires: python3-psutil

BuildRequires: python3-devel
BuildRequires: python3-setuptools

%description
Rig is a utility designed to watch or monitor specific system resources (e.g.
log files, journals, network activity, etc...) and then take specific action
when the trigger condition is met. It's primary aim is to assist in troubleshooting
for randomly occurring events.

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
* Mon Jun 24 2019 Jake Hunsaker <jhunsake@redhat.com> - 0.0.3-1
- Alpha 3 build

* Tue Feb 05 2019 Jake Hunsaker <jhunsake@redhat.com> - 0.0.2-1
- Alpha 2 build
- New rig - process
- New actions - noop, gcore, kdump


* Mon Jan 14 2019 Jake Hunsaker <jhunsake@redhat.com> - 0.0.1-1
- Initial build
