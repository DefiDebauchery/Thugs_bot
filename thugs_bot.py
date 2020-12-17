import datetime
import json
import os
import shlex
import sqlite3
import telebot
from collections import defaultdict
from dotenv import load_dotenv
from urllib.request import urlopen, Request

load_dotenv()

if (API_TOKEN := os.getenv('API_KEY_TG')) is None:
    raise EnvironmentError('No API Key defined!')

fallback = {
    'allocation'    : '$100',
    'initial_shares': 10,
    'bump_shares'   : 1,
    'otj_shares'    : 1
}

runtime = {
    'users'        : defaultdict(dict),
    'bounties'     : defaultdict(dict),
    'participation': defaultdict(list), # List
    'settings'     : fallback
}

strings = {
    'general_error'     : "I had an issue processing this request. I've logged the error.",
    'unknown_user'      : "Yo, who the fuck are you? Did you forget to /register?",
    'unknown_target'    : "Sorry, I don't know who that is!",
    'self_grant'        : "🖕 Fuck you - don't give shares to yourself!",
    'self_bump'         : "🖕 Fuck you - you can't fistbump yourself!",
    'participating'     : "Hey asshole, did you forget? You're already part of this bounty!",
    'not_participating' : "Did you bump your head? You're not even part of this bounty!",
    'bounty_full'       : "Sorry, we have all the muscle we need for this job.",
    'bounty_value_error': "Could not add the bounty: Share value must be a positive number!",
    'bounty_limit_error': "Could not add the bounty: Provide a positive number of minutes!"
}

admin_usernames = ['Hammerloaf', 'mikeythug1', 'SensoryYard', '@DefiDebauchery']
dev_usernames = ['SensoryYard', '@DefiDebauchery']
bot = telebot.TeleBot(API_TOKEN, parse_mode='Markdown')

def admin_command(f):
    def wrapper(*args, **kwargs):
        message = args[0]
        if is_admin(message.from_user):
            return f(*args, **kwargs)
        else:
            bot.reply_to(message, "🙅‍♂️ This is an administrator command!!")

    return wrapper

def num_arguments(required=0):
    def outer_wrapper(f):
        def wrapper(*args, **kwargs):
            message = args[0]
            if len(shlex.split(fix_quotes(message.text))) == required + 1:
                return f(*args, **kwargs)
            else:
                bot.reply_to(message, f"🙅‍♂️ This command requires exactly {pluralize(required, 'argument')}! "
                                      f"Wrap quotes around text with spaces!")

        return wrapper

    return outer_wrapper

def is_admin(user: telebot.types.User):
    return runtime['users'].get(user.id, {}).get('is_admin', 0) or parse_user(user) in admin_usernames

def find_bounty_by_name(bounty_name, require_active=True) -> dict:
    if require_active:
        res = [item for item in runtime['bounties'].values() if item['name'] == bounty_name and item['is_active']]
    else:
        res = [item for item in runtime['bounties'].values() if item['name'] == bounty_name]

    return next(iter(res), None)

def find_user_by_name(search):
    results = [user for user in runtime['users'].values() if user['username'] == search]

    return next(iter(results), None)

def now():
    return int(datetime.datetime.now().timestamp())

def display_time(seconds, granularity=2):
    intervals = (
        ('wks', 604800),  # 60 * 60 * 24 * 7
        ('days', 86400),  # 60 * 60 * 24
        ('hrs', 3600),  # 60 * 60
        ('mins', 60),
        ('sec', 1),
    )
    result = []

    for name, count in intervals:
        value = seconds // count
        if value:
            seconds -= value * count
            if value == 1:
                name = name.rstrip('s')
            result.append("{} {}".format(value, name))
    return ', '.join(result[:granularity])

def parse_int(val):
    try:
        val = int(val)
    except ValueError:
        val = None

    return val

def parse_mention(message: telebot.types.Message):
    if len(message.entities) < 2:
        return None

    entity = message.entities[1]

    if entity.type == 'text_mention':
        return entity.user.first_name

    return message.text[entity.offset + 1:entity.offset + entity.length]

def parse_user(user: telebot.types.User):
    return user.username or user.first_name

