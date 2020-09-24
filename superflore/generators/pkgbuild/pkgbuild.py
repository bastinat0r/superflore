# Copyright 2017 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from time import gmtime, strftime

from superflore.exceptions import UnknownBuildType
from superflore.exceptions import UnresolvedDependency
from superflore.utils import get_license
from superflore.utils import resolve_dep
from superflore.utils import sanitize_string
from superflore.utils import trim_string

# TODO(allenh1): is there a better way to get these?
depend_only_pkgs = [
    'dev-util/gperf',
    'app-doc/doxygen',
    'virtual/pkgconfig'
]


class pkgbuild_keyword(object):
    def __init__(self, arch, stable):
        self.arch = arch
        self.stable = stable

    def to_string(self):
        if self.stable:
            return self.arch
        else:
            return '~{0}'.format(self.arch)

    def __eq__(self, other):
        return self.to_string() == other.to_string()


class PkgBuild(object):
    """
    Basic definition of an pkgbuild file.
    This is where any necessary variables will be filled.
    """
    def __init__(self):
        self.eapi = str(6)
        self.description = ""
        self.homepage = "https://wiki.ros.org"
        self.src_uri = None
        self.upstream_license = ["LGPL-2"]
        self.keys = list()
        self.rdepends = list()
        self.rdepends_external = list()
        self.depends = list()
        self.depends_external = list()
        self.tdepends = list()
        self.tdepends_external = list()
        self.distro = None
        self.cmake_package = True
        self.base_yml = None
        self.version = None
        self.unresolved_deps = list()
        self.name = None
        self.has_patches = False
        self.build_type = 'catkin'
        self.is_ros2 = False
        self.python_3 = True
        self.patches = list()
        self.illegal_desc_chars = '()[]{}|^$\\#\t\n\r\v\f\'"`'

    def add_build_depend(self, depend, internal=True):
        if depend in self.rdepends:
            return
        elif depend in self.rdepends_external:
            return
        elif internal:
            self.depends.append(depend)
        else:
            self.depends_external.append(depend)

    def add_run_depend(self, rdepend, internal=True):
        if rdepend in depend_only_pkgs and not internal:
            self.depends_external.append(rdepend)
        elif internal:
            self.rdepends.append(rdepend)
        else:
            self.rdepends_external.append(rdepend)

    def add_test_depend(self, tdepend, internal=True):
        if not internal:
            self.tdepends_external.append(tdepend)
        else:
            self.tdepends.append(tdepend)

    def add_keyword(self, keyword, stable=False):
        self.keys.append(pkgbuild_keyword(keyword, stable))

    def get_license_line(self, distributor, license_text):
        ret = "# Copyright " + strftime("%Y", gmtime()) + " "
        ret += distributor + "\n"
        ret += "# Distributed under the terms of the " + license_text
        ret += " license\n\n"
        return ret

    def get_eapi_line(self):
        return 'EAPI=%s\n' % self.eapi

    def get_python_compat(self, python_versions):
        ver_string = ''
        if len(python_versions) > 1:
            ver_string = '{' + ','.join(python_versions) + '}'
        else:
            ver_string = python_versions[0]
        return 'PYTHON_COMPAT=( python%s )\n\n' % ver_string

    def get_inherit_line(self):
        # if we are using catkin, we just inherit ros-cmake
        if self.build_type in ['catkin', 'cmake']:
            return 'inherit ros-cmake\n\n'
        elif self.build_type == 'ament_python':
            return 'inherit ament-python\n\n'
        elif self.build_type == 'ament_cmake':
            return 'inherit ament-cmake\n\n'
        else:
            raise UnknownBuildType(self.build_type)

    def get_pkgbuild_text(self, distributor, license_text):
        """
        Generate the pkgbuild in text, given the distributor line
        and the license text.
        """
        # EAPI=<eapi>
        entries = []
        entries.append("# Script generated with superflore")
        entries.append("# Maintainer: Sebastian Mai <sebastian.mai@ovgu.de>")
        self.description =\
            sanitize_string(self.description, self.illegal_desc_chars)
        self.description = trim_string(self.description)

        entries.append(f"pkgname='ros-{self.distro}-{self.name}'")
        entries.append(f'pkgdesc="{self.description}"')
        entries.append(f"url={self.homepage}")
        version_str = self.version.split("-")[0]
        rc = self.version.split("-")[1][1:]
        entries.append(f"pkgver={version_str}")
        entries.append(f"arch=('any')")
        entries.append(f"pkgrel={rc}")
        license_str = [ f"'{ul}'" for ul in self.upstream_license]
        entries.append(f"license=({' '.join(license_str)})")
        entries.append(f"epoch=0")
        entries.append(f"groups=('ros' 'ros-{self.distro}')")
        ros_deps = [f"ros-{self.distro}-{d}" for d in self.depends]
        dependencies = (ros_deps + self.depends_external)
        for i, dep in enumerate(dependencies):
            if dep.startswith("python3"):
                dependencies[i] = dep.replace("python3", "python", 1)
        entries.append(f"makedepends=({' '.join(dependencies)})")
        ros_rdeps = [f"ros-{self.distro}-{d}" for d in self.rdepends] 
        rdependencies = (ros_rdeps + self.rdepends_external)
        for i, dep in enumerate(rdependencies):
            if dep.startswith("python3"):
                rdependencies[i] = dep.replace("python3", "python", 1)
        entries.append(f"depends=({' '.join(rdependencies)})")
        entries.append(f'source=("ros-{self.distro}-{self.name}-{self.version}.tar.gz::{self.src_uri}")')
        entries.append(f"md5sums=('SKIP')")
        entries.append(f"""
build() {{
    cd "${{srcdir}}"
    [ -f /opt/ros/{self.distro}/setup.bash ] && source /opt/ros/{self.distro}/setup.bash
    colcon build
}}
""")

        entries.append(f"""
package() {{
    cd "${{srcdir}}"
    colcon build --install-base "${{pkgdir}}"/opt/ros/{self.distro}
    rm "${{pkgdir}}"/opt/ros/{self.distro}/*setup*
    rm "${{pkgdir}}"/opt/ros/{self.distro}/COLCON_IGNORE
    rm "${{pkgdir}}"/opt/ros/{self.distro}/.colcon_install_layout
    chown -R ros:ros "${{pkgdir}}"/opt/ros/{self.distro}
    chmod -R 777 "${{pkgdir}}"/opt/ros/{self.distro}
}}
""")
        return "\n".join(entries)

    def get_unresolved(self):
        return self.unresolved_deps
 