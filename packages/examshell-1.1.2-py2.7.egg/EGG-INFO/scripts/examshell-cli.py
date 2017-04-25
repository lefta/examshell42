#!/Users/zaz/Documents/work/exam/prod/shell/build/venv/bin/python
# ===============================================================================
#
# WHY, oh WHY would you read this script? It's way too ugly!
# Just go back to your exam...
# Seriously, just do it.
#
# zaz
# 2015
#
# ===============================================================================

import os
import pwd
import krbV
import socket
import fcntl
import struct
import sys
import time
import cStringIO
import tarfile
import base64
import shutil
import subprocess
import traceback
import string
import json
import requests
import cmd
import urllib3
import datetime
from netaddr import IPAddress, IPNetwork
import strict_rfc3339
urllib3.disable_warnings()
requests.packages.urllib3.disable_warnings()

from termcolor import colored
from attrdict import AttrDict
from requests_kerberos import HTTPKerberosAuth, DISABLED

from examshell.version import __version__


def get_lan_ip():
    """Returns the LAN IP of the current machine, filtering out 127.*
    """
    def get_interface_ip(ifname):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return socket.inet_ntoa(
            fcntl.ioctl(s.fileno(),
                        0x8915,
                        struct.pack('256s',
                                    ifname[:15]
                                    )
                        )[20:24]
        )
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip.startswith("127."):
            interfaces = ["en{0}".format(n) for n in range(4)]
            for ifname in interfaces:
                try:
                    ip = get_interface_ip(ifname)
                    break
                except IOError:
                    pass
        return IPAddress(ip)
    except:
        return None


if os.path.isfile("/etc/exam_master_host"):
    with open("/etc/exam_master_host") as fp:
        HOST_BASE = fp.read().rstrip()
else:
    HOST_BASE = "exam-master.42.fr"

HOST_BASE = "https://{}".format(HOST_BASE)

if pwd.getpwuid(os.getuid())[0] == 'exam':
    REAL_MODE = True
    EXAM_BASEDIR = os.path.expanduser("~/")
    CLEAN_BASEDIR = False
#elif get_lan_ip() in IPNetwork("10.18.250.0/24"):
#    REAL_MODE = True
#    EXAM_BASEDIR = os.path.expanduser("~/exam-basedir")
#    CLEAN_BASEDIR = True
else:
    REAL_MODE = False
    EXAM_BASEDIR = os.path.expanduser("~/exam-basedir")
    CLEAN_BASEDIR = True

if len(sys.argv) > 1:
    print "Running with local server"
    HOST_BASE = "http://localhost:8000"
    EXAM_BASEDIR = os.path.expanduser("~/exam-basedir")
    CLEAN_BASEDIR = True
    REAL_MODE = sys.argv[1] == "-real"

SUBJECTS_DIR = os.path.join(EXAM_BASEDIR, "subjects")
TRACES_DIR = os.path.join(EXAM_BASEDIR, "traces")
GIT_DIR = os.path.join(EXAM_BASEDIR, "rendu")
DOCS_DIR = os.path.join(EXAM_BASEDIR, "docs")


def get_principal():
    ctx = krbV.default_context()
    cc = ctx.default_ccache()
    try:
        princ = cc.principal()
        return princ.name
    except krbV.Krb5Error:
        return None


def check_principal():
    pn = get_principal()
    if pn is None:
        fatal("You do not have a valid Kerberos ticket. Please run \"kinit"
              " <your_login>\" and run \"examshell\" again.")
    elif pn.startswith("exam@"):
        fatal(("Your Kerberos ticket is for \"{}\". You must have a"
              " Kerberos ticket with your own login to use this system. Please"
              " run \"kinit <your_login>\" and run \"examshell\" again.").format(pn))


def ip_allowed(raw_networks):
    networks = [IPNetwork(n) for n in raw_networks]
    ip = get_lan_ip()
    if ip is None:
        return True
    for network in networks:
        if ip in network:
            return True
    return False


def rfc3339_to_local(src):
    """Converts a date in RFC3339 format (Django's default JSON format for date)
    into a datetime in local time
    """
    ts = strict_rfc3339.rfc3339_to_timestamp(src)
    date = datetime.datetime.fromtimestamp(ts)
    return date


def date_to_str(src):
    """Return a coherent strftime of the passed date
    """
    return src.strftime("%d/%m/%Y %H:%M:%S")


def delta_to_str(src):
    """Returns a timedelta in form 'X hours, Y min and Z seconds'
    """
    s = src.seconds
    hours, remainder = divmod(s, 3600)
    minutes, seconds = divmod(remainder, 60)
    ret = "{0}sec".format(seconds)
    if minutes > 0 or hours > 0:
        ret = " and " + ret
    if minutes > 0:
        ret = "{0}min".format(minutes) + ret
    if hours > 0:
        if minutes > 0:
            ret = ", " + ret
        ret = "{0}hrs".format(hours) + ret

    return ret


def tilde(path):
    """Return the passed path with a ~ instead of the user's full homedir
    """
    return string.replace(path, os.path.expanduser("~"), "~")


def query_yes_no(question, default="yes"):
    """Ask a yes/no question, and waits for a yes/no answer
    to release control. Returns True if yes/ye/y, False otherwise
    """
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        choice = raw_input(question + prompt).lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            print "Please respond with 'yes' or 'no'"


