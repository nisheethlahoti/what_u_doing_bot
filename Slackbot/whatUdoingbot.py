import inspect
import time
import threading

from datetime import datetime
from slackclient import SlackClient

# our bot's ID
BOT_ID = ""  # TODO: Should be the bot's UID

# constants
AT_BOT = "<@" + BOT_ID + ">:"
FOLLOWUP_TIME = 30

# String
MORNING_MESSAGE = "Good morning. Let's start creating awesome sound experiences. Have a great day!"
REQUEST_FOR_UPDATE = "Hey, just checking up. Can you let me know what have you been doing?"
INVALID_INPUT = "Not sure what you mean. Type help to get possible commands"
LOGIN_REQUIRED = "You have to be logged in to use this command!"
LOGOUT_REQUIRED = "Can't do this when already logged in!"

# instantiate Slack & Twilio clients
slack_client = SlackClient("")  # TODO: Should have the slack token


class User:
    # TODO - Add for options for break and end of day
    # TODO - Implement help function
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self._logged_in = False
        self._login_time = datetime()
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
            with_args.func_dict = func.func_dict
            return with_args
        return with_fn

    def _command(func):
        def one_argument_fn(self, x):
            if x:
                self.post_message("This command does not take arguments")
            else:
                func(self)
        if inspect.getargspec(func).args.len() == 1:
            func = one_argument_fn
        func.func_dict['command'] = True
        return func

    def _timely_followup(self):
        self._post_message(REQUEST_FOR_UPDATE)
        self._timer = threading.Timer(FOLLOWUP_TIME, self._timely_followup)
        self._timer.start()

    @_command
    @_assert_login_status(False)
    def login(self):
        self._logged_in = True
        self._post_message(MORNING_MESSAGE)
        self._login_time = datetime.now()
        self._timer = threading.Timer(FOLLOWUP_TIME, self._timely_followup)
        self._timer.start()
        print "Login time of " + self.name + " is " + str(self._login_time)

    @_command
    @_assert_login_status(True)
    def update(self, content):
        print "Work Update from " + self.name + " is:" + content

    @_command
    @_assert_login_status(True)
    def logout(self):
        logout_time = datetime.now()
        print "Logout time of " + self.name + " is " + str(logout_time)
        self._logged_in = False
        if self.timer:
            self.timer.cancel()

    def handle_command(self, user_input):
        """
            Receives commands directed at the bot and determines if they
            are valid commands. If so, then acts on the commands. If not,
            returns back what it needs for clarification.
        """
        tokens = user_input.split(None, 1)
        if not tokens:
            self.post_message("Don't know what to do with empty command :(")
        else:
            func = getattr(self, tokens[0], None)
            if callable(func) and func.func_dict['command']:
                func(*tokens[1:])
            else:
                self.post_message(INVALID_INPUT)


users = {User("<uid>", "@<username>"),
         User("<uid>", "@<username>"),
         User("<uid>", "@<username>")}  # TODO: Should be actual uids and usernames


def find_user(user_id):
    return next(x for x in users if x.id == user_id)


def parse_slack_output(slack_rtm_output):
    """
        The Slack Real Time Messaging API is an events firehose.
        this parsing function returns None unless a message is
        directed at the Bot, based on its ID.
    """
    output_list = slack_rtm_output
    if output_list and len(output_list) > 0:
        for output in output_list:
            if output and 'text' in output and AT_BOT in output['text']:
                # return text after the @ mention, whitespace removed
                return output['text'].split(AT_BOT)[1].strip().lower(), \
                       output['channel']
    return None, None


if __name__ == "__main__":
    if slack_client.rtm_connect():
        print("StarterBot connected and running!")
        while True:
            command, channel = parse_slack_output(slack_client.rtm_read())
            if command and channel:
                find_user(channel).handle_command(command)
            time.sleep(1)  # 1 second delay between reading from firehose
    else:
        print("Connection failed. Invalid Slack token or bot ID?")
