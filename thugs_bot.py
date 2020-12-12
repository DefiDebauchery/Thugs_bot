import sqlite3
import datetime
import shlex
import telebot
import os
from dotenv import load_dotenv
from unidecode import unidecode

load_dotenv()

API_TOKEN = os.getenv('API_KEY_TG')
if API_TOKEN is None:
    raise EnvironmentError('No API Key defined!')

runtime = {
    'users'        : {},
    'bounties'     : {},
    'participation': {},
    'settings'     : {}
}

fallback = {
    'shares': 10
}

strings = {
    'general_error': "I had an issue processing this request. I've logged the error."
}

admin_usernames = ['Hammerloaf', 'mikeythug1', 'SensoryYard', '@DefiDebauchery']
bot = telebot.TeleBot(API_TOKEN, parse_mode='Markdown')

def admin_command(f):
    def wrapper(*args, **kwargs):
        message = args[0]
        if is_admin(message.from_user):
            return f(*args, **kwargs)
        else:
            bot.reply_to(message, "🙅‍♂️ This is an administrator command!!")

    return wrapper

def is_admin(user: telebot.types.User):
    return runtime['users'].get(user.id, {}).get('is_admin', 0)

@bot.message_handler(commands=['help'])
def help_message(message):
    resp = """
Interacting with the Bounty system:

*User Commands*:
`/register` |  Initial registration
`/leaderboard` |  Show the Leaderboard
`/bountylist` | List the active Bounties
`/onthejob {bounty}` | Register for an active Bounty
`/highfive {@User}` | Send a share to a User
"""
    if is_admin(message.from_user):
        resp += """
*Admin Commands*:
`/grant {@User} {cred}` | Grant CRED
`/addbounty {"name"} {cred_value} {time_limit}` | Add a new Bounty
`/endbounty {"name"|id}` | End a Bounty
"""

    bot.reply_to(message, resp, parse_mode='Markdown')

@bot.message_handler(commands=['register'])
def register(message):
    user_id = message.from_user.id
    username = message.from_user.username
    if username is None:
        username = message.from_user.first_name

    if user_id in runtime['users']:
        bot.reply_to(message, f"{username}, you're already registered!")
        return

    shares = runtime['settings'].get('initial_shares', fallback['shares'])

    # create new entry in the users table
    sqlite_insert_with_param = "INSERT INTO users (telegram_id,username,shares) VALUES (?,?,?);"
    data_tuple = (user_id, username, shares)
    try:
        c = db.cursor()
        c.execute(sqlite_insert_with_param, data_tuple)
        db.commit()
    except sqlite3.IntegrityError as e:
        # Somehow already exists, but not accounted for. We'll pretend they're new
        pass
    except sqlite3.Error as e:
        print(e)
        bot.reply_to(message, strings['general_error'])
        return

    runtime['users'][user_id] = {'username': username, 'shares': shares}

    resp = f"Welcome {username}! You have {str(shares)} shares!"
    bot.reply_to(message, resp)

@bot.message_handler(commands=['addbounty'])
@admin_command
def addbounty(message):
    # Replace smart quotes and treat them as a single argument
    args = shlex.split(unidecode(message.text))
    bounty_name = args[1]

    # Filter bounty dict by keys to determine whether we have a current bounty
    search = dict(filter(lambda elem: elem[0] == bounty_name, runtime['bounties'].items()))
    if len(search):
        bot.reply_to(message, "This bounty already exists!")
        return

    try:
        bounty_amount = int(args[2])
        if bounty_amount < 1:
            raise ValueError
    except ValueError:
        bot.reply_to(message, "Could not add the bounty: The value must be a positive number!")
        return

    try:
        bounty_time_limit = int(args[3])
        if bounty_time_limit < 1:
            raise ValueError
    except ValueError:
        bot.reply_to(message, "Could not add the bounty: Provide a positive number of minutes!")
        return

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
    except sqlite3.Error as e:
        print(e)
        bot.reply_to(message, strings['general_error'])
        return

    runtime['bounties'][bounty_name] = {'bounty_id': bounty_id, 'worth': bounty_amount, 'endtime': updated_time, 'is_active': True}

    resp = f"The bounty `{bounty_name}` is created with a budget of {str(bounty_amount)} CRED! Signup ends in {str(bounty_time_limit)} minutes!"
    bot.reply_to(message, resp)