def exam_request(fct):
    """Should be used as a decorator
    Takes a function that returns a (urlpath, parameters_dict) tuple,
    and generates a function that sends a request to the exam master
    """
    def wrap(*args, **kwargs):
        (path, jbody) = fct(*args, **kwargs)
        body = json.dumps(jbody)
        headers = {
            "Content-type": "application/json",
            "Accept": "application/json",
        }
        url = "%(host)s/%(path)s/" % {
            "host": HOST_BASE,
            "path": path,
        }
        try:
            response = requests.post(url,
                                     data=body,
                                     headers=headers,
                                     auth=HTTPKerberosAuth(
                                         mutual_authentication=DISABLED
                                     ),
                                     verify=False)
        except RuntimeError as e:
            fatal("Error communicating with server: You most likely do not have"
                  " a valid Kerberos ticket. Please run \"kinit <your_login>\""
                  " and run \"examshell\" again.")
        except Exception as e:
            fatal(("Exception while communicating with server"
                  " ({0})\n\nYou should retry. If this error persists, try"
                   "using another computer!\nIf it keeps happening after that,"
                   " warn a staff member !").format(str(e)))
        try:
            resp_json = AttrDict(response.json())
        except:
            resp_json = None
        return (response.status_code, resp_json)
    return wrap


@exam_request
def rq_close_session():
    return ("close_session", {})


@exam_request
def rq_get_session():
    return ("get_session", {})


@exam_request
def rq_get_version():
    return ("get_version", {})


@exam_request
def rq_get_assignment():
    return ("get_assignment", {})


@exam_request
def rq_grading():
    return ("grading", {})


@exam_request
def rq_resolve_error(decision):
    return ("resolve_error", {"decision": decision})


@exam_request
def rq_get_subject(assignment_name):
    return ("get_subject", {"assignment": assignment_name})


@exam_request
def rq_get_docs():
    return ("get_docs", {})


@exam_request
def rq_select_project(m, slug, sl):
    return ("select_project", {
        "mode": m,
        "slug": slug,
        "start_level": sl,
    })


def fatal(msg, staff=False):
    print "{0}: {1}".format(colored("ERROR", "red"), msg)
    if staff:
        print ("This is {0} expected, please contact a staff member "
               "{1}!").format(colored("NOT", 'red'),
                              colored("immediately", "red"))
    sys.exit(1)


def error_krb():
    return ("Server says you're unauthorized - Make sure you have a valid"
            " Kerberos ticket and try again")


def error_http(rc):
    if rc == 401:
        return error_krb()
    else:
        return ("Server returned HTTP error code {0} - Try again in a few"
                " moments, if the error persists, contact a staff"
                " member").format(rc)


class UpdatedProjectChoices(Exception):
    pass


class TooEarlyForReal(Exception):
    pass


class TooLateForReal(Exception):
    pass


class LoginWindowExpired(Exception):
    pass


class UnknownProject(Exception):
    pass


def select_project(mode, slug, start_level):
    check_principal()
    (rc, rj) = rq_select_project(mode, slug, start_level)
    if rc != 200:
        fatal(error_http(rc))
    if not rj.success:
        if rj.code == 3:
            error_krb()
            sys.exit(1)
        elif rj.code == 4:
            fatal("You have multiple running exam sessions", True)
        elif rj.code == 5:
            fatal("You are not allowed to access this exam session from"
                  " this location")
        elif rj.code == 14:
            fatal("There does not appear to be any running session here."
                  " Most probably the end date was exceeded, and it's been"
                  " marked as finished already.")
        elif rj.code == 7:
            fatal("The chosen session mode is invalid.", True)
        elif rj.code == 6:
            fatal("Your session already has a project selected.", True)
        elif rj.code == 8:
            raise UnknownProject()
        elif rj.code == 9:
            fatal("The requested start level is invalid", True)
        elif rj.code in [10, 11, 12, 13]:  # Vogsphere errors
            fatal("There was an error while creating your Git repository."
                  " Please try again in a few moments.")
        elif rj.code == 26:
            raise UpdatedProjectChoices(rj.args[0])
        elif rj.code == 27:
            raise TooEarlyForReal()
        elif rj.code == 28:
            raise TooLateForReal()
        elif rj.code == 34:
            raise LoginWindowExpired()
        fatal(("Unexpected error while selecting project (Code {0}, info"
               " \"{1}\").").format(rj.code, rj.message), True)
    return (rj.session)


def close_session():
    check_principal()
    (rc, rj) = rq_close_session()
    if rc != 200:
        fatal(error_http(rc))
    if not rj.success:
        if rj.code == 3:
            error_krb()
            sys.exit(1)
        elif rj.code == 4:
            fatal("You have multiple running exam sessions", True)
        elif rj.code == 5:
            fatal("You are not allowed to access this exam session from"
                  " this location")
        elif rj.code == 14:
            fatal("There does not appear to be any running session here."
                  " Most probably the end date was exceeded, and it's been"
                  " marked as finished already.")
        fatal(("Unexpected error while closing session (Code {0}, info"
               " \"{1}\").").format(rj.code, rj.message), True)
    return (rj.session)


