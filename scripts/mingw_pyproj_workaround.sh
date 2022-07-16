#!/usr/bin/env bash
mkdir proj_build && cd proj_build &&
git clone https://github.com/pyproj4/pyproj.git . &&
git checkout 3.3.1 &&
python setup.py bdist_wheel