def pluralize(amount, string):
    return f"{amount} {string}" + ('s' if amount != 1 else '')

def fix_quotes(text):
    return text.translate({0x201c: '"', 0x201d: '"', 0x2018: "'", 0x2019: "'"})

def indexof(lst, idx):
    try:
        res = lst[idx]
    except IndexError:
        res = None

    return res

def get_setting(key):
    return runtime['settings'].get(key, None)

def escape_username(username):
    return username.replace("_", "\\_").replace("*", "\\*")

@bot.message_handler(commands=['help'])
def help_message(message):
    resp = """
Interacting with the Bounty system:

*User Commands*:
`/register` |  Initial registration
`/leaderboard` |  Show the Leaderboard
`/bountylist` | List the active Bounties
`/onthejob {bounty}` | Register for an active Bounty
`/abandon {bounty}` | Concede participation from an active Bounty
`/bump {@User}` | Fistbump and add a share to a user
"""
    if is_admin(message.from_user):
        resp += """
*Admin Commands*:
`/grant {@User} {shares}` | Grant Shares
`/addbounty {"name"} {cred_value} {time_limit}` | Add a new Bounty
`/endbounty {"name"|id}` | End a Bounty
`/cashout {@User} {shares}` | Redeem Shares for User
`/audit {id}` | Show stats for Bounty
`/showlog {@User}` | Show Balance changes
"""

    bot.reply_to(message, resp, parse_mode='Markdown')

@bot.message_handler(commands=['register'])
def register(message):
    user_id = message.from_user.id
    if (username := message.from_user.username) is None:
        username = message.from_user.first_name

    esc_username = escape_username(username)

    if user_id in runtime['users']:
        return bot.reply_to(message, f"{esc_username}, you're already registered!")

    shares = get_setting('initial_shares')
    created_at = now()

    # create new entry in the users table
    sqlite_insert_with_param = "INSERT INTO users (telegram_id, username, shares, created_at) VALUES (?,?,?,?);"
    data_tuple = (user_id, username, shares, created_at)
    try:
        c = db.cursor()
        c.execute(sqlite_insert_with_param, data_tuple)
        db.commit()
    except sqlite3.IntegrityError:
        # Somehow already exists, but not accounted for. We'll pretend they're new
        pass
    except sqlite3.Error as e:
        print('register', e)
        return bot.reply_to(message, strings['general_error'])

    runtime['users'][user_id] = {'telegram_id': user_id, 'username': username, 'shares': shares,
                                 'created_at' : created_at}

    add_log(user_id, user_id, 'reg', shares)

    resp = f"Welcome {esc_username}! We've granted you {pluralize(shares, 'share')}!"
    bot.reply_to(message, resp)

@bot.message_handler(commands=['addbounty'])
@admin_command
@num_arguments(3)
def addbounty(message):
    # Replace smart quotes and treat them as a single argument
    args = shlex.split(fix_quotes(message.text))

    bounty_name = args[1]

    # Filter bounty dict by keys to determine whether we have a current bounty
    if find_bounty_by_name(bounty_name) is not None:
        return bot.reply_to(message, "This bounty already exists!")

    if not (bounty_amount := parse_int(args[2])) or bounty_amount < 1:
        return bot.reply_to(message, strings['bounty_value_error'])

    if not (bounty_time_limit := parse_int(args[3])) or bounty_time_limit < 1:
        return bot.reply_to(message, strings['bounty_limit_error'])

    end_time = datetime.datetime.now() + datetime.timedelta(minutes=bounty_time_limit)
    end_time = int(end_time.timestamp())
    created_at = now()

    sqlite_insert_with_param = "INSERT INTO bounties(name, worth, endtime, created_at) VALUES (?, ?, ?, ?);"
    data_tuple = (bounty_name, bounty_amount, end_time, created_at)
    try:
        c = db.cursor()
        c.execute(sqlite_insert_with_param, data_tuple)
        bounty_id = c.lastrowid
        db.commit()
    except sqlite3.IntegrityError as e:
        print('addbounty integrity error', e)
        return bot.reply_to(message, strings['general_error'])
    except sqlite3.Error as e:
        print('addbounty general error', e)
        return bot.reply_to(message, strings['general_error'])

    runtime['bounties'][bounty_id] = {'bounty_id': bounty_id, 'name': bounty_name, 'worth': bounty_amount,
                                      'endtime'  : end_time, 'is_active': True, 'created_at': created_at}

    response = f"""
*NEW BOUNTY!*

ID {bounty_id}: `{bounty_name}` now has {pluralize(bounty_amount, 'open spot')} for willing muscle.
This bounty is open for {display_time(bounty_time_limit * 60)}. GO GO GO!
"""

    bot.send_message(message.chat.id, response)