def resolve_error(retry):
    check_principal()
    (rc, rj) = rq_resolve_error("retry" if retry else "abort")
    if rc != 200:
        fatal(error_http(rc))
    if not rj.success:
        if rj.code == 3:
            error_krb()
            sys.exit(1)
        elif rj.code == 4:
            fatal("You have multiple running exam sessions", True)
        elif rj.code == 5:
            fatal("You are not allowed to access this exam session from"
                  " this location")
        elif rj.code == 23:
            fatal("This current assignment is not in an error state. You"
                  " can just retry.", True)
        elif rj.code == 24:
            fatal("Wrong resolution decision", True)
        elif rj.code == 14:
            fatal("There does not appear to be any running session here."
                  " Most probably the end date was exceeded, and it's been"
                  " marked as finished already.")
        fatal(("Unexpected error while trying to resolve error (Code "
               "{0}, info \"{1}\").").format(rj.code, rj.message), True)
    return (rj.assignment)


def get_session():
    check_principal()
    (rc, rj) = rq_get_session()
    if rc != 200:
        fatal(error_http(rc))
    if not rj.success:
        if rj.code == 3:
            error_krb()
            sys.exit(1)
        elif rj.code == 4:
            fatal("You have multiple running exam sessions", True)
        elif rj.code == 5:
            fatal("You are not allowed to access this exam session from"
                  " this location")
        elif rj.code == 21:
            print colored("The end date for this session is exceeded, it's "
                          "been marked as finished.", "red", attrs=["bold"])
            print_session_info_and_exit(rj.args[0])
        elif rj.code == 14:
            fatal("There does not appear to be any running session here."
                  " Most probably the end date was exceeded, and it's been"
                  " marked as finished already.")
        elif rj.code in [29, 30, 31, 33]:
            fatal("There has been an error while communicating with the"
                  " intranet. Please warn a staff member, and retry in a"
                  " few minutes.", True)
        elif rj.code == 32:
            fatal("Unknown exam pool.", True)
        fatal(("Unexpected error while getting session info (Code {0},"
               " info \"{1}\").").format(rj.code, rj.message), True)
    return (rj.session)


def get_version():
    check_principal()
    (rc, rj) = rq_get_version()
    if rc != 200:
        fatal(error_http(rc))
    if not rj.success:
        if rj.code == 3:
            error_krb()
            sys.exit(1)
        fatal(("Unexpected error while getting session info (Code {0},"
              " info \"{1}\").").format(rj.code, rj.message), True)
    return (rj.version)


class GradingThrottled(Exception):
    pass


def grading():
    check_principal()
    (rc, rj) = rq_grading()
    if rc != 200:
        fatal(error_http(rc))
    if not rj.success:
        if rj.code == 3:
            error_krb()
            sys.exit(1)
        elif rj.code == 4:
            fatal("You have multiple running exam sessions", True)
        elif rj.code == 5:
            fatal("You are not allowed to access this exam session from this"
                  " location")
        elif rj.code == 21:
            print colored("The end date for this session is exceeded, it's been"
                          " marked as finished.", "red", attrs=["bold"])
            print_session_info_and_exit(rj.args[0])
        elif rj.code == 18:
            fatal("You do not have a current assignment for this session", True)
        elif rj.code == 20:
            fatal("There was a problem while submitting your grading job to the"
                  " Deepthought cluster. You should retry in a few moments, but"
                  " if this error persists, please contact a staff member!")
        elif rj.code == 25:
            raise GradingThrottled()
        elif rj.code == 14:
            fatal("There does not appear to be any running session here. Most"
                  "probably the end date was exceeded, and it's been marked as"
                  " finished already.")
        fatal(("Unexpected error while submitting grading job (Code {0},"
               " info \"{1}\").").format(rj.code, rj.message), True)
    return (rj.assignment)


class NoMoreAssignmentsInLevel(Exception):
    pass


class NoMoreLevelsInExam(Exception):
    pass


def get_current_assignment():
    check_principal()
    (rc, rj) = rq_get_assignment()
    if rc != 200:
        fatal(error_http(rc))
    if not rj.success:
        if rj.code == 3:
            error_krb()
            sys.exit(1)
        elif rj.code == 15:
            fatal("You do not have a session in progress. You must log in.")
        elif rj.code == 4:
            fatal("You have multiple running exam sessions", True)
        elif rj.code == 5:
            fatal("You are not allowed to access this exam session from this"
                  " location")
        elif rj.code == 16:
            raise NoMoreLevelsInExam(rj.args[0])
        elif rj.code == 17:
            raise NoMoreAssignmentsInLevel(rj.args[0])
        elif rj.code == 21:
            print colored("The end date for this session is exceeded, it's "
                          "been marked as finished.", "red", attrs=["bold"])
        elif rj.code == 14:
            fatal("There does not appear to be any running session here. Most"
                  " probably the end date was exceeded, and it's been marked"
                  " as finished already.")
        fatal(("Unexpected error while getting current assignment (Code {0},"
               " info \"{1}\").").format(rj.code, rj.message), True)
    return (rj.assignment)


def get_docs():
    check_principal()
    (rc, rj) = rq_get_docs()
    if rc != 200:
        fatal(error_http(rc))
    if not rj.success:
        if rj.code == 3:
            error_krb()
            sys.exit(1)
        elif rj.code == 4:
            fatal("You have multiple running exam sessions", True)
        elif rj.code == 15:
            fatal("Your session is not in progress", True)
        elif rj.code == 5:
            fatal("You are not allowed to access this exam session from this"
                  " location")
        elif rj.code == 21:
            print colored("The end date for this session is exceeded, it's "
                          "been marked as finished.", "red", attrs=["bold"])
        elif rj.code == 14:
            fatal("There does not appear to be any running session here. Most"
                  " probably the end date was exceeded, and it's been marked as"
                  " finished already.")
        fatal(("Unexpected error while getting docs (Code {0},"
               " info \"{1}\").").format(rj.code, rj.message), True)
    return (rj.docs)


