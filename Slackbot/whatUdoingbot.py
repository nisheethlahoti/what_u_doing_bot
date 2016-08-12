import os
import time
import threading
from slackclient import SlackClient
from datetime import datetime

# our starterbot's ID
BOT_ID = ""  # TODO: Should be the bot's UID

username_list = []  # TODO: Should be list of usernames to work with
expecting_work_update = [False, False]
# constants
AT_BOT = "<@" + BOT_ID + ">:"
delay_between_message = 5
EXAMPLE_COMMAND = "record"
FOLLOWUP_TIME = 30
login_time = [datetime.now().time(), datetime.now().time()]  # TODO - Properly initiate this list to store datetime equal to size of channel_id


# String
HELLO_JARVIS = "login"
MORNING_MESSAGE = "Good morning. Let's start creating awesome sound experiences. Have a great day!"
REQUEST_FOR_UPDATE = "Hey, just checking up. Can you let me know what have you been doing?"
INVALID_INPUT = "Not sure what you mean. Type help to get possible commands"

# channel constants
channel_id = []  # TODO: Should be list of channel IDs corresponding to username_list
channel_id_name = username_list

# instantiate Slack & Twilio clients
slack_client = SlackClient("")  # TODO: Should have the slack token


def periodic_check():
    while True:
        slack_client.api_call("chat.postMessage", channel=username_list[0], text="Kaam karo, timepass nahi :P",
                              as_user=True)
        time.sleep(delay_between_message)


def find_user(input_channel):
    count = 0
    for a in channel_id:
        if a == input_channel:
            break
        else:
            count += 1
    return count


def send_im(user_id, text):
    slack_client.api_call("chat.postMessage", channel=channel_id_name[user_id],
                          text=text, as_user=True)


def timely_followup(user_id):
    global expecting_work_update

    # The hourly check loop
    if expecting_work_update[user_id]:
        send_im(user_id, REQUEST_FOR_UPDATE)
        # TODO - Add for options for break and end of day

    # The user just started working. First login of the day
    else:
        expecting_work_update[user_id] = True
        login_time[user_id] = datetime.now().time()
        print "Login id of " + channel_id_name[user_id] + " is " + str(login_time[user_id])
    threading.Timer(FOLLOWUP_TIME, lambda: timely_followup(user_id)).start()


def handle_command(command, channel):
    """
        Receives commands directed at the bot and determines if they
        are valid commands. If so, then acts on the commands. If not,
        returns back what it needs for clarification.
    """
    global expecting_work_update
    user_id = find_user(channel)

    # TODO - Implement help function
    if expecting_work_update[user_id]:
        if command.startswith("update"):
            print "Work Update from " + username_list[user_id] + " is " + command  # TODO - Save the time, user_id, and work update in a database, not just print on terminal
        # expecting_work_update[user_id] = False


    else:
        if command == HELLO_JARVIS:
            response = MORNING_MESSAGE
            slack_client.api_call("chat.postMessage", channel=channel,
                                  text=response, as_user=True)
            timely_followup(user_id)
        else:
            response = INVALID_INPUT
            slack_client.api_call("chat.postMessage", channel=channel,
                                  text=response, as_user=True)


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


# TODO - Now that we have the login time, we need to code the bot to ask the user for what he/she has done say 1 minute every login time. How do we keep a count of time? (python asynch future programming)
if __name__ == "__main__":
    READ_WEBSOCKET_DELAY = 1  # 1 second delay between reading from firehose
    if slack_client.rtm_connect():
        print("StarterBot connected and running!")
        # periodic_check()
        while True:
            command, channel = parse_slack_output(slack_client.rtm_read())
            if command and channel:
                handle_command(command, channel)
            time.sleep(READ_WEBSOCKET_DELAY)
    else:
        print("Connection failed. Invalid Slack token or bot ID?")