@bot.message_handler(commands=['endbounty'])
@admin_command
@num_arguments(1)
def endbounty(message):
    # get the args
    args = shlex.split(fix_quotes(message.text))
    bounty_name = args[1]

    bounty_id = parse_int(bounty_name)

    if bounty_id:
        if (bounty := runtime['bounties'].get(bounty_id)) is None:
            return bot.reply_to(message, f"Bounty ID {bounty_id} does not exist!")
    else:
        if bounty := find_bounty_by_name(bounty_name):
            bounty_id = bounty['bounty_id']
        else:
            return bot.reply_to(message, f"There is no open bounty called `{bounty_name}`!")

    try:
        remove_bounty(bounty)
    except Exception as e:
        print('endbounty', e)
        return bot.reply_to(message, strings['general_error'])

    runtime['bounties'][bounty_id]['is_active'] = False
    runtime['bounties'][bounty_id]['endtime'] = now()

    bot.reply_to(message, "This bounty is ended!")

@bot.message_handler(commands=['audit'])
@admin_command
@num_arguments(1)
def audit(message):
    bounty_id = parse_int(message.text.split()[1])

    if bounty_id:
        if (bounty := runtime['bounties'].get(bounty_id)) is None:
            return bot.reply_to(message, f"Bounty ID {bounty_id} does not exist!")
    else:
        return bot.reply_to(message, f"I don't know anything about Bounty ID {bounty_id}.")

    running_time = f"Ends in {display_time(bounty['endtime'] - now())}" if (
                bounty['is_active'] and bounty['endtime'] > now()) \
        else f"Ran for {display_time(bounty['endtime'] - bounty['created_at'])}"

    participation_list = [escape_username(runtime['users'][k]['username']) for k in
                          runtime['participation'][bounty_id] if k in runtime['users']]

    response = f"""
Bounty {bounty['bounty_id']}:  `{bounty['name']}`
Created {str(datetime.datetime.fromtimestamp(bounty['created_at']))}
{running_time}

Muscle ({len(participation_list)}/{bounty['worth']}): {', '.join(participation_list)}
"""

    bot.reply_to(message, response)

@bot.message_handler(commands=['showlog'])
@admin_command
@num_arguments(1)
def showlog(message):
    username = parse_mention(message)

    if (target_user := find_user_by_name(username)) is None:
        return bot.reply_to(message, strings['unknown_target'])

    query = "SELECT IIF(from_id = to_id, '<Self>', u.username) AS username, " \
            "IIF(subject, action || ' (' || subject || ')', action) as action, amount, at FROM log " \
            "INNER JOIN users u ON u.telegram_id = from_id " \
            "WHERE to_id = ? ORDER BY at DESC LIMIT 15"

    cursor = db.cursor()
    cursor.execute(query, (target_user['telegram_id'],))

    results = [dict(row) for row in cursor.fetchall()]

    if not len(results):
        return bot.reply_to(message, f"No logs for this user")

    maxlength = {
        'username': len(max(results, key=lambda x: len(x['username']))['username']),
        'action'  : len(max(results, key=lambda x: len(x['action']))['action']),
        'amount'  : len(str(max(results, key=lambda x: len(str(x['amount'])))['amount']))
    }

    table = f"{'From'.ljust(maxlength['username'])} | {'Act'.ljust(maxlength['action'])} | {'$'.ljust(maxlength['amount'])} | {'Time'.ljust(12)}\n"
    table += "=" * (len(table) - 1) + "\n"
    for row in results:
        table += f"{row['username'].center(maxlength['username'])} | " \
                 f"{row['action'].ljust(maxlength['action'])} | " \
                 f"{str(row['amount']).ljust(maxlength['amount'])} | " \
                 f"{datetime.datetime.fromtimestamp(row['at']).strftime('%b-%d %H:%M')}\n"

    response = f"""
Last 15 Updates for {escape_username(target_user['username'])}

```
{table}
```
"""
    bot.reply_to(message, response)