def get_subject(name):
    check_principal()
    (rc, rj) = rq_get_subject(name)
    if rc != 200:
        fatal(error_http(rc))
    if not rj.success:
        if rj.code == 3:
            error_krb()
            sys.exit(1)
        elif rj.code == 4:
            fatal("You have multiple running exam sessions", True)
        elif rj.code == 5:
            fatal("You are not allowed to access this exam session from this"
                  " location")
        elif rj.code == 18:
            fatal(("You do not have the assignment {0} in your session").format(
                name), True)
        elif rj.code == 19:
            fatal(("The assignment {0} appears multiple times in your"
                   " session").format(name), True)
        elif rj.code == 21:
            print colored("The end date for this session is exceeded, it's "
                          "been marked as finished.", "red", attrs=["bold"])
        elif rj.code == 14:
            fatal("There does not appear to be any running session here. Most"
                  " probably the end date was exceeded, and it's been marked as"
                  " finished already.")
        fatal(("Unexpected error while getting current subject (Code {0},"
               " info \"{1}\").").format(rj.code, rj.message), True)
    return (rj.subject)


def user_select_project(session):
    invalid_idx = []
    doable = []
    reals = {}
    practices = {}
    dn = rfc3339_to_local(session.date_now)
    for idx, project in enumerate(session.projects):
        ds = rfc3339_to_local(project.date_start)
        dl = rfc3339_to_local(project.date_limit)
        lw = rfc3339_to_local(project.login_window)
        if "real" not in project.available_modes:
            reals[idx] = False
        elif not ip_allowed(project.allowed_networks):
            reals[idx] = False
        elif (dn < ds
              or dn > dl
              or dn > lw
              or ds < datetime.datetime.fromtimestamp(86400)):
            reals[idx] = False
        elif not REAL_MODE:
            reals[idx] = False
        else:
            reals[idx] = True
        if "practice" not in project.available_modes:
            practices[idx] = False
        elif REAL_MODE:
            practices[idx] = False
        else:
            practices[idx] = True

        if not practices[idx] and not reals[idx]:
            invalid_idx.append(idx)
        else:
            doable.append((idx, project))

    print
    print "The following projects are available to you at the moment:"
    for idx, project in enumerate(session.projects):
        ds = rfc3339_to_local(project.date_start)
        dl = rfc3339_to_local(project.date_limit)
        lw = rfc3339_to_local(project.login_window)
        print
        print "  {0}: {1}".format(
            colored("{0:<2}".format(idx),
                    "green" if idx not in invalid_idx else "red"),
            colored(project.title, attrs=["bold"])
        )
        print ("      Maximum start level    : {0}"
               " (Best grade you got is {1})").format(
                   colored(project.max_start_level, "yellow"),
                   colored(project.best_grade, "green"))
        if ds < datetime.datetime.fromtimestamp(0) + datetime.timedelta(days=1):
            print ("      Real mode available    : {0} (You must subscribe"
                   " to an exam event)").format(colored("no", "red"))
        elif "real" not in project.available_modes:
            if not project.retried:
                print ("      Real mode available    : {0} (You must retry"
                       " the project on the intranet)").format(
                           colored("no", "red"))
            elif not project.event_allows_real:
                print ("      Real mode available    : {0} (Current event"
                       " doesn't allow for this exam)").format(
                           colored("no", "red"))
            else:
                print ("      Real mode available    : {0} (Project doesn't"
                       " allow it)").format(colored("no", "red"))
        elif not ip_allowed(project.allowed_networks):
            print ("      Real mode available    : {0} (Can't do it from this"
                   " location)").format(colored("no", "red"))
        elif dn < ds:
            print ("      Real mode available    : {0} (Too early, will be OK"
                   " in {1})").format(colored("no", "red"),
                                      delta_to_str(ds - dn))
        elif dn > lw:
            print ("      Real mode available    : {0} (Login window expired"
                   " {1} ago)").format(colored("no", "red"),
                                       delta_to_str(dn - lw))
        elif dn > dl:
            print ("      Real mode available    : {0} (Too late, ended at"
                   " {1})").format(colored("no", "red"), date_to_str(dl))
        elif not REAL_MODE:
            print ("      Real mode available    : {0} (Must login as 'exam' to"
                   " run in real mode)").format(colored("no", "red"),
                                                date_to_str(dl))
        else:
            print ("      Real mode available    : {0} (Login ends in"
                   " {1})").format(colored("yes", "green"),
                                   delta_to_str(lw - dn))
            print ("                                   (Exam ends in"
                   " {0})").format(delta_to_str(dl - dn))
        if "practice" not in project.available_modes:
            print ("      Practice mode available: {0} (Project doesn't allow"
                   " it)").format(colored("no", "red"))
        elif REAL_MODE:
            print ("      Practice mode available: {0} (Can't practice when"
                   " logged in as 'exam')").format(colored("no", "red"))
        else:
            print ("      Practice mode available: {0} (Ends in"
                   " {1})").format(colored("yes", "green"),
                                   delta_to_str(
                                       datetime.timedelta(
                                           hours=project.duration)))

    print
    if len(doable) == 0:
        fatal("There are currently no projects you CAN do here and now.")
    elif len(doable) > 1:
        print "Please choose which project you would like to do on this session"
        while True:
            print
            idx_raw = raw_input("ID of desired project(" + colored(
                "0-{0}".format(len(session.projects) - 1), "green") + "): ")
            try:
                idx = int(idx_raw)
                if (idx >= 0
                    and idx < len(session.projects)
                    and idx not in invalid_idx):
                    break
            except:
                pass
            print ("Invalid project number, please the ID of one of the"
                   " projects listed in green above")
    else:
        print "There is only one project you can do right now."
        print ("Automatically selecting project {0}:"
               " \"{1}\"").format(colored(0, "green"), doable[0][1].title)
        idx = doable[0][0]

    max_lvl = session.projects[idx].max_start_level

    print
    project = session.projects[idx]
    if reals[idx] and practices[idx]:
        while True:
            print ("Please choose either '{0}' or '{1}' mode").format(
                colored("real", "magenta"), colored("practice", "green"))
            print ("In '{0}' mode, your grade will be taken into account on the"
                   " intranet, but you can only access your repository from an"
                   " exam session").format(colored("real", "magenta"))
            print ("In '{0}' mode, your grade will not be taken into account,"
                   " and you can only access your repository from your regular"
                   " (non-exam) session").format(colored("practice", "green"))
            mode = raw_input("Desired mode: ")
            if mode in ["practice", "real"]:
                break
    else:
        if reals[idx]:
            print ("This project can only be done in {0} mode").format(
                colored("real", "magenta"))
            print ("In '{0}' mode, your grade will be taken into account on the"
                   " intranet, but you can only access your repository from an"
                   " exam session").format(colored("real", "magenta"))
            mode = "real"
        elif practices[idx]:
            print ("This project can only be done in {0} mode").format(
                colored("practice", "green"))
            print ("In '{0}' mode, your grade will not be taken into account,"
                   " and you can only access your repository from your regular"
                   " (non-exam) session").format(colored("practice", "green"))
            mode = "practice"
        else:
            print ("This project does not allow you to select either practice"
                   " or real mode at this time and place.")
            return (None, None, None)

    print
    if max_lvl > 0:
        print ("Please select the level at which you would like to start"
               " your session")
        print ("Be aware that if you select a level higher than 0, you will"
               " only gain however many points the previous levels would have"
               " given you IF you complete your selected starting level !")
        while True:
            print
            lvl_raw = raw_input("Desired start level ("
                                + colored("0-{0}".format(max_lvl),
                                          "yellow") + "): ")
            try:
                lvl = int(lvl_raw)
            except:
                print "This is not a number ..."
                continue
            if lvl >= 0 and lvl <= max_lvl:
                break
            else:
                print ("Invalid start level, please choose between "
                       + colored(0, "yellow")
                       + " and {0}").format(colored(max_lvl, "yellow"))
                continue
    else:
        print ("You can only start this project on level {0}").format(
            colored(0, "yellow"))
        lvl = 0

    print
    return (mode, idx, lvl)


