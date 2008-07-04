#!/bin/bash

if [ ! -f pkgamarokpidgin.sh ]; then
    echo "Please be in the AmarokPidgin Directory"
    exit 1
fi

if grep -i debug.*true AmarokPidgin.py; then
    if [ "$1" != "debug" ]; then
	echo "Switch off debugging!"
	exit 1
    fi
fi

version=$(fgrep ':Version:' README | awk '{ print $2 }')

mkdir AmarokPidgin
rst2html.py README > README.html
cp AmarokPidgin.py AmarokPidgin.spec COPYING README AmarokPidgin
tar cjf AmarokPidgin-$version.amarokscript.tar.bz2 AmarokPidgin

rm -rf AmarokPidgin
