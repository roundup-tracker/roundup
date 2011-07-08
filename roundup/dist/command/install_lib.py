from roundup.dist.command.build import build_message_files, check_manifest
from distutils.command.install_lib import install_lib as base

class install_lib(base):

    def run(self):
        check_manifest()
        build_message_files(self)
        base.run(self)
