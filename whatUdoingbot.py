import inspect
import pickle
import signal
import sys
import time

from argparse import ArgumentParser
from datetime import datetime, timedelta
from enum import Enum
from slackclient import SlackClient
from threading import Lock, Timer
from websocket import WebSocketConnectionClosedException

parser = ArgumentParser(description='Bot to measure work time of team members')
parser.add_argument('bot_id', help='Slack UID of bot')
parser.add_argument('slack_token', help='Slack token (xoxs-...)')
args = parser.parse_args()

# Globals
BOT_ID = args.bot_id
FOLLOWUP_TIME = timedelta(hours=1)  # Time to wait before follow-up
STATUS_FILE = "status.bin"  # Contains the statuses of current users when bot reboots
users = {}              # Map of user id's to User objects
slack_client = SlackClient(args.slack_token)

# String
MORNING_MESSAGE = "Good morning. Let's start creating awesome sound experiences. Have a great day!"
REQUEST_FOR_UPDATE = "Hey, just checking up. Can you let me know what have you been doing?"
INVALID_INPUT = "Not sure what you mean. Type help to get possible commands"
NO_ACCEPT_ARGUMENTS = "Don't understand this command if followed by further text :/"
UPDATE_MESSAGE = "Thanks for the update!"
PAUSE_MESSAGE = "All right, time for a break. Do remember to inform me when you return!"
RESUME_MESSAGE = "Hello again!"
LOGOUT_MESSAGE = "Bye bye!"

HELP_STRING = u"I'm _what_u_doing_, a bot to help you log your hourly tasks." \
    " Here are the commands that I understand for now:\n\n" \
    "*login* - Type this when you start your work day\n\n" \
    "*pause* - Want to take a break?" \
    " Type pause to ensure that the bot doesn't keep pestering you.\n\n" \
    "*resume* - Type this when you again start working after a pause." \
    " You should do this immediately after your break is over.\n\n" \
    "*update* - This is the main command. Whenever you want to share an update," \
    " write `update xyz`, where xyz is the work that you did since the last update.\n\n" \
    "*logout* - Done for the day? Just type logout to tell the bot!\n\n" \
    "For any queries or suggestions, reach out to what_u_doing_bot@soundrex.com ASAP."


class Status(Enum):
    active = 0
    paused = 1
    logged_out = 2

mismatch_message = {
    Status.active: "Can't do this when you're already active!",
    Status.paused: "Can't do this while on a pause.",
    Status.logged_out: "Can't do this while logged out."
}


