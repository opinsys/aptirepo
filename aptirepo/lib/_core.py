# aptirepo - Simple APT Repository Tool
# Copyright (C) 2013 Tuomas Räsänen
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

from __future__ import print_function

import datetime
import errno
import fcntl
import gzip
import hashlib
import os
import os.path
import shutil
import signal
import subprocess

import debian.debfile

from ._dcf import parse_distributions

from ._error import Error

class ChangesError(Error):
    pass

class PoolError(Error):
    pass

def _gz(filepath_in):
    filepath_out = "%s.gz" % filepath_in
    with open(filepath_in, "rb") as f_in:
        with gzip.open(filepath_out, "wb") as f_out:
            f_out.writelines(f_in)
    return filepath_out

def _md5sum(filepath, block_size=4096):
    md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        data = f.read(block_size)
        while data:
            md5.update(data)
            data = f.read(block_size)
    return md5.hexdigest()

def _abbrev(source_name):
    if source_name.startswith("lib"):
        return "lib"
    return source_name[0]

class Aptirepo:
    """Class representing Aptirepo repository directory tree.

    >>> repo = Aptirepo("/srv/repo")
    >>> repo.import_changes("/var/cache/pbuilder/results/sl_3.03-17_i386.changes")
    """

    def __init__(self, rootdir, confdir="", timeout_secs=0):
        self.__rootdir = os.path.abspath(rootdir)
        self.__confdir = confdir
        if not self.__confdir:
            self.__confdir = self.__join("conf")

        if timeout_secs == 0:
            # No timeout, fail if the lock cannot be obtained right
            # away.
            self.__lockfile = open(self.__join("lock"), "w")
            fcntl.lockf(self.__lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif timeout_secs < 0:
            # Infinite timeout, block until the lock is obtained.
            self.__lockfile = open(self.__join("lock"), "w")
            fcntl.lockf(self.__lockfile, fcntl.LOCK_EX)
        else:
            # Block until the lock is obtained or timeout_secs has
            # passed.
            orig_sigalrm_handler = signal.signal(signal.SIGALRM, lambda *_ : None)
            try:
                signal.alarm(timeout_secs)
                self.__lockfile = open(self.__join("lock"), "w")
                fcntl.lockf(self.__lockfile, fcntl.LOCK_EX)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, orig_sigalrm_handler)

        self.__logfile = open(self.__join("log"), "a")
        self.__dists = parse_distributions(self.__confdir)
        self.__create_pool()
        self.__create_dists()

    def __log(self, msg):
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%m:%S.%fZ")
        print("%s  %s" % (ts, msg), file=self.__logfile)

    def __create_dists(self):
        for codename, dist in self.__dists.items():
            for comp in dist["Components"]:
                for arch in dist["Architectures"]:
                    archdir = "binary-%s" % arch
                    if arch == "source":
                        archdir = "source"
                    p = self.__join("dists", codename, comp, archdir)
                    try:
                        os.makedirs(p)
                    except OSError as e:
                        if e.errno != errno.EEXIST:
                            raise e
                    else:
                        self.__log("created directory '%s'" % p)

    def __create_pool(self):
        for codename, dist in self.__dists.items():
            for comp in dist["Components"]:
                p = self.__join(dist["Pool"], comp)
                try:
                    os.makedirs(p)
                except OSError  as e:
                    if e.errno != errno.EEXIST:
                        raise e
                else:
                    self.__log("created directory '%s'" % p)

    def __join(self, *args):
        return os.path.join(self.__rootdir, *args)

    def __write_contents(self, pool, codename, comp):
        path = self.__join("dists", codename, comp, "Contents.gz")
        with gzip.open(path, 'wb') as f:
            subprocess.check_call(["apt-ftparchive", "--db", "db",
                                   "contents", os.path.join(pool, comp)],
                                  stdout=f, cwd=self.__rootdir)
            self.__log("wrote '%s'" % path)

    def __write_packages(self, pool, codename, comp, arch):
        path = self.__join("dists", codename, comp, "binary-%s" % arch,
                           "Packages")
        with open(path, "w") as f:
            subprocess.check_call(["apt-ftparchive", "--db", "db",
                                   "packages", os.path.join(pool, comp)],
                                  stdout=f, cwd=self.__rootdir)
            self.__log("wrote '%s'" % path)
        pathgz =_gz(path)
        self.__log("wrote '%s'" % pathgz)

    def __write_release(self, codename, comps, archs):
        path = self.__join("dists", codename, "Release")
        with open(path, "w") as f:
            subprocess.check_call(["apt-ftparchive", "--db", "db",
                                   "-o", "APT::FTPArchive::Release::Codename=%s" % codename,
                                   "-o", "APT::FTPArchive::Release::Components=%s" % " ".join(comps),
                                   "-o", "APT::FTPArchive::Release::Architectures=%s" % " ".join(archs),
                                   "release", os.path.join("dists", codename)],
                                  stdout=f, cwd=self.__rootdir)
            self.__log("wrote '%s'" % path)

    def __write_sources(self, pool, codename, comp):
        path = self.__join("dists", codename, comp, "source", "Sources")
        with open(path, "w") as f:
            subprocess.check_call(["apt-ftparchive",
                                   "sources", os.path.join(pool, comp)],
                                  stdout=f, cwd=self.__rootdir)
            self.__log("wrote '%s'" % path)
        pathgz = _gz(path)
        self.__log("wrote '%s'" % pathgz)

    def __copy_to_pool(self, filepath, codename, source_name, section):
        dist = self.__dists[codename]
        filename = os.path.basename(filepath)

        component, sep, section = section.partition("/")
        if not sep:
            component="main"

        abbrevdir = self.__join(dist["Pool"], component, _abbrev(source_name))
        try:
            os.mkdir(abbrevdir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise e

        packagedir = os.path.join(abbrevdir, source_name)
        try:
            os.mkdir(packagedir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise e

        target_filepath = os.path.join(packagedir, filename)
        if os.path.exists(target_filepath):
            if _md5sum(target_filepath) != _md5sum(filepath):
                raise PoolError("'%s' already exists in the repository with different checksum" % filename)
            return

        shutil.copyfile(filepath, target_filepath)
        self.__log("copied '%s' to '%s'" % (filepath, target_filepath))

    def import_deb(self, deb_filepath, codename="", section=""):
        debfile = debian.debfile.DebFile(deb_filepath)
        debcontrol = debfile.debcontrol()
        # Handle changelog inside try-except since it can fail multiple
        # ways: some packages (at least google-earth-stable) seems to
        # have compressed their data-parts with lzma, which
        # python-debian cannot handle. Asking for a changelog for such a
        # package causes debian.debfile.DebError to be raised.  On the
        # other hand, some packages do not have changelog at all. In
        # those cases DebFile.changelog() returns None in which case
        # AttributeError is raised.
        try:
            changelog = debfile.changelog()
            source_name = changelog.package
            if not codename:
                codename = changelog.distributions
        except Exception:
            # If the changelog cannot be found, use the binary package
            # name as its source package name.
            source_name = debcontrol["Package"]
        if not section:
            section = debcontrol["Section"]
        self.__copy_to_pool(deb_filepath, codename, source_name, section)

    def import_changes(self, changes_filepath, codename=""):
        with open(changes_filepath) as changes_file:
            changes = debian.deb822.Changes(changes_file)

        if not codename:
            codename = changes["Distribution"]
        source_name = changes["Source"]
        changes_dirpath = os.path.dirname(changes_filepath)
        for f in changes["Files"]:
            md5 = f["md5sum"]
            section = f["section"]
            filename = f["name"]
            filepath = os.path.join(changes_dirpath, filename)
            real_md5 = _md5sum(filepath)

            if md5 != real_md5:
                raise ChangesError("md5 checksum mismatch '%s': '%s' != '%s'" % (filename, md5, real_md5))

            self.__copy_to_pool(filepath, codename, source_name, section)

    def update_dists(self, do_prune=False):
        if do_prune:
            shutil.rmtree(self.__join("dists"))
            self.__create_dists()
        for codename, dist in self.__dists.items():
            pool = dist["Pool"]
            comps = dist["Components"]
            archs = dist["Architectures"]
            for comp in comps:
                self.__write_contents(pool, codename, comp)
                for arch in archs:
                    if arch == "source":
                        self.__write_sources(pool, codename, comp)
                    else:
                        self.__write_packages(pool, codename, comp, arch)
            self.__write_release(codename, comps, archs)

    def sign_releases(self):
        for codename in self.__dists:
            release_path = self.__join("dists", codename, "Release")
            signature_path = release_path + ".gpg"
            with open(signature_path, "w") as signature_file:
                subprocess.check_call(["gpg", "--output", "-", "-a", "-b", release_path],
                                      stdout=signature_file, cwd=self.__rootdir)
                self.__log("signed '%s'" % release_path)
