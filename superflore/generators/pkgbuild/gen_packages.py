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

import glob
import os

from rosdistro.dependency_walker import DependencyWalker
from rosdistro.manifest_provider import get_release_tag
from rosdistro.rosdistro import RosPackage
from rosinstall_generator.distro import _generate_rosinstall
from rosinstall_generator.distro import get_package_names
from superflore.exceptions import UnresolvedDependency
from superflore.generators.pkgbuild.pkgbuild import PkgBuild
from superflore.PackageMetadata import PackageMetadata
from superflore.utils import err
from superflore.utils import get_distros
from superflore.utils import get_pkg_version
from superflore.utils import make_dir
from superflore.utils import ok
from superflore.utils import retry_on_exception
from superflore.utils import warn

# TODO(allenh1): This is a blacklist of things that
# do not yet support Python 3. This will be updated
# on an as-needed basis until a better solution is
# found (CI?).

no_python3 = ['tf']

org = "Open Source Robotics Foundation"
org_license = "BSD"


def regenerate_pkg(overlay, pkg, distro, preserve_existing=False):
    version = get_pkg_version(distro, pkg)
    pkgbuild_name =\
        '/ros-{0}/{1}/{1}.pkgbuild'.format(distro.name, pkg)
    pkgbuild_name = overlay.repo.repo_dir + pkgbuild_name
    patch_path = '/ros-{}/{}/files'.format(distro.name, pkg)
    patch_path = overlay.repo.repo_dir + patch_path
    is_ros2 = get_distros()[distro.name]['distribution_type'] == 'ros2'
    has_patches = os.path.exists(patch_path)
    pkg_names = get_package_names(distro)[0]
    patches = None
    if os.path.exists(patch_path):
        patches = [
            f for f in glob.glob('%s/*.patch' % patch_path)
        ]
    if pkg not in pkg_names:
        raise RuntimeError("Unknown package '%s'" % (pkg))
    # otherwise, remove a (potentially) existing pkgbuild.
    prefix = '{0}/ros-{1}/{2}/'.format(overlay.repo.repo_dir, distro.name, pkg)
    existing = glob.glob('%s*.pkgbuild' % prefix)
    previous_version = None
    if preserve_existing and os.path.isfile(pkgbuild_name):
        ok("pkgbuild for package '%s' up to date, skipping..." % pkg)
        return None, [], None
    elif existing:
        overlay.repo.remove_file(existing[0])
        previous_version = existing[0].lstrip(prefix).rstrip('.pkgbuild')
        manifest_file = '{0}/ros-{1}/{2}/Manifest'.format(
            overlay.repo.repo_dir, distro.name, pkg
        )
        overlay.repo.remove_file(manifest_file)
    try:
        current = arch_pkgbuild(distro, pkg, has_patches)
        current.pkgbuild.name = pkg
        current.pkgbuild.version = version
        current.pkgbuild.patches = patches
        current.pkgbuild.is_ros2 = is_ros2
    except Exception as e:
        err('Failed to generate pkgbuild for package {}!'.format(pkg))
        raise e
    try:
        pkgbuild_text = current.pkgbuild_text()
    except UnresolvedDependency:
        dep_err = 'Failed to resolve required dependencies for'
        err("{0} package {1}!".format(dep_err, pkg))
        unresolved = current.pkgbuild.get_unresolved()
        for dep in unresolved:
            err(" unresolved: \"{}\"".format(dep))
        return None, current.pkgbuild.get_unresolved(), None
    except KeyError as ke:
        err("Failed to parse data for package {}!".format(pkg))
        raise ke
    make_dir(
        "{}/ros-{}/{}".format(overlay.repo.repo_dir, distro.name, pkg)
    )
    success_msg = 'Successfully generated pkgbuild for package'
    ok('{0} \'{1}\'.'.format(success_msg, pkg))

    try:
        pkgbuild_file = '{0}/ros-{1}/{2}/PKGBUILD'.format(
            overlay.repo.repo_dir,
            distro.name, 
            pkg,
        )
        ok(f"writing {pkgbuild_file}")
        with open(pkgbuild_file, "w") as pkgbuild_file_f:
            pkgbuild_file_f.write(pkgbuild_text)
    except Exception as e:
        err(f"Failed to write f{pkgbuild_file} to disk!")
        raise e
    return current, previous_version, pkg



def _gen_pkgbuild_for_package(
    distro, pkg_name, pkg, repo, ros_pkg, pkg_rosinstall
):
    pkg_pkgbuild = PkgBuild()

    pkg_pkgbuild.distro = distro.name
    pkg_pkgbuild.src_uri = pkg_rosinstall[0]['tar']['uri']
    pkg_names = get_package_names(distro)
    pkg_dep_walker = DependencyWalker(distro)

    pkg_buildtool_deps = pkg_dep_walker.get_depends(pkg_name, "buildtool")
    pkg_build_deps = pkg_dep_walker.get_depends(pkg_name, "build")
    pkg_run_deps = pkg_dep_walker.get_depends(pkg_name, "run")
    pkg_test_deps = pkg_dep_walker.get_depends(pkg_name, "test")

    pkg_keywords = ['x86', 'amd64', 'arm', 'arm64']

    # add run dependencies
    for rdep in pkg_run_deps:
        pkg_pkgbuild.add_run_depend(rdep, rdep in pkg_names[0])

    # add build dependencies
    for bdep in pkg_build_deps:
        pkg_pkgbuild.add_build_depend(bdep, bdep in pkg_names[0])

    # add build tool dependencies
    for tdep in pkg_buildtool_deps:
        pkg_pkgbuild.add_build_depend(tdep, tdep in pkg_names[0])

    # add test dependencies
    for test_dep in pkg_test_deps:
        pkg_pkgbuild.add_test_depend(test_dep, test_dep in pkg_names[0])

    # add keywords
    for key in pkg_keywords:
        pkg_pkgbuild.add_keyword(key)

    # parse through package xml
    try:
        pkg_xml = retry_on_exception(ros_pkg.get_package_xml, distro.name)
    except Exception:
        warn("fetch metadata for package {}".format(pkg_name))
        return pkg_pkgbuild
    pkg = PackageMetadata(pkg_xml)
    pkg_pkgbuild.upstream_license = pkg.upstream_license
    pkg_pkgbuild.description = pkg.description
    pkg_pkgbuild.homepage = pkg.homepage
    pkg_pkgbuild.build_type = pkg.build_type
    return pkg_pkgbuild


class arch_pkgbuild(object):
    def __init__(self, distro, pkg_name, has_patches=False):
        pkg = distro.release_packages[pkg_name]
        repo = distro.repositories[pkg.repository_name].release_repository
        ros_pkg = RosPackage(pkg_name, repo)

        pkg_rosinstall =\
            _generate_rosinstall(pkg_name, repo.url,
                                 get_release_tag(repo, pkg_name), True)

        self.pkgbuild =\
            _gen_pkgbuild_for_package(distro, pkg_name,
                                    pkg, repo, ros_pkg, pkg_rosinstall)
        self.pkgbuild.has_patches = has_patches

        if pkg_name in no_python3:
            self.pkgbuild.python_3 = False

    def pkgbuild_text(self):
        return self.pkgbuild.get_pkgbuild_text(org, org_license)