@bot.message_handler(commands=['onthejob'])
@num_arguments(1)
def onthejob(message):
    # get the args
    args = str(message.text).split()
    bounty_name = ' '.join(args[1:])  # Don't require quotes since it's a single argument
    user_id = message.from_user.id
    shares = get_setting('otj_shares')

    if (user := runtime['users'].get(user_id)) is None:
        return bot.reply_to(message, strings['unknown_user'])

    if bounty_id := parse_int(bounty_name):
        if (bounty := runtime['bounties'].get(bounty_id, None)) is None:
            return bot.reply_to(message, f"Bounty ID {bounty_id} does not exist!")
    else:
        if (bounty := find_bounty_by_name(bounty_name)) is None:
            return bot.reply_to(message, f"There is no open bounty named `{bounty_name}`!")

    if not bounty['is_active']:
        return bot.reply_to(message, 'This bounty has ended!')

    # If we get this far, the bounty is still active and we'll disable it
    if bounty['endtime'] < now():
        remove_bounty(bounty)
        return bot.reply_to(message, 'This bounty has ended!')

    if (bounty_participation := runtime['participation'][bounty['bounty_id']]) and user_id in bounty_participation:
        return bot.reply_to(message, strings['participating'])

    if len(bounty_participation) >= bounty['worth']:
        return bot.reply_to(message, strings['bounty_full'])

    c = db.cursor()
    sqlite_insert_with_param = "INSERT INTO participation(telegram_id, bounty_id) VALUES (?, ?);"
    data_tuple = (user_id, bounty['bounty_id'])
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.IntegrityError as e:
        print('onthejob', e)
        return
    except sqlite3.Error as e:
        print('onthejob general', e)
        return

    sqlite_insert_with_param = "UPDATE users SET shares = shares + ? WHERE telegram_id = ?;"
    data_tuple = (shares, user_id)
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.Error as e:
        print(e)
        return

    db.commit()
    user['shares'] += shares
    bounty_participation.append(user_id)

    add_log(user_id, user_id, 'otj', shares, bounty['bounty_id'])
    return bot.reply_to(message,
                        f"Thanks for taking on `{bounty['name']}`! You've earned {pluralize(shares, 'share')}!")

@bot.message_handler(commands=['abandon'])
def abandon(message):
    # get the args
    args = str(message.text).split()
    bounty_name = ' '.join(args[1:])  # Don't require quotes since it's a single argument
    user_id = message.from_user.id
    shares = get_setting('otj_shares')

    if (user := runtime['users'].get(user_id)) is None:
        return bot.reply_to(message, strings['unknown_user'])

    if bounty_id := parse_int(bounty_name):
        if (bounty := runtime['bounties'].get(bounty_id, None)) is None:
            return bot.reply_to(message, f"Bounty ID {bounty_id} does not exist!")
    else:
        if (bounty := find_bounty_by_name(bounty_name)) is None:
            return bot.reply_to(message, f"There is no open bounty named `{bounty_name}`!")

    if not bounty['is_active']:
        return bot.reply_to(message, 'This bounty has ended!')

    # If we get this far, the bounty is still active and we'll disable it
    if bounty['endtime'] < now():
        remove_bounty(bounty)
        return bot.reply_to(message, 'This bounty has ended!')

    bounty_participation = runtime['participation'][bounty['bounty_id']]
    if user_id not in bounty_participation:
        return bot.reply_to(message, strings['not_participating'])

    c = db.cursor()
    sqlite_insert_with_param = "DELETE FROM participation WHERE telegram_id = ? AND bounty_id = ?"
    data_tuple = (user_id, bounty['bounty_id'])
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.IntegrityError as e:
        print('abandon', e)
        return
    except sqlite3.Error as e:
        print('abandon general', e)
        return

    sqlite_insert_with_param = "UPDATE users SET shares = shares - ? WHERE telegram_id = ?;"
    data_tuple = (shares, user_id)
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.Error as e:
        print(e)
        return

    db.commit()
    user['shares'] -= shares
    bounty_participation.remove(user_id)

    add_log(user_id, user_id, 'aban', -shares, bounty['bounty_id'])
    return bot.reply_to(message, f"A real G knows when they're in over their head. "
                                 f"You've left the bounty `{bounty['name']}` and the shares have been removed.")