def choose_project(session):
    if len(session.projects) == 0:
        fatal("You are not subscribed to any exam projects. You can not do an"
              " exam now.")
    while True:
        (mode, idx, lvl) = user_select_project(session)
        if mode is None:
            continue
        if mode == "practice":
            delta = datetime.timedelta(hours=session.projects[idx].duration)
        else:
            dn = datetime.datetime.now()
            dl = rfc3339_to_local(session.projects[idx].date_limit)
            delta = dl - dn
            modecol = "green" if mode == "practice" else "magenta"
            print ("You are about to start the project \"{0}\", in {1} mode,"
                   " at level {2}.").format(session.projects[idx].title,
                                            colored(mode, modecol),
                                            colored(lvl, "yellow"))
        print ("You would have {0} to complete this project").format(
            colored(delta_to_str(delta), "green"))
        if query_yes_no("Confirm ?", None):
            print "Selecting project..."
            try:
                sess = select_project(mode, session.projects[idx].slug, lvl)
                break
            except UnknownProject:
                print ("The project you have selected isn't in the list of"
                       " allowed projects for you right now.")
                print ("This can happen sometimes if the allowed start date has"
                       " just been exceeded, or if you've become unsubscribed")
                print ("You should just try again right now, but if the error"
                       " persists, warn a staff member.")
                raw_input("(Press Enter to continue...)")
                continue
        else:
            print "OK, we'll ask again..."
            session = get_session()

    return sess