@bot.message_handler(commands=['endbounty'])
@admin_command
def endbounty(message):
    # get the args
    args = shlex.split(unidecode(message.text))
    bounty_name = args[1]
    bounty_id = 0

    print(bounty_name)

    try:
        bounty_id = int(bounty_name)
    except ValueError:
        pass

    if bounty_id:
        if runtime['bounties'].get(bounty_id, None) is None:
            bot.reply_to(message, f"Bounty ID {bounty_id} does not exist!")
            return
    else:
        search = dict(filter(lambda elem: elem[1].get('name', '') == bounty_name, runtime['bounties'].items()))
        if len(search):
            bounty_id = search[0]['bounty_id']
        else:
            bot.reply_to(message, f"The bounty `{bounty_name}` does not exist!")
            return

    c = db.cursor()

    # Update the bounty
    sqlite_insert_with_param = "DELETE FROM participation WHERE bounty_id = ?;"
    data_tuple = (bounty_id,)
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.Error as e:
        print(e)
        bot.reply_to(message, strings['general_error'])
        return
    except ValueError as e:
        print(e)
        bot.reply_to(message, strings['general_error'])
        return

    # Update the participating users
    sqlite_insert_with_param = "UPDATE bounties SET is_active = false WHERE bounty_id = ?;"
    data_tuple = (bounty_id,)
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.Error as e:
        print(e)
        bot.reply_to(message, strings['general_error'])
        return
    except ValueError as e:
        print(e)
        bot.reply_to(message, strings['general_error'])
        return

    runtime['participation'].pop(bounty_id, None)
    runtime['bounties'][bounty_id]['is_active'] = False

    db.commit()
    bot.reply_to(message, "This bounty is ended!")

@bot.message_handler(commands=['onthejob'])
def onthejob(message):
    if message.from_user.username is None:
        bot.reply_to(message, "🙅‍♂️ You don't have an @")
        exit()
    try:
        c = db.cursor()
        # get the args
        args = str(message.text).split()
        bounty_name = args[1]
        id_user = message.from_user.id
        print(id_user)
        print(bounty_name)

        # get the id of the bounty
        sqlite_insert_with_param = "SELECT bounty_id FROM bounties WHERE name=?"
        data_tuple = (bounty_name,)
        try:
            c.execute(sqlite_insert_with_param, data_tuple)
            id_bounty = c.fetchone()
        except:
            bot.reply_to(message, "Didn't find the id of this bounty")
            exit()

        # Check if the bounty is open
        sqlite_insert_with_param = "SELECT is_active FROM bounties WHERE bounty_id=?"
        data_tuple = id_bounty
        try:
            c.execute(sqlite_insert_with_param, data_tuple)
            active = c.fetchone()
        except:
            bot.reply_to(message, "Couldn't check if the bounty is active")
            exit()
        if (not active[0]):
            bot.reply_to(message, "The bounty is not active anymore!")
            exit()

        # get the id of the user
        sqlite_insert_with_param = "SELECT telegram_id FROM users WHERE telegram_id=?"
        data_tuple = (id_user,)
        c.execute(sqlite_insert_with_param, data_tuple)
        id_user = c.fetchone()

        # Get the max date of the bounty
        sqlite_insert_with_param = "SELECT endtime FROM bounties WHERE bounty_id=?"
        data_tuple = id_bounty
        try:
            c.execute(sqlite_insert_with_param, data_tuple)
            time_limit = c.fetchone()
        except:
            bot.reply_to(message, "Didn't find the time limit of this bounty")
            exit()

        # Check the time limit
        # limit = datetime.datetime.strptime(time_limit,'%Y-%m-%d').date()
        present = datetime.datetime.today()
        # print(time_limit[0])
        # print(present)
        time_max = datetime.datetime.strptime(time_limit[0], '%Y-%m-%d %H:%M:%S.%f')
        # print(time_max>present)
        if (time_max > present):
            sqlite_insert_with_param = "INSERT INTO participation(telegram_id,bounty_id) VALUES (?, ?);"
            data_tuple = (id_user[0], id_bounty[0])
            try:
                c.execute(sqlite_insert_with_param, data_tuple)
            except sqlite3.Error as e:
                print(e)
                exit()
            print("Added")
            sqlite_insert_with_param = "UPDATE users SET shares = shares + 1 WHERE telegram_id = ?;"
            data_tuple = (id_user)
            try:
                c.execute(sqlite_insert_with_param, data_tuple)
            except sqlite3.Error as e:
                print(e)
                exit()
            print("Share Added")
            bot.reply_to(message, "Registered! You earned 1 share!")
        else:
            bot.reply_to(message, "Impossible to register to this bounty (check the date)")
            del_bounty(str(bounty_name))
        # save and code
        db.commit()
    except:
        bot.reply_to(message, "🙅‍♂️ Wrong answer! 🤷‍♂️")