@bot.message_handler(commands=['leaderboard'])
def leaderboard(message):
    if not len(runtime['users']):
        return bot.reply_to(message, 'There are currently no registered users!')

    maxlength = len(max(runtime['users'].values(), key=lambda x: len(x['username']))['username'])
    totalshares = sum((map(lambda x: x['shares'], runtime['users'].values())))
    users = sorted(runtime['users'].values(), key=lambda item: item['shares'], reverse=True)

    user_list = f"{'User'.ljust(maxlength)} | Joined | Shares (%)\n"
    user_list += "=" * (len(user_list)-1) + "\n"
    for user in users:
        user_list += f"{user['username'].ljust(maxlength)} | " \
                     f"{datetime.datetime.fromtimestamp(user['created_at']).strftime('%b %d')} | " \
                     f"{user['shares']} ({round(user['shares'] / totalshares * 100, 2)}%)\n"

    response = f"""
*Reward Allocation*: {creds_invested()}
*Total Shares*: {totalshares}

```
{user_list}
```
"""

    bot.send_message(message.chat.id, response)

@bot.message_handler(commands=['bump'])
@num_arguments(1)
def bump(message: telebot.types.Message):
    target = parse_mention(message)

    if (target_user := find_user_by_name(target)) is None:
        return bot.reply_to(message, strings['unknown_target'])

    """
    username_receiver = bot.get_chat_member(-445263888,username_receiver).user.id
    id_user_receiver = bot.get_chat_member(-445263888,message.from_user.id).user.id
    print("username_receiver from db",username_receiver)
    print("id_user_receiver from db",username_receiver)
    """

    if target_user['telegram_id'] == message.from_user.id:
        return bot.reply_to(message, strings['self_bump'])

    shares = get_setting('bump_shares')

    c = db.cursor()
    sqlite_insert_with_param = "UPDATE users SET shares = shares + ? WHERE telegram_id = ?;"
    data_tuple = (shares, target_user['telegram_id'])
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.IntegrityError as e:
        print('bump integrity', e)
        return
    except sqlite3.Error as e:
        print('bump general', e)
        return bot.reply_to(message, strings['general_error'])

    db.commit()

    target_user['shares'] += shares
    add_log(message.from_user.id, target_user['telegram_id'], 'bump', shares)

    response = f"{escape_username(parse_user(message.from_user))} 🤜💥🤛 {escape_username(target_user['username'])}!\n" \
               f"{pluralize(shares, 'share')} added!"
    bot.send_message(message.chat.id, response)

@bot.message_handler(commands=['bountylist'])
def bountylist(message):
    bounties = {key: val for key, val in runtime['bounties'].items() if val['is_active'] and val['endtime'] > now()}

    if not len(bounties):
        return bot.reply_to(message, "There are no active bounties at this time.")

    bounty_list = "ID: Name" + " ↳ Space | Time left\n".rjust(23)
    for bounty_id, bounty in bounties.items():
        space_left = bounty['worth'] - len(runtime['participation'][bounty['bounty_id']])
        availability = f"{space_left}/{bounty['worth']}" if space_left else "Full!"

        bounty_list += f"{bounty['bounty_id']}: {bounty['name']} \n"
        bounty_list += f"{availability} | {display_time(bounty['endtime'] - now())}".rjust(31) + "\n"

    response = f"""
*Active bounties*

```
{bounty_list.rstrip()}
```
Join a bounty using `/onthejob [ID]`
"""
    bot.send_message(message.chat.id, response)

