import inspect
import time
import threading

from datetime import datetime
from slackclient import SlackClient

# our bot's ID
BOT_ID = ""  # TODO: Should be the bot's UID

# constants
FOLLOWUP_TIME = 30

# String
MORNING_MESSAGE = "Good morning. Let's start creating awesome sound experiences. Have a great day!"
REQUEST_FOR_UPDATE = "Hey, just checking up. Can you let me know what have you been doing?"
INVALID_INPUT = "Not sure what you mean. Type help to get possible commands"
LOGIN_REQUIRED = "You have to be logged in to use this command!"
LOGOUT_REQUIRED = "Can't do this when already logged in!"
NO_ACCEPT_ARGUMENTS = "Don't understand this command if followed by further text :/"

# instantiate Slack & Twilio clients
slack_client = SlackClient("")  # TODO: Should have the slack token


class User:
    # TODO - Add for options for break and end of day
    # TODO - Implement help function
    def __init__(self, user_data):
        self.id = user_data['id']
        self.name = user_data['name']
        self._logged_in = False
        self._login_time = None
        self._timer = None

    def _post_message(self, message):
        slack_client.api_call("chat.postMessage", channel=self.id,
                              text=message, as_user=True)

    def _assert_login_status(desired):
        def with_fn(func):
            def with_args(self, *args):
                if self._logged_in == desired:
                    func(self, *args)
                else:
                    self._post_message(LOGIN_REQUIRED if desired else LOGOUT_REQUIRED)
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
        self._post_message(REQUEST_FOR_UPDATE)
        self._timer = threading.Timer(FOLLOWUP_TIME, self._timely_followup)
        self._timer.start()

    @_assert_login_status(False)
    @_command
    def login(self):
        self._logged_in = True
        self._post_message(MORNING_MESSAGE)
        self._login_time = datetime.now()
        self._timer = threading.Timer(FOLLOWUP_TIME, self._timely_followup)
        self._timer.start()
        print("Login time of " + self.name + " is " + str(self._login_time))

    @_assert_login_status(True)
    @_command
    def update(self, content):
        print("Work Update from " + self.name + " is:" + content)

    @_assert_login_status(True)
    @_command
    def logout(self):
        logout_time = datetime.now()
        print("Logout time of " + self.name + " is " + str(logout_time))
        self._logged_in = False
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