@bot.message_handler(commands=['leaderboard'])
def leaderboard(message):
    try:
        conn = sqlite3.connect('thugsDB.db')
        c = conn.cursor()
        string = "*Amount Invested by the team* : {0} Creds\n\n".format(creds_invested())
        string = string + "*Amount Available now in the fund* :SOON\n\n"
        string = string + "*Leaderboard* \n\n"
        res = c.execute("select username,shares from users ORDER BY shares DESC;")
        # print(res.fetchall)
        for row in res:
            string = string + row[0] + " | " + str(row[1]) + "\n"
        # conn.close()
        print(string)
        bot.reply_to(message, string)
    except:
        bot.reply_to(message, "🙅‍♂️ Wrong answer! Try again", parse_mode='Markdown')

@bot.message_handler(commands=['highfive'])
def highfive(message):
    if message.from_user.username == None:
        bot.reply_to(message, "🙅‍♂️ You don't have an @")
        exit()
    try:
        args = str(message.text).split()
        c = db.cursor()
        username_receiver = args[1].replace('@', '')
        # username_receiver = message.entities[1]
        print("username_receiver from text", username_receiver)
        # parsed_user = message.parse_entity(username_receiver)
        # username_receiver = message.caption_entities[0].user.id
        # print("username_receiver from text",parsed_user)
        """
        username_receiver = bot.get_chat_member(-445263888,username_receiver).user.id
        id_user_receiver = bot.get_chat_member(-445263888,message.from_user.id).user.id
        print("username_receiver from db",username_receiver)
        print("id_user_receiver from db",username_receiver)
        """
        # username_sender,username_receiver
        id_user_sender = message.from_user.id

        # get the id of the username_sender
        sqlite_insert_with_param = "SELECT username FROM users WHERE telegram_id=?;"
        data_tuple = (id_user_sender,)
        c.execute(sqlite_insert_with_param, data_tuple)
        name_user_sender = c.fetchone()
        print(name_user_sender)

        # get the id of the username_receiver
        sqlite_insert_with_param = "SELECT telegram_id FROM users WHERE username=?;"
        data_tuple = (username_receiver,)
        c.execute(sqlite_insert_with_param, data_tuple)
        id_user_receiver = c.fetchone()

        print(id_user_receiver)
        print(id_user_sender)
        if (id_user_receiver[0] != id_user_sender):
            print('TEST')
            sqlite_insert_with_param = "UPDATE users SET shares = shares + 1 WHERE telegram_id = ?;"
            data_tuple = id_user_receiver
            try:
                c.execute(sqlite_insert_with_param, data_tuple)
            except sqlite3.Error as e:
                print(e)
                exit()
            print("Share Added")
            response = username_receiver + ' received a share from ' + name_user_sender[0] + '🤑'
            bot.reply_to(message, response)
            db.commit()
        else:
            bot.reply_to(message, "Fuck you 🖕 Don't highfive yourself!")
            print("Fuck you 🖕")
    except:
        bot.reply_to(message, "🙅‍♂️ Wrong answer! Try again")

@bot.message_handler(commands=['bountylist'])
def bountylist(message):
    try:
        c = db.cursor()
        string = "Active bounties\n\n"
        res = c.execute("select name from bounties WHERE is_active = TRUE;")
        # print(res.fetchall)
        for row in res:
            string = string + row[0] + "\n"
        # conn.close()
        print(string)

        bot.reply_to(message, string)
    except:
        bot.reply_to(message, "🙅‍♂️ Wrong answer! Try again")