@bot.message_handler(commands=['config'])
@admin_command
def config(message):
    args = shlex.split(fix_quotes(message.text))

    if len(args) < 2:
        return bot.reply_to(message, "Use `get <key>`, `set <key> <val>`, or `show`")

    if args[1] == 'get':
        value = runtime['settings'].get(indexof(args, 2), u"¯\\\_(ツ)\_/¯")
        return bot.reply_to(message, f"`{escape_username(value)}")

    if args[1] == 'set':
        if (key := indexof(args, 2)) is None or (val := indexof(args, 3)) is None:
            return bot.reply_to(message, f"Please set a value for `{key}`!")

        c = db.cursor()
        query = 'INSERT INTO settings (setting_name, setting_value) VALUES (?,?) ' \
                'ON CONFLICT(setting_name) DO UPDATE SET setting_value=excluded.setting_value'
        data = (key, val)
        try:
            c.execute(query, data)
            db.commit()
        except sqlite3.Error as e:
            print('config error', e)
            return bot.reply_to(message, f"There was an error applying the config for `{key}` :(")

        runtime['settings'][key] = val
        return bot.reply_to(message, f"Setting saved for `{key}`")

    if args[1] == 'show':
        maxlen_k = (len(max(runtime['settings'].keys(), key=lambda x: len(x))))
        maxlen_v = (len(max(runtime['settings'].values(), key=lambda x: len(str(x)))))

        if maxlen_v > 20:
            maxlen_v = 20

        setting_list = f"{'Setting'.ljust(maxlen_k)} | {'Value'.ljust(maxlen_v)}\n"
        setting_list += "=" * (len(setting_list)-1) + "\n"

        for k, v in runtime['settings'].items():
            v = str(v)
            setting_list += f"{k.ljust(maxlen_k)} | {v if len(v) <= 20 else v[:17] + '...'}\n"

        response = f"""
*Current Runtime Configuration*

```
{setting_list.rstrip()}
```
        """
        return bot.send_message(message.chat.id, response)

    bot.reply_to(message, "Uh, your choices are `get`, `set`, or `show`. Don't get cute.")

def remove_bounty(bounty: dict):
    c = db.cursor()

    # Not sure we need to actually remove participation; could be used as a log
    # Keeping updated code just in case
    #
    # sqlite_insert_with_param = "DELETE FROM participation WHERE bounty_id = ?;"
    # data_tuple = (bounty_id,)
    # try:
    #     c.execute(sqlite_insert_with_param, data_tuple)
    # except sqlite3.Error as e:
    #     print(e)
    #     return bot.reply_to(message, strings['general_error'])
    # except ValueError as e:
    #     print(e)
    #     return bot.reply_to(message, strings['general_error'])
    # Update the participating users
    sqlite_insert_with_param = "UPDATE bounties SET endtime = ? AND is_active = FALSE WHERE bounty_id = ?;"
    data_tuple = (now(), bounty['bounty_id'],)
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.IntegrityError as e:
        print('remove_bounty integrity', e)
        raise Exception(e)
    except sqlite3.Error as e:
        print('remove_bounty error', e)
        raise Exception(e)

    # save and code
    db.commit()

@bot.message_handler(commands=['grant'])
@admin_command
@num_arguments(2)
def grant(message):
    target = parse_mention(message)
    args = str(message.text).split()

    if (target_user := find_user_by_name(target)) is None:
        return bot.reply_to(message, strings['unknown_target'])

    if target_user['telegram_id'] == message.from_user.id:
        return bot.reply_to(message, strings['self_grant'])

    if not (shares := parse_int(args[-1])) or shares < 0:
        return bot.reply_to(message, 'Grant a positive number of shares!')

    c = db.cursor()
    sqlite_insert_with_param = "UPDATE users SET shares = shares + ? WHERE telegram_id = ?;"
    data_tuple = (shares, target_user['telegram_id'])
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.Error as e:
        print('grant', e)
        return bot.reply_to(message, strings['general_error'])

    db.commit()

    target_user['shares'] += shares
    add_log(message.from_user.id, target_user['telegram_id'], 'gr', shares)

    response = f"{escape_username(target_user['username'])} received {pluralize(shares, 'share')} from {escape_username(parse_user(message.from_user))} 🤑"
    bot.send_message(message.chat.id, response)

