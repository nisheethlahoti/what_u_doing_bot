#!/usr/bin/python3

import functools
import os
import pickle
import signal
import sys
import time

from argparse import ArgumentParser
from datetime import datetime, timedelta
from enum import Enum
from slackclient import SlackClient
from threading import Lock, Timer

parser = ArgumentParser(description='Bot to measure work time of team members')
parser.add_argument('bot_id', help='Slack UID of bot')
parser.add_argument('slack_token', help='Slack token (xoxs-...)')
parser.add_argument('admins', nargs='*', help="The people who receive everyone's daily report")
args = parser.parse_args()

# Globals
BOT_ID = args.bot_id
FOLLOWUP_TIME = timedelta(hours=1)      # Time to wait before follow-up
users = {}                              # Map of user id's to User objects
slack_client = SlackClient(args.slack_token)
UPDATE_RECEIVERS = set(args.admins)

# String
MORNING_MESSAGE = "Good morning. Let's start creating awesome sound experiences. Have a great day!"
REQUEST_FOR_UPDATE = "Hey, just checking up. Can you let me know what have you been doing?"
INVALID_INPUT = "Not sure what you mean. Type help to get possible commands"
WRONG_ARGUMENTS = "Sorry, wrong further input for this command :/"
UPDATE_MESSAGE = "Thanks for the update!"
PAUSE_MESSAGE = "All right, time for a break. Do remember to inform me when you return!"
RESUME_MESSAGE = "Hello again!"
LOGOUT_MESSAGE = "Bye bye!"
INVALID_STATUS = "Can't do this while you're {}!"

HELP_MESSAGE = u"I'm _what_u_doing_, a bot to help you log your hourly tasks." \
               " Here are the commands that I understand for now:\n\n" \
               "*login* - Type this when you start your work day\n\n" \
               "*pause* - Want to take a break?" \
               " Type pause to ensure that the bot doesn't keep pestering you.\n\n" \
               "*resume* - Type this when you again start working after a pause." \
               " You should do this immediately after your break is over.\n\n" \
               "*update* - This is the main command. Whenever you want to share an update," \
               " write `update xyz`, where xyz is the work you did since the last update.\n\n" \
               "*logout* - Done for the day? Just type logout to tell the bot!\n\n" \
               "*get_work_time* - Type this if you want to know how long you've already worked" \
               " for the day.\n\n" \
               "For any queries or suggestions, reach out to what_u_doing_bot@soundrex.com ASAP."

STATS_MESSAGE = u"Your Work Update for {date!s}:\n\n" \
                "Today you worked for {hours!s} hours. Here's what you did in that time:\n" \
                "{tasks}\n\n" \
                "Cheers!"


class Status(Enum):
    active = 0
    paused = 1
    logged_out = 2


