#!/usr/bin/python
# -*- coding: utf-8 -*-

import os.path
from xml.dom.minidom import parse
from setuptools import setup

project_dir = os.path.dirname(os.path.abspath(__file__))
metadata = parse(os.path.join(project_dir, 'addon.xml'))
addon_version = metadata.firstChild.getAttribute('version')

setup(
    name='simplecache',
    version=addon_version,
    url='https://github.com/kodi-community-addons/script.module.simplecache',
    author='sualfred,marcelveldt',
    description='Provides a simple file- and memory based cache for Kodi addons',
    long_description=open(os.path.join(project_dir, 'README.md')).read(),
    keywords='Kodi, plugin, cache',
    license='Apache 2.0',
    package_dir={'': 'lib'},
    py_modules=['simplecache'],
    zip_safe=False,
)