@bot.message_handler(commands=['cashout'])
@admin_command
@num_arguments(2)
def cashout(message):
    target = parse_mention(message)
    args = str(message.text).split()

    if (target_user := find_user_by_name(target)) is None:
        return bot.reply_to(message, strings['unknown_target'])

    if not (shares := parse_int(args[-1])) or shares < 0:
        return bot.reply_to(message, 'Cash out a positive number of shares!')

    if target_user['shares'] < shares:
        return bot.reply_to(message, f"That bitch is too poor! Max cashout amount is {target_user['shares']}.")

    c = db.cursor()
    sqlite_insert_with_param = "UPDATE users SET shares = shares - ? WHERE telegram_id = ?;"
    data_tuple = (shares, target_user['telegram_id'])
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.Error as e:
        print('cashout', e)
        return bot.reply_to(message, strings['general_error'])

    db.commit()

    add_log(message.from_user.id, target_user['telegram_id'], '$out', -shares)

    target_user['shares'] -= shares
    response = f"{target_user['username']} took the money and ran! 🤑\n" \
               f"{pluralize(shares, 'share')} redeemed, with {pluralize(target_user['shares'], 'share')} left."
    bot.reply_to(message, response)

def add_log(from_id, to_id, action, value, subject=''):
    c = db.cursor()
    log_query = "INSERT INTO log VALUES (?,?,?,?,?,?)"
    data = (from_id, to_id, action, subject, value, now())
    try:
        c.execute(log_query, data)
    except sqlite3.Error as e:
        print('logging error', e)
        for username in dev_usernames:
            if cur_user := find_user_by_name(username):
                bot.send_message(cur_user['telegram_id'], 'Just so you know, I had an issue with logging...')
                bot.send_message(cur_user['telegram_id'], e)

    db.commit()

def creds_invested():
    return get_setting('allocation')

def setup():
    db.cursor().execute('''
        CREATE TABLE IF NOT EXISTS bounties (
            bounty_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(50) NOT NULL,	
            worth INTEGER NOT NULL,
            endtime DATE NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at DATE NOT NULL
        );
    ''')

    db.cursor().execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY NOT NULL,
            username VARCHAR(50) NOT NULL,
            shares INTEGER NOT NULL,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at DATE NOT NULL
        ); 
    ''')

    db.cursor().execute('''
        CREATE TABLE IF NOT EXISTS participation (
            telegram_id INTEGER NOT NULL,
            bounty_id INTEGER NOT NULL,
            FOREIGN KEY(telegram_id) REFERENCES users(telegram_id),
            FOREIGN KEY(bounty_id) REFERENCES bounties(bounty_id)
        );
    ''')

    db.cursor().execute('''
        CREATE TABLE IF NOT EXISTS log (
            from_id INTEGER NOT NULL,
            to_id INTEGER NOT NULL,
            action VARCHAR(20) NOT NULL,
            subject VARCHAR(50) NOT NULL,
            amount INTEGER NOT NULL,
            at DATE NOT NULL
        );
    ''')
    db.cursor().execute('''
        CREATE TABLE IF NOT EXISTS settings (
            setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_name VARCHAR(50) UNIQUE NOT NULL,
            setting_value VARCHAR(255) NOT NULL
        )
    ''')

    cursor = db.cursor()
    cursor.execute("SELECT * FROM bounties")
    for row in cursor.fetchall():
        runtime['bounties'][row['bounty_id']] = dict(row)

    cursor = db.cursor()
    cursor.execute('SELECT * FROM users')
    for row in cursor.fetchall():
        runtime['users'][row['telegram_id']] = dict(row)

    cursor = db.cursor()
    cursor.execute('SELECT * FROM participation')
    for row in cursor.fetchall():
        runtime['participation'][row['bounty_id']] += [row['telegram_id']]

    cursor = db.cursor()
    cursor.execute('SELECT * FROM settings')
    for row in cursor.fetchall():
        runtime['settings'][row['setting_name']] = row['setting_value']

def script_exit():
    db.close()

if __name__ == "__main__":
    try:
        db = sqlite3.connect('thugsDB.db', check_same_thread=False)
        db.row_factory = sqlite3.Row

        setup()
        bot.infinity_polling()
    finally:
        script_exit()
