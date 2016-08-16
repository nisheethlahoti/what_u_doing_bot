import inspect
import io
import time

from datetime import datetime
from enum import Enum
from slackclient import SlackClient
from threading import Lock, Timer

# our bot's ID
BOT_ID = ""  # TODO: Should be the bot's UID

# constants
FOLLOWUP_TIME = 3

# String
MORNING_MESSAGE = "Good morning. Let's start creating awesome sound experiences. Have a great day!"
REQUEST_FOR_UPDATE = "Hey, just checking up. Can you let me know what have you been doing?"
INVALID_INPUT = "Not sure what you mean. Type help to get possible commands"
NO_ACCEPT_ARGUMENTS = "Don't understand this command if followed by further text :/"

# instantiate Slack & Twilio clients
slack_client = SlackClient("")  # TODO: Should have the slack token


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
    # TODO - Add for options for break and end of day
    # TODO - Implement help function
    def __init__(self, data):
        self.id = data['id']
        self.name = data['name']
        self._status = Status.logged_out
        self._timer_start_time = None
        self._timer = None
        self._pause_time = None
        self._lock = Lock()
        self._log_file = None

    def _log(self, message):
        self._log_file.write(message + '\n')
        self._log_file.flush()

    def _post_message(self, message):
        slack_client.api_call("chat.postMessage", channel=self.id,
                              text=message, as_user=True)

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

    def _timely_followup(self):
        with self._lock:
            if self._status == Status.active:  # Just in case the lock's acquired just after pause
                if self._timer is not None:  # It will be None only during first call at login
                    self._post_message(REQUEST_FOR_UPDATE)
                self._timer_start_time = datetime.now()
                self._timer = Timer(FOLLOWUP_TIME, self._timely_followup)
                self._timer.start()

    @_allowed_status(Status.logged_out)
    @_command
    def login(self):
        self._log_file = open(self.name + ".log", 'a')
        self._status = Status.active
        self._post_message(MORNING_MESSAGE)
        self._log("Login time of " + self.name + " is " + str(datetime.now()))
        Timer(0, self._timely_followup).start()

    @_allowed_status(Status.active)
    @_command
    def update(self, content):
        self._log("Work Update from " + self.name + " is:" + content.replace("\n", "\n\t"))

    @_allowed_status(Status.active)
    @_command
    def pause(self):
        self._status = Status.paused
        self._pause_time = datetime.now()
        self._timer.cancel()
        self._log(self.name + " has paused work at " + str(self._pause_time))

    @_allowed_status(Status.paused)
    @_command
    def resume(self):
        self._status = Status.active
        timer_done = (self._pause_time-self._timer_start_time).total_seconds()
        self._timer = Timer(FOLLOWUP_TIME-timer_done, self._timely_followup)
        self._timer_start_time = datetime.now()
        self._log(self.name + " has resumed work at " + str(self._timer_start_time))
        self._timer.start()

    @_allowed_status(Status.active, Status.paused)
    @_command
    def logout(self):
        self._log("Logout time of " + self.name + " is " + str(datetime.now()))
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


if __name__ == "__main__":
    users = {}
    for user_data in slack_client.api_call("users.list")['members']:
        users[user_data['id']] = User(user_data)

    if slack_client.rtm_connect():
        print("StarterBot connected and running!")
        while True:
            uid, command = parse_slack_output(slack_client.rtm_read())
            if uid in users:
                users[uid].handle_command(command)
            time.sleep(1)  # 1 second delay between reading from firehose
    else:
        print("Connection failed. Invalid Slack token or bot ID?")