""" if __name__ == "__main__":
    #grant("SensoryYard", 10)
    #addbounty("Test2", 100, '15/12/2020')
    #onthejob("Test2","SensoYard3")
    #grant("SensoYard4", 10)
    #leaderboard()
    #highfive('SensoYard2','SensoYard3')
 """

def del_bounty(bounty_name):
    c = db.cursor()
    # get the args
    """    
    args = str(message).split()
    bounty_name = args[1] """
    print("bounty_name", bounty_name)
    # get the id
    sqlite_insert_with_param = "SELECT bounty_id FROM bounties WHERE name=?;"
    data_tuple = (bounty_name,)
    c.execute(sqlite_insert_with_param, data_tuple)
    id = c.fetchone()

    # Update the bounty
    sqlite_insert_with_param = "DELETE FROM PARTICIPATION WHERE bounty_id = ?;"
    data_tuple = id
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.Error as e:
        print(e)
        exit()

    # Update the participating users
    sqlite_insert_with_param = "UPDATE bounties SET is_active = FALSE WHERE bounty_id = ?;"
    data_tuple = id
    try:
        c.execute(sqlite_insert_with_param, data_tuple)
    except sqlite3.Error as e:
        print(e)
        exit()

    # save and code
    db.commit()
    # conn.close()

@bot.message_handler(commands=['grant'])
@admin_command
def grant(message):
    if (message.from_user.username == None):
        bot.reply_to(message, "🙅‍♂️ You don't have an @")
        exit()

    try:
        args = str(message.text).split()
        conn = sqlite3.connect('thugsDB.db')
        c = conn.cursor()
        username_receiver = args[1].replace('@', '')
        amount = int(args[2])
        print(amount)
        print("username_receiver from text", username_receiver)
        """
        username_receiver = bot.get_chat_member(-445263888,username_receiver).user.id
        id_user_receiver = bot.get_chat_member(-445263888,message.from_user.id).user.id
        print("username_receiver from db",username_receiver)
        print("id_user_receiver from db",username_receiver)
        """
        # username_sender,username_receiver
        id_user_sender = message.from_user.id

        # get the id of the username_sender
        sqlite_insert_with_param = "SELECT username FROM users WHERE telegram_id=?;"
        data_tuple = (id_user_sender,)
        c.execute(sqlite_insert_with_param, data_tuple)
        name_user_sender = c.fetchone()
        print(name_user_sender)

        # get the id of the username_receiver
        sqlite_insert_with_param = "SELECT telegram_id FROM users WHERE username=?;"
        data_tuple = (username_receiver,)
        c.execute(sqlite_insert_with_param, data_tuple)
        id_user_receiver = c.fetchone()

        print(id_user_receiver)
        print(id_user_sender)
        if (id_user_receiver[0] != id_user_sender):
            print('TEST')
            id = id_user_receiver[0]
            print(id)
            sqlite_insert_with_param = "UPDATE users SET shares = shares + ? WHERE telegram_id = ?;"
            data_tuple = (amount, id)
            try:
                c.execute(sqlite_insert_with_param, data_tuple)
            except sqlite3.Error as e:
                print(e)
                exit()
            print("Share Added")
            print(name_user_sender[0])
            response = username_receiver + " received " + str(amount) + " shares from " + name_user_sender[0] + '🤑'
            bot.reply_to(message, response)
            conn.commit()
        else:
            bot.reply_to(message, "Fuck you 🖕 Don't give shares to yourself!")
    except:
        bot.reply_to(message, "🙅‍♂️ Wrong answer! Try again")

def creds_invested():
    conn = sqlite3.connect('thugsDB.db')
    c = conn.cursor()
    c.execute("select sum(worth) from bounties;")
    result = c.fetchone()
    print(result[0])
    return result[0]


def setup():
    db.cursor().execute('''
        CREATE TABLE IF NOT EXISTS bounties (
            bounty_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(50) UNIQUE NOT NULL,	
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

    db.cursor().execute('SELECT * FROM participation '
                        'INNER JOIN bounties b on participation.bounty_id = b.bounty_id '
                        'WHERE is_active = TRUE')
    for row in db.cursor().fetchall():
        runtime['participation'][row['bounty_id']] += [row['telegram_id']]

    db.cursor().execute('SELECT * FROM settings')
    for row in db.cursor().fetchall():
        runtime['settings'][row['setting_name']] = dict(row)

    print(runtime)

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
