if [ "$(id -u)" != "0" ]; then
   echo "This script must be run as root" 1>&2
   exit 1
fi

rm -rf /usr/local/share/examshell/venv
rm -f /usr/local/bin/examshell

echo "Examshell have been removed from your computer"
