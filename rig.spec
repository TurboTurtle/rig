Summary: Monitor a system for events and trigger specific actions
Name: rig
Version: 0.0.1
Release: 1
Source0: http://people.redhat.com/jhunsake/rig/%{name}-%{version}.tar.gz
License: GPLv2
BuildArch: noarch
Requires: python3

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
%py3_install

%check
%{__python3} setup.py test

%files
%{_bindir}/rig

%{python3_sitelib}/*

%license LICENSE

%changelog
* Mon Jan 14 2019 Jake Hunsaker <jhunsake@redhat.com> - 0.0.1-1
- Initial build
