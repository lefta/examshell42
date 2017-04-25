#!/bin/bash

die()
{
	if [[ $# -ge 1 ]]
	then
		echo $1 1>&2
	fi
	exit -1
}

EXAM_VENV=/usr/local/share/examshell/venv

if [ "$(id -u)" != "0" ]; then
   echo "This script must be run as root" 1>&2
   exit 1
fi

echo "> Creation of the virtual python environment"
python2 -m virtualenv --download $EXAM_VENV || die "Failed. Make sure Python 2 and the virtualenv module are installed"

echo "> Installation of dependencies"
source $EXAM_VENV/bin/activate
pip install -r requirements.txt || die "Failed."
deactivate

echo "> Installation of the exam shell"
cp -R packages/examshell-1.1.2-py2.7.egg $EXAM_VENV/lib/python2.7/site-packages
cp bin/examshell-cli.py $EXAM_VENV/bin

echo "> Installation of the run script"
cp bin/examshell /usr/local/bin/examshell || die "Failed."

echo ">> Examshell have been installed to /usr/local. Make sure /usr/local/bin is in your PATH, then run the command \`examshell\`"