def ensure_git(session):
    if os.path.isdir(GIT_DIR):
        config_path = os.path.join(GIT_DIR, ".git", "config")
        if os.path.isfile(config_path):
            with open(config_path) as fp:
                data = fp.read()
            if string.find(data, session.git_url) == -1:
                print ("{2}: While a git repository does exist in {0}, the"
                       " correct remote URL does not appear in its config."
                       " Please ensure that this git repository is indeed a"
                       " clone of the following URL: \"{1}\". If not, clone it"
                       " yourself.").format(tilde(GIT_DIR),
                                            session.git_url,
                                            colored("WARNING", "yellow"))
            else:
                print ("{1}: A git repository already exists in {0}. While the"
                       " remote URL appears to be correct, maybe you should"
                       " still 'git pull', just to be safe.").format(
                           tilde(GIT_DIR), colored("WARNING", "yellow"))
            return
        else:
            shutil.rmtree(GIT_DIR)
    print "Git repository is not cloned yet. Cloning..."
    try:
        out = subprocess.check_output("git clone {0} {1}".format(
            session.git_url, GIT_DIR), stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError as e:
        print e.output
        fatal(("Could not clone the git repository from {0} (Return code"
              " {1}).").format(session.git_url, e.returncode), True)
    print out
    print "Your git repository was successfully cloned to {0}".format(
        tilde(GIT_DIR))


def remove_dirs():
    for d in [SUBJECTS_DIR, GIT_DIR, TRACES_DIR, DOCS_DIR]:
        if os.path.isdir(d):
            shutil.rmtree(d)


def ensure_dirs():
    for d in [SUBJECTS_DIR, GIT_DIR, TRACES_DIR, DOCS_DIR]:
        if not os.path.isdir(d):
            os.makedirs(d)


def print_session_info_and_exit(sess):
    sessmode = (colored("REAL", "magenta")
                if sess.mode == "real" else colored("practice", "green"))
    print
    print "You were doing \"{0}\" in {1} mode.".format(
        sess.current_project.title,
        sessmode)
    print "Your final grade is {0}/100.".format(colored(sess.grade, "green"))
    print
    print colored("This session is finished, you can now log out.",
                  "magenta", attrs=["bold"])
    sys.exit(0)


def get_current_and_ensure_subject():
    """get the current assignment
    then get the subject
    then save it to the appropriate location
    then return the assignment
    """
    try:
        assignment = get_current_assignment()
    except NoMoreAssignmentsInLevel as e:
        print
        print colored("You have tried and failed all the possible assignments"
                      " at this level.", "red", attrs=["bold"])
        print_session_info_and_exit(e.args[0])
    except NoMoreLevelsInExam as e:
        print
        print colored("You have completed the last level of this exam."
                      " Congratulations !", "green", attrs=["bold"])
        print_session_info_and_exit(e.args[0])

    subject = get_subject(assignment.name)
    try:
        ensure_dirs()
    except Exception as e:
        traceback.print_exc(e)
        fatal("There was a problem creating the required directories for the"
              " exam.", True)
    subject_dir = os.path.join(SUBJECTS_DIR, assignment.name)
    if os.path.isdir(subject_dir):
        shutil.rmtree(subject_dir)
    os.mkdir(subject_dir)
    buf = cStringIO.StringIO(base64.b64decode(subject))
    tf = tarfile.open(mode='r:gz', fileobj=buf)
    tf.extractall(subject_dir)
    tf.close()

    return assignment


def get_current_and_advertise():
    current = get_current_and_ensure_subject()
    advertise_assignment(current)
    return current


def advertise_assignment(current):
    print ("Your current assignment is {0} for {1} potential points").format(
        colored(current.name, 'green'),
        colored(current.potential_grade, "green"))
    print ("It is assignment {0} for level {1}").format(
        colored(current.index, "yellow"),
        colored(current.level, "green"))
    print ("The subject is located at: {0}").format(
        colored(tilde(os.path.join(SUBJECTS_DIR, current.name)), 'green'))
    print ("You must turn in your files in a {0} with the\nsame name as the"
           " assignment ({1}).\nOf course, you must still push...").format(
               colored("subdirectory of your Git repository", attrs=["bold"]),
               colored(tilde(os.path.join(GIT_DIR, current.name)),
                       'red', attrs=["bold"]))


def can_now_work():
    print ("You can now work on your assignment. When you are sure you're done"
           " with it,\npush it to vogsphere, and then use the \"{0}\" command"
           " to be graded.").format(colored("grademe", "green"))


def save_trace(assignment):
    if assignment.trace is None:
        fatal("Can not save a trace when there is none.", True)
    ensure_dirs()
    tracefile = os.path.join(TRACES_DIR, "{0}-{1}_{2}.trace".format(
        assignment.level, assignment.index, assignment.name))
    with open(tracefile, "w") as fp:
        fp.write(assignment.trace)

    print "Trace saved to {0}".format(colored(tilde(tracefile), "green"))


class ExamShell(cmd.Cmd):
    prompt = "{0}> ".format(colored("examshell", "yellow", attrs=["bold"]))
    current_assignment = None

    def __init__(self):
        cmd.Cmd.__init__(self)

    def print_usage(self):
        print
        print "The following commands are available to you:"
        print ("  {0}: Displays the status of your session, including"
               " information about\n    your current assignment, and the exam"
               " history.").format(colored("status", "green"))
        print """  {0}: Asks the server to grade your current assignment. If you
    have done it right, you will gain the points of the current assignment, go
    up a level, and try the next one. If you fail, however, you will have
    another assignment of the same level to do, and it will potentially bring
    you less points on your grade ... So be sure of yourself before you launch
    this command !""".format(colored("grademe", "green"))
        print "  {0}: Tells the server you are finished with your exam.".format(
            colored("finish", "green"))
        print
        print ("You can log out at any time. If this program tells you you"
               " earned points,\nthen they will be counted whatever happens.")

    def help_EOF(self):
        print "(Called when you issue a Ctrl-D) Alias for exit"

    def do_EOF(self, line):
        return self.do_exit(line)

    def help_exit(self):
        print "Exits this program"

    def do_exit(self, line):
        return True

    def help_status(self):
        print ("Displays the status of your session, including information"
               " about\nyour current assignment, and the exam history.")

    def do_status(self, line):
        cur = self.current_assignemnt = get_current_and_ensure_subject()
        sess = get_session()
        print
        print ("========================================================"
               "========================")
        print "You are currently at level {0}".format(
            colored(sess.level, "green"))
        if sess.mode == "real":
            print ("You are running in {0} mode (Your grade will be"
                   " counted)").format(colored("REAL", "magenta"))
        else:
            print ("You are running in {0} mode (Your grade does not"
                   " count)").format(colored("practice", "green"))
        print "Your current grade is {0}/100".format(
            colored(sess.grade, "green"))
        print "Assignments:"
        lvl = -1
        for ass in sess.assignments:
            if ass.level > lvl:
                lvl = ass.level
                print "  Level {0}:".format(colored(str(lvl), "green"))
            if ass.state == "in_progress":
                st = colored("Current", "cyan")
            elif ass.state == "wait_grading":
                st = colored("Grading in progress", "cyan")
            elif ass.state == "ok":
                st = colored("Success", "green")
            elif ass.state == "ko":
                st = colored("Failure", "red")
            elif ass.state == "error":
                st = colored("Unresolved error", "magenta")
            elif ass.state == "aborted":
                st = colored("Aborted by user", "magenta")
            print "    {0}: {1} for {3} potential points ({2})".format(
                colored(ass.index, "yellow"),
                colored(ass.name, "green"), st, ass.potential_grade)

        print
        advertise_assignment(cur)
        dl = rfc3339_to_local(sess.date_limit)
        now = rfc3339_to_local(sess.date_now)
        delta = delta_to_str(dl - now)
        print
        print "The end date for this exam is: {0}".format(
            colored(date_to_str(dl), "green"))
        print "You have {0} remaining".format(colored(delta, "green"))
        print ("==========================================================="
               "=====================")

    def help_finish(self):
        print "Tells the server your session is finished"

    def do_finish(self, line):
        print ("Please confirm that you {0} want to end your current"
               " session.").format(colored("REALLY", "red", attrs=["bold"]))
        print "If you do, you will not be able to do anything with it anymore!"
        try:
            if query_yes_no("Are you finished?", default="no"):
                close_session()
                print ("Your session has been marked as finished. You may now"
                       " log out.")
                return True
            else:
                print "Aborting"
        except KeyboardInterrupt:
            print "Aborting"

    def help_grademe(self):
        print ("Asks the server to grade your current assignment. If you have"
               " done it right,\nyou will gain the points of the current"
               " assignment, go up a level, and try the\nnext one. If you fail,"
               " however, you will have another assignment of the same\nlevel"
               " to do, and it will potentially bring you less points on your"
               " grade ... So\nbe sure of yourself before you launch this"
               " command !")

    def do_grademe(self, line):
        """get current assignment
        show the user what would be graded
        confirm decision
        ok? then send grading request, and send another request every 10 seconds
        until done
        """

        print
        print ("Before continuing, please make {0} that you have pushed your"
               " files,\nthat they are in the right directory, that you didn't"
               " forget anything, etc...").format(
                   colored("ABSOLUTELY SURE", "red"))
        print ("If your assignment is wrong, you will have another assignment"
               " at the same level,\nbut with less potential points to earn!")
        print
        try:
            if not query_yes_no(colored("Are you sure?", "red"), default="no"):
                print "Aborting"
                return False
        except KeyboardInterrupt:
            print "Aborting"
            return False

        print "OK, making grading request to server now."
        try:
            rspg = grading()
        except GradingThrottled:
            print ("{0}: You must wait at least 2 minutes between grading"
                   " requests").format(colored("ERROR", "red"))
            return False

        print
        print "We will now wait for the job to complete."
        print ("Please be {0}, this {1} take several minutes...").format(
            colored("patient", "green"), colored("CAN", "green"))
        print ("(10 seconds is fast, 30 seconds is expected,"
               " 3 minutes is a maximum)")

        do_trace = False
        do_status = False

        try:
            while True:
                rspg = grading()
                if rspg.state == "in_progress":
                    fatal("Grading job has not even started."
                          " You can just retry.", True)
                elif rspg.state == "wait_grading":
                    print "waiting..."
                    time.sleep(10)
                    continue
                elif rspg.state == "ok":
                    print colored(">>>>>>>>>> SUCCESS <<<<<<<<<<", "green",
                                  attrs=["bold"])
                    print ("You have successfully completed the assignment and"
                           " earned {0} points!").format(
                               colored(rspg.potential_grade, "green"))
                    do_trace = True
                    do_status = True
                    break
                elif rspg.state == "ko":
                    print colored(">>>>>>>>>> FAILURE <<<<<<<<<<", "red",
                                  attrs=["bold"])
                    print "You have failed the assignment."
                    do_trace = True
                    do_status = True
                    break
                elif rspg.state == "error":
                    print colored("########## ERROR ##########", "magenta",
                                  attrs=["bold"])
                    print "There was a problem with the grading job."
                    print "Please review the trace below:"
                    print ("==================================================="
                           "=============================")
                    print rspg.trace
                    print ("==================================================="
                           "=============================")
                    print ("You can choose to {0}, or to {1}.").format(
                        colored("retry", "yellow"), colored("abort", "red"))
                    print ("If you {0}, this grading job will be restarted."
                           " There is no risk in retrying, a lot of errors are "
                           "just transient.").format(colored("retry", "yellow"))
                    print ("If you {0}, this grading job will be stopped, and"
                           " you will have a new assignment at the same level."
                           " You will, of course, NOT be penalized in any"
                           " way.").format(colored("abort", "red"))
                    print ("If the error is not solved by a {0}, please inform"
                           " a staff member {1}, as this should not really"
                           " happen !").format(colored("retry", "yellow"),
                                               colored("immediately", "red"))
                    print
                    while True:
                        if query_yes_no("Do you want to {0}?".format(
                            colored("retry", "yellow"))):
                            print "OK, asking the server to retry."
                            rspg = resolve_error(True)
                            brk = False
                            break
                        else:
                            print ("Are you sure? Please understand that if you"
                                   " choose to {0}, you will forfeit this"
                                   " assignment and get a new one (albeit at no"
                                   " penalty to you).").format(
                                       colored("abort", "red"))
                            if not query_yes_no(("Do you REALLY want to {0}"
                                                "?").format(colored("abort",
                                                                    "red")),
                                                default="no"):
                                continue
                            print "OK, telling the server to abort."
                            rspg = resolve_error(False)
                            do_status = True
                            brk = True
                            break
                    if brk:
                        break
                    else:
                        continue
                elif rspg.state == "aborted":
                    fatal("Grading job was unexpectedly aborted.", True)
        except KeyboardInterrupt:
            print "Aborting"
            print "Grading job is still running on the server"
            print ("You can just run \"{0}\" again to get the result").format(
                colored("grademe", "green"))
            return False
        except GradingThrottled:
            print ("{0}: You must wait at least 2 minutes between grading"
                   " requests").format(colored("ERROR", "red"))
            return False

        if do_trace:
            save_trace(rspg)

        print
        raw_input("(Press Enter to continue...)")

        if do_status:
            self.do_status("")
            can_now_work()


def check_mode_conflicts(session):
    if session.mode is not None:
        if session.mode == "practice" and REAL_MODE:
            fatal("You already have a running session in practice mode, and can"
                  " not access it from an exam session. If you want to start a"
                  " new session, you have to either close it manually using the"
                  " \"finish\" command, or wait until its end time")
        elif session.mode == "real" and not REAL_MODE:
            fatal("You already have a running session in real mode, and can"
                  " not access it from your regular session. If you want to"
                  " start a new session, you have to either close it manually"
                  " using the \"finish\" command, or wait until its end time")


def fetch_docs(session):
    docs = get_docs()
    try:
        ensure_dirs()
    except Exception as e:
        traceback.print_exc(e)
        fatal("There was a problem creating the required directories for the"
              " exam.", True)
    buf = cStringIO.StringIO(base64.b64decode(docs))
    tf = tarfile.open(mode='r:gz', fileobj=buf)
    tf.extractall(DOCS_DIR)
    tf.close()


if __name__ == "__main__":
    print "examshell v{0}".format(colored(__version__, "green"))
    print
    check_principal()

    sh = ExamShell()
    try:
        version = get_version()
        if version != __version__:
            fatal(("Mismatched versions (Local version is {0}, server expects"
                   " {1}).\nPlease update your examshell.").format(
                       __version__, version))

        if CLEAN_BASEDIR:
            print colored("WARNING", "red")
            print "Your exam files will be stored in {0}".format(
                colored(tilde(EXAM_BASEDIR), "green"))
            print colored("THIS DIRECTORY WILL BE ENTIRELY EMPTIED BEFORE"
                          " YOU START", "red")
            print ("So, if you do have important things there, Ctrl-C NOW and"
                   " back them up before running this.")
            raw_input("(Press Enter to continue...)")

            remove_dirs()

        while True:
            print "Getting current exam session from server..."
            session = get_session()

            check_mode_conflicts(session)

            if session.state == "wait_choice":
                try:
                    session = choose_project(session)
                    break
                except TooEarlyForReal:
                    print ("{1}: Cannot select {0} mode for this project, it's"
                           " too early").format(colored("real", "magenta"),
                                                colored("ERROR", "red"))
                except TooLateForReal:
                    print ("{1}: Cannot select {0} mode for this project, it's"
                           " too late").format(colored("real", "magenta"),
                                               colored("ERROR", "red"))
                except LoginWindowExpired:
                    print ("{1}: Cannot select {0} mode for this project, the"
                           " login time is too long ago").format(
                               colored("real", "magenta"),
                               colored("ERROR", "red"))
                except UpdatedProjectChoices:
                    print ("{0}: You have waited too long to choose a project,"
                           " so the session has been refreshed from"
                           " server.").format(colored("ERROR", "red"))
            else:
                break
            raw_input("(Press Enter to continue...)")

        if session.state != "in_progress":
            fatal("Unexpected session state '{0}'".format(session.state), True)
        print "Creating required directories..."
        try:
            ensure_dirs()
        except Exception as e:
            traceback.print_exc(e)
            fatal("There was a problem creating the required directories for"
                  " the exam.", True)
        print ("Ensuring your Git repository for this exam is"
               " present and correct...")
        try:
            ensure_git(session)
        except Exception as e:
            traceback.print_exc()
            fatal("There was a problem ensuring your git directory is"
                  " correct.", True)

        try:
            fetch_docs(session)
        except Exception as e:
            traceback.print_exc()
            fatal("There was a problem fetching the documentation from the"
                  "master server.", True)

        sh.print_usage()
        print
        raw_input("(Press Enter to continue...)")
        sh.onecmd("status")
        can_now_work()
        sh.cmdloop()
    except (KeyboardInterrupt, EOFError):
        sh.do_exit("")