class User:
    def __init__(self, data):
        self.id = data['id']
        self.name = data['name']
        self._status = Status.logged_out
        self._timer_start_time = None
        self._timer = None
        self._pause_time = None
        self._lock = Lock()
        self._log_file = None
        self._log_file_path = "logs/" + self.name + ".log"

    def __getstate__(self):
        state = self.__dict__.copy()
        for attr in ['_timer', '_lock', '_log_file']:
            state[attr] = None
        return state

    def __setstate__(self, state):
        self.__dict__ = state.copy()
        self._lock = Lock()
        if self._status is not Status.logged_out:
            self._log_file = open(self._log_file_path, 'a', encoding="UTF-8")
            if self._status is Status.active:
                self._initiate_followup(datetime.now()-self._timer_start_time)

    def _log(self, message):
        self._log_file.write(str(datetime.now())[:-7] + ": " + message + '\n')
        self._log_file.flush()

    def _post_message(self, message):
        slack_client.api_call("chat.postMessage", channel=self.id, text=message, as_user=True)

    def _allowed_status(*statuses):
        def with_fn(func):
            def with_args(self, *args):
                if self._status in statuses:
                    func(self, *args)
                else:
                    self._post_message(mismatch_message[self._status])
            with_args.__dict__ = func.__dict__
            return with_args
        return with_fn

    def _command(func):
        num_params = len(inspect.signature(func).parameters)-1

        def one_argument_fn(self, *args):  # args and num_params can both only be 0 or 1
            if len(args) == num_params:
                func(self, *args)
            elif args:
                self._post_message(NO_ACCEPT_ARGUMENTS)
            elif num_params:
                func(self, "")
        one_argument_fn.__dict__['command'] = True
        return one_argument_fn

    def _initiate_followup(self, elapsed_time=timedelta()):
        # timer_start_time denotes the *apparent* start time: FOLLOWUP_TIME before whenever
        # the timer is actually supposed to fire
        self._timer_start_time = datetime.now() - elapsed_time
        self._timer = Timer((FOLLOWUP_TIME-elapsed_time).total_seconds(), self._timely_followup)
        self._timer.start()

    def _timely_followup(self):
        with self._lock:
            if self._status == Status.active:  # Just in case the lock's acquired just after pause
                self._post_message(REQUEST_FOR_UPDATE)
                self._initiate_followup()

    @_command
    def help(self):
        self._post_message(HELP_STRING)

    @_allowed_status(Status.logged_out)
    @_command
    def login(self):
        self._log_file = open(self._log_file_path, 'a', encoding="UTF-8")
        self._status = Status.active
        self._post_message(MORNING_MESSAGE)
        self._log("Logged in")
        self._initiate_followup()

    @_allowed_status(Status.active)
    @_command
    def update(self, content):
        self._post_message(UPDATE_MESSAGE)
        self._log("Work update: " + content.replace("\n", "\n\t"))
        self._timer.cancel()
        self._initiate_followup()

    @_allowed_status(Status.active)
    @_command
    def pause(self):
        self._status = Status.paused
        self._pause_time = datetime.now()
        self._timer.cancel()
        self._post_message(PAUSE_MESSAGE)
        self._log("Paused for break")

    @_allowed_status(Status.paused)
    @_command
    def resume(self):
        self._status = Status.active
        self._initiate_followup(self._pause_time-self._timer_start_time)
        self._post_message(RESUME_MESSAGE)
        self._log("Resumed working")

    @_allowed_status(Status.active, Status.paused)
    @_command
    def logout(self):
        self._post_message(LOGOUT_MESSAGE)
        self._log("Logged out")
        self._status = Status.logged_out
        self._log_file.close()
        if self._timer:
            self._timer.cancel()

    def handle_command(self, user_input):
        """
            Receives commands directed at the bot and determines if they
            are valid commands. If so, then acts on the commands. If not,
            returns back what it needs for clarification.
        """
        tokens = user_input.split(None, 1)
        if tokens:
            with self._lock:
                func = getattr(self, tokens[0].lower(), None)
                if callable(func) and func.__dict__['command']:
                    func(*tokens[1:])
                else:
                    self._post_message(INVALID_INPUT)


def parse_slack_output(output_list):
    """
    Parses slack output to extract all messages not sent by the bot itself
    :param output_list: A list of json objects for slack messages
    :return: The ID of the user sending the message, and the text of the message
    """
    if output_list and len(output_list) > 0:
        for output in output_list:
            if output and 'text' in output and 'user' in output and output['user'] != BOT_ID:
                return output['user'], output['text']
    return None, None


def try_slack_connect(delay):
    """
    Keeps trying to connect to slack, with given delay between retries.
    """
    while not slack_client.rtm_connect():
        print("Unable to connect. Retrying...")
        time.sleep(delay)
    print("StarterBot connected and running!")


def save_and_quit(signal, frame):
    # TODO - Find out why SIGINT is required twice
    pickle.dump(users, open(STATUS_FILE, "wb"), pickle.HIGHEST_PROTOCOL)
    sys.exit()


def load_users():
    global users
    try:
        status_file = open(STATUS_FILE, "rb")
        users = pickle.load(status_file)
        status_file.close()
        print("Restored state information of users")
    except (FileNotFoundError, IOError, EOFError):
        users = {}
        for user_data in slack_client.api_call("users.list")['members']:
            users[user_data['id']] = User(user_data)
        print("Reset all user data")


if __name__ == "__main__":
    load_users()
    signal.signal(signal.SIGINT, save_and_quit)

    try_slack_connect(1)
    while True:
        try:
            uid, command = parse_slack_output(slack_client.rtm_read())
            if uid in users:
                users[uid].handle_command(command)
            time.sleep(1)  # 1 second delay between reading from firehose
        except WebSocketConnectionClosedException:
            print("Connection to Slack closed. Reconnecting...")
            try_slack_connect(1)