class User:
    def __init__(self, data):
        self.id = data['id']
        self.name = data['name']
        self._status = Status.logged_out
        self._timer_start_time = None
        self._timer = None
        self._pause_time = None
        self._lock = Lock()
        self._log_file_path = "logs/" + self.name + ".log"
        self._working_time = None
        self._updates = None

    @property
    def status(self):
        return self._status

    def __getstate__(self):
        state = self.__dict__.copy()
        state['_timer'], state['_lock'] = None, None
        return state

    def __setstate__(self, state):
        self.__dict__ = state.copy()
        self._lock = Lock()
        self._timer = Timer(0, lambda: None)    # Just so it has a non-null value
        if self._status is Status.active:
            self._initiate_followup(datetime.now() - self._timer_start_time)

    def _log(self, message):
        with open(self._log_file_path, 'a', encoding="UTF-8") as log_file:
            log_file.write(str(datetime.now())[:-7] + ": " + message.replace("\n", "\n\t") + '\n')
        slack_client.api_call("chat.postMessage", channel='#live_work_updates',
                              text=self.name + " " + message, as_user=True)

    def _slack_message(self, message):
        try:
            slack_client.api_call("chat.postMessage", channel=self.id, text=message, as_user=True)
        except Exception as e:
            self._log("[Error Generated]\n" + str(e))

    def _command(*statuses):
        """
        Decorator to mark a method as callable by the end user
        :param statuses: The list of possible user states when calling the command is allowed
        """

        def with_fn(func):
            @functools.wraps(func)
            def with_args(self, *args):
                if self._status in statuses:
                    try:
                        func(self, *args)
                    except TypeError:
                        self._slack_message(WRONG_ARGUMENTS)
                else:
                    self._slack_message(INVALID_STATUS.format(self._status.name.replace('_', ' ')))

            with_args.is_command = True   # is_command should only be present for commands
            return with_args

        return with_fn

    def _initiate_followup(self, elapsed_time=timedelta()):
        """
        Start the countdown timer for the next timely followup.
        :param elapsed_time: Time for which the timer has already run. Defaults to zero.
        """
        # timer_start_time denotes the *apparent* start time: FOLLOWUP_TIME before whenever
        # the timer is actually supposed to fire
        self._timer_start_time = datetime.now() - elapsed_time
        self._timer = Timer((FOLLOWUP_TIME - elapsed_time).total_seconds(), self._timely_followup)
        self._timer.start()

    def _timely_followup(self):
        """
        Executed when enough time has passed since the last update, and a new update is required.
        """
        with self._lock:
            if self._status == Status.active:  # Just in case the lock's acquired just after pause
                self._working_time += FOLLOWUP_TIME
                self._slack_message(REQUEST_FOR_UPDATE)
                self._initiate_followup()

    @_command(*Status)  # Allow for all values of Status
    def help(self):
        self._slack_message(HELP_MESSAGE)

    @_command(Status.logged_out)
    def login(self):
        self._updates = []
        self._status = Status.active
        self._working_time = timedelta()
        self._slack_message(MORNING_MESSAGE)
        self._log("logged in")
        self._initiate_followup()

    @_command(Status.active)
    def update(self, content):
        self._slack_message(UPDATE_MESSAGE)
        self._log("work update: " + content)
        self._updates.append(content)
        self._timer.cancel()
        self._working_time += datetime.now() - self._timer_start_time
        self._initiate_followup()

    @_command(Status.active)
    def pause(self):
        self._status = Status.paused
        self._pause_time = datetime.now()
        self._timer.cancel()
        self._slack_message(PAUSE_MESSAGE)
        self._log("paused for break")

    @_command(Status.paused)
    def resume(self):
        self._status = Status.active
        self._initiate_followup(self._pause_time - self._timer_start_time)
        self._slack_message(RESUME_MESSAGE)
        self._log("resumed working")

    @_command(Status.active, Status.paused)
    def logout(self):
        final_time = datetime.now() if self._status is Status.active else self._pause_time
        self._working_time += final_time - self._timer_start_time
        self._slack_message(LOGOUT_MESSAGE)
        self._log("logged out")
        self._status = Status.logged_out
        self._timer.cancel()
        self._relay_stats()

    @_command(Status.active, Status.paused)
    def get_work_time(self):
        ending_time = datetime.now() if self._status is Status.active else self._pause_time
        time_worked = self._working_time + (ending_time - self._timer_start_time)
        self._slack_message("You have worked for {} hours".format(str(time_worked)[:-10]))

    def _relay_stats(self):
        """
        Sends a file mentioning session information to the user and the admins
        """
        tasks = "\n".join(map(lambda x: " => " + x.replace("\n", "\n    "), self._updates))
        slack_client.api_call("files.upload",
                              channels=",".join(UPDATE_RECEIVERS.union(['@' + self.name])),
                              content=STATS_MESSAGE.format(tasks=tasks, date=datetime.now().date(),
                                                           hours=str(self._working_time)[:-10]),
                              filename=self.name + "_stats.txt")

    def handle_command(self, user_input):
        """
        Receives a command directed at the bot and determines if it is valid. If so, acts on it.
        If not, returns back what it needs for clarification.
        """
        tokens = user_input.split(None, 1)
        if tokens:
            with self._lock:
                func = getattr(self, tokens[0].lower(), None)
                if callable(func) and hasattr(func, 'is_command'):
                    func(*tokens[1:])
                else:
                    self._slack_message(INVALID_INPUT)

    del _command


def parse_slack_output(json_list):
    """
    Parses slack output to extract all messages not sent by the bot itself
    :param json_list: A list of json objects for slack messages
    :return: A list of pairs of the ID of the user sending the message, and the text of the message
    """
    message_pairs = []
    for json in json_list:
        if json and 'text' in json and 'user' in json and json['user'] != BOT_ID:
            message_pairs.append((json['user'], json['text']))
    return message_pairs


def slack_connect(retry_delay):
    while not slack_client.rtm_connect():
        print("Unable to connect. Retrying...")
        time.sleep(retry_delay)
    print("StarterBot connected and running at " + str(datetime.now())[:-7])


def save_and_quit(_, __):
    """
    Saves the state of each logged-in user in status/user_id.bin and quits the program
    """
    for user in users.values():
        if user.status is not Status.logged_out:
            with open("status/" + user.id + ".bin", "wb") as status_file:
                pickle.dump(user, status_file, pickle.HIGHEST_PROTOCOL)
    sys.exit()


def load_users():
    """
    Loads state corresponding to each file in 'status/' folder, and starts new session for each file
    not present in it. Deletes all files in the 'status/' folder before quitting.
    """
    for user_data in slack_client.api_call("users.list")['members']:
        if not user_data['deleted']:
            user_id = user_data['id']
            try:
                with open("status/" + user_id + ".bin", "rb") as status_file:
                    users[user_id] = pickle.load(status_file)
                    print("Restored session information of " + user_data['name'])
            except (FileNotFoundError, IOError, EOFError):
                users[user_id] = User(user_data)
                print("Reset session for " + user_data['name'])

    for filename in os.listdir("status"):
        os.remove("status/" + filename)


if __name__ == "__main__":
    load_users()
    signal.signal(signal.SIGINT, save_and_quit)

    slack_connect(1)
    while True:
        try:
            for uid, command in parse_slack_output(slack_client.rtm_read()):
                users[uid].handle_command(command)
            time.sleep(0.5)
        except Exception as e:
            print(e)
            slack_connect(1)
