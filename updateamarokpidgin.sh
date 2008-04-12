#!/bin/bash

if [ ! -f pkgamarokpidgin.sh ]; then
    echo "Please be in the AmarokPidgin Directory"
    exit 1
fi

cat AmarokPidgin.py | sed 's/^DEBUG.*$/DEBUG = True/' > ~/.kde/share/apps/amarok/scripts/AmarokPidgin/AmarokPidgin.py
dcop amarok script stopScript AmarokPidgin
dcop amarok script runScript AmarokPidgin
