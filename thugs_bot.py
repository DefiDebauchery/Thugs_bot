import sqlite3
import datetime
import shlex
import telebot
import os
from dotenv import load_dotenv
from collections import defaultdict
from unidecode import unidecode

load_dotenv()

if (API_TOKEN := os.getenv('API_KEY_TG')) is None:
    raise EnvironmentError('No API Key defined!')

runtime = {
    'users'        : defaultdict(dict),
    'bounties'     : defaultdict(dict),
    'participation': defaultdict(list),
    'settings'     : defaultdict(dict)
}

fallback = {
    'initial_shares': 10,
    'bump_shares'   : 1,
    'otj_shares'    : 1
}

strings = {
    'general_error'     : "I had an issue processing this request. I've logged the error.",
    'unknown_user'      : "Yo, who the fuck are you? Did you forget to /register?",
    'unknown_target'    : "Sorry, I don't know who that is!",
    'self_grant'        : "🖕 Fuck you - don't give shares to yourself!",
    'self_bump'         : "🖕 Fuck you - you can't bump yourself!",
    'participating'     : "Hey asshole, did you forget? You're already part of this bounty!",
    'not_participating' : "Did you bump your head? You're not even part of this bounty!",
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
            if len(shlex.split(unidecode(message.text))) == required + 1:
                return f(*args, **kwargs)
            else:
                bot.reply_to(message, f"🙅‍♂️ This command requires exactly {required} arguments! "
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
"""

    bot.reply_to(message, resp, parse_mode='Markdown')

@bot.message_handler(commands=['register'])
def register(message):
    user_id = message.from_user.id
    if (username := message.from_user.username) is None:
        username = message.from_user.first_name

    if user_id in runtime['users']:
        return bot.reply_to(message, f"{username}, you're already registered!")

    shares = runtime['settings'].get('initial_shares', fallback['initial_shares'])

    # create new entry in the users table
    sqlite_insert_with_param = "INSERT INTO users (telegram_id,username,shares) VALUES (?,?,?);"
    data_tuple = (user_id, username, shares)
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

    runtime['users'][user_id] = {'telegram_id': user_id, 'username': username, 'shares': shares}

    add_log(user_id, user_id, 'register', shares)

    resp = f"Welcome {username}! You have {str(shares)} shares!"
    bot.reply_to(message, resp)

@bot.message_handler(commands=['addbounty'])
@admin_command
@num_arguments(3)
def addbounty(message):
    # Replace smart quotes and treat them as a single argument
    args = shlex.split(unidecode(message.text))

    bounty_name = args[1]

    # Filter bounty dict by keys to determine whether we have a current bounty
    if find_bounty_by_name(bounty_name) is not None:
        return bot.reply_to(message, "This bounty already exists!")

    if not (bounty_amount := parse_int(args[2])) or bounty_amount < 1:
        return bot.reply_to(message, strings['bounty_value_error'])

    if not (bounty_time_limit := parse_int(args[3])) or bounty_time_limit < 1:
        return bot.reply_to(message, strings['bounty_limit_error'])

    # try:
    #     bounty_amount = int(args[2])
    #     if bounty_amount < 1:
    #         raise ValueError
    # except ValueError:
    #     return bot.reply_to(message, strings['bounty_value_error'])
    #
    # try:
    #     bounty_time_limit = int(args[3])
    #     if bounty_time_limit < 1:
    #         raise ValueError
    # except ValueError:
    #     bot.reply_to(message, "Could not add the bounty: Provide a positive number of minutes!")
    #     return
    # parse the date in unix timestamp
    """ d, m, y = [int(x) for x in bounty_time_limit.split('/')] 
    date = datetime.date(y,m,d) """
    updated_time = datetime.datetime.now() + datetime.timedelta(minutes=bounty_time_limit)
    updated_time = int(updated_time.timestamp())

    sqlite_insert_with_param = "INSERT INTO bounties(name, worth, endtime) VALUES (?, ?, ?);"
    data_tuple = (bounty_name, bounty_amount, updated_time)
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
                                      'endtime'  : updated_time, 'is_active': True}

    resp = f"Bounty {bounty_id}, `{bounty_name}`, is created with a budget of {str(bounty_amount)} shares! " \
           f"Signup ends in {str(bounty_time_limit)} minutes!"
    bot.reply_to(message, resp)

@bot.message_handler(commands=['endbounty'])
@admin_command
@num_arguments(1)
def endbounty(message):
    # get the args
    args = shlex.split(unidecode(message.text))
    bounty_name = args[1]
    bounty_id = 0

    bounty_id = parse_int(bounty_id)

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

    runtime['participation'].pop(bounty_id, None)
    runtime['bounties'][bounty_id]['is_active'] = False

    bot.reply_to(message, "This bounty is ended!")

@bot.message_handler(commands=['onthejob'])
@num_arguments(1)
def onthejob(message):
    # get the args
    args = str(message.text).split()
    bounty_name = ' '.join(args[1:])  # Don't require quotes since it's a single argument
    user_id = message.from_user.id
    shares = runtime['settings'].get('otj_shares', fallback['otj_shares'])

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

    print(bounty_participation)

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

    add_log(user_id, user_id, 'onthejob', shares)
    return bot.reply_to(message, f"Thanks for taking on `{bounty['name']}`! You earned {shares} share(s)!")

@bot.message_handler(commands=['abandon'])
def abandon(message):
    # get the args
    args = str(message.text).split()
    bounty_name = ' '.join(args[1:])  # Don't require quotes since it's a single argument
    user_id = message.from_user.id
    shares = runtime['settings'].get('otj_shares', fallback['otj_shares'])

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

    add_log(user_id, user_id, 'abandon', -shares)
    return bot.reply_to(message, f"A real G knows when they're in over their head. "
                                 f"You've left the bounty `{bounty['name']}` and the shares have been removed.")

@bot.message_handler(commands=['leaderboard'])
def leaderboard(message):
    if not len(runtime['users']):
        return bot.reply_to(message, 'There are currently no registered users!')

    maxlength = len(max(runtime['users'].values(), key=lambda x: len(x['username']))['username'])
    users = sorted(runtime['users'].values(), key=lambda item: item['shares'], reverse=True)

    user_list = f"{'User'.ljust(maxlength, ' ')} | Shares\n"
    user_list += "=" * len(user_list) + "\n"
    for user in users:
        user_list += f"{user['username'].ljust(maxlength, ' ')} | {user['shares']}\n"

    response = f"""
*Total Allocation*: {creds_invested()} CRED
*Amount Available*: ?

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

    shares = runtime['settings'].get('bump_shares', fallback['bump_shares'])

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

    sql = "INSERT INTO bumps (from_id, to_id, at) VALUES (?,?,?)"
    data_tuple = (message.from_user.id, target_user['telegram_id'], now())
    try:
        c.execute(sql, data_tuple)
    except sqlite3.Error as e:
        print('bump', e)
        return bot.reply_to(message, strings['general_error'])

    db.commit()

    target_user['shares'] += shares
    add_log(message.from_user.id, target_user['telegram_id'], 'bump', shares)

    response = f"{parse_user(message.from_user)} 🤜💥🤛 {target_user['username']}!  {shares} share(s) added!"
    bot.send_message(message.chat.id, response)

@bot.message_handler(commands=['bountylist'])
def bountylist(message):
    bounties = {key: val for key, val in runtime['bounties'].items() if val['is_active'] and val['endtime'] > now()}

    if not len(bounties):
        return bot.reply_to(message, "There are no active bounties at this time.")

    bounty_list = "Name (ID) | Bounty | Signup ends\n"
    for bounty_id, bounty in bounties.items():
        bounty_list += f"{bounty['name']} (ID {bounty['bounty_id']}) | {bounty['worth']} CRED | {display_time(bounty['endtime'] - now())}\n"

    response = f"""
*Active bounties*

{bounty_list}
Join a bounty using `/onthejob [ID / Name]`
"""
    bot.send_message(message.chat.id, response)

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
    sqlite_insert_with_param = "UPDATE bounties SET is_active = FALSE WHERE bounty_id = ?;"
    data_tuple = (bounty['bounty_id'],)
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

    add_log(message.from_user.id, target_user['telegram_id'], 'grant', shares)

    response = f"{target_user['username']} received {shares} shares from {parse_user(message.from_user)} 🤑"
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

    add_log(message.from_user.id, target_user['telegram_id'], 'cashout', -shares)

    target_user['shares'] -= shares
    response = f"{target_user['username']} took the money and ran! 🤑\n" \
               f"{shares} shares redeemed, with {target_user['shares']} left."
    bot.reply_to(message, response)

def add_log(from_id, to_id, action, value):
    c = db.cursor()
    log_query = "INSERT INTO log VALUES (?,?,?,?,?)"
    data = (from_id, to_id, action, value, now())
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
    c = db.cursor()
    c.execute("select sum(worth) from bounties;")
    result = c.fetchone()
    return result[0]

def setup():
    db.cursor().execute('''
        CREATE TABLE IF NOT EXISTS bounties (
            bounty_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(50) NOT NULL,	
            worth INTEGER NOT NULL,
            endtime DATE NOT NULL,
            is_active BOOLEAN DEFAULT TRUE     
        );
    ''')

    db.cursor().execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY NOT NULL,
            username VARCHAR(50) NOT NULL,
            shares INTEGER NOT NULL,
            is_admin BOOLEAN DEFAULT FALSE
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
            amount INTEGER NOT NULL,
            at DATE NOT NULL
        );
    ''')
    db.cursor().execute('''
        CREATE TABLE IF NOT EXISTS settings (
            setting_id INTEGER NOT NULL,
            setting_name VARCHAR(50) UNIQUE NOT NULL,
            setting_value VARCHAR(255) NOT NULL
        )
    ''')

    cursor = db.cursor()
    cursor.execute("SELECT * FROM bounties WHERE endtime < date('now') and is_active = TRUE")
    for row in cursor.fetchall():
        runtime['bounties'][row['bounty_id']] = dict(row)

    cursor = db.cursor()
    cursor.execute('SELECT * FROM users')
    for row in cursor.fetchall():
        runtime['users'][row['telegram_id']] = dict(row)

    cursor = db.cursor()
    cursor.execute('SELECT * FROM participation '
                   'INNER JOIN bounties b on participation.bounty_id = b.bounty_id '
                   'WHERE is_active = TRUE')
    for row in cursor.fetchall():
        runtime['participation'][row['bounty_id']] += [row['telegram_id']]

    cursor = db.cursor()
    cursor.execute('SELECT * FROM settings')
    for row in cursor.fetchall():
        runtime['settings'][row['setting_name']] = dict(row)

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
