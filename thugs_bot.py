import sqlite3,datetime, telebot

admin_usernames =['Hammerloaf','mikeythug1','SensoryYard']
bot = telebot.TeleBot("1314718679:AAFXwfK5fTfdwGseYVYqoBCW5jw9HE2poF4", parse_mode='MARKDOWN') # You can set parse_mode by default. HTML or MARKDOWN

""" 
CREATE TABLE BOUNTY(
   ID_BOUNTY INTEGER PRIMARY KEY     AUTOINCREMENT,
   NAME_BOUNTY    CHAR(50) UNIQUE      NOT NULL,	
   VALUE          INTEGER            NOT NULL,
   TIME_LIMIT     DATE           NOT NULL,
   ACTIVE         BOOLEAN        DEFAULT TRUE     
);


CREATE TABLE USERS(
   ID_USER INTEGER PRIMARY KEY AUTOINCREMENT,
   NAME    CHAR(50) UNIQUE NOT NULL,
   SHARE_NB INTEGER    NOT NULL
);



CREATE TABLE PARTICIPATION(
   ID_USER INTEGER  PRIMARY KEY  NOT NULL,
   ID_BOUNTY INTEGER   NOT NULL,
   FOREIGN KEY(ID_USER) REFERENCES USERS(ID_USER),
   FOREIGN KEY(ID_BOUNTY) REFERENCES BOUNTY(ID_BOUNTY)
);
 """

@bot.message_handler(commands=['grant'])
def grant(message):
    if(message.from_user.username in admin_usernames):
        conn = sqlite3.connect('thugsDB.db')
        c = conn.cursor()
        #get the args
        args = str(message.text).split()
        name = args[1].replace('@', '')
        share = args[2]
        #create new entry in the USERS table
        sqlite_insert_with_param = "INSERT INTO USERS (NAME,SHARE_NB) VALUES (?, ?);"
        data_tuple = (name,share)
        try:
            c.execute(sqlite_insert_with_param, data_tuple)
        except sqlite3.Error as e:
            print(e)
            bot.reply_to(message, "Wrong answer! Try again")
            exit()
        conn.commit()
        resp = "Welcome " + name + "! You have " + str(share) + " shares!"
        bot.reply_to(message, resp)
        #conn.close()
    else:
        bot.reply_to(message, "🙅‍♂️ You're not an admin!")

@bot.message_handler(commands=['addbounty'])
def addbounty(message):
    if(message.from_user.username in admin_usernames):
        try:
            conn = sqlite3.connect('thugsDB.db')
            c = conn.cursor()
            #get the args
            args = str(message.text).split()
            bounty_name = args[1]
            bounty_amount = args[2]
            bounty_time_limit =args[3]
            #get the date in a proper format
            """ d, m, y = [int(x) for x in bounty_time_limit.split('/')] 
            date = datetime.date(y,m,d) """
            time_now = datetime.datetime.now()
            print(time_now) 
            updated_time  = time_now + datetime.timedelta(minutes=30)
            print(updated_time) 
            sqlite_insert_with_param = "INSERT INTO BOUNTY(NAME_BOUNTY,VALUE,TIME_LIMIT) VALUES (?, ?, ?);"
            data_tuple = (bounty_name,bounty_amount,updated_time)
            try:
                c.execute(sqlite_insert_with_param, data_tuple)
            except sqlite3.Error as e:
                print(e)
                exit()
            conn.commit()
            resp = 'The bounty "' + bounty_name + '" is created with a budget of ' + str(bounty_amount) + ' shares! ' + 'End in ' + str(bounty_time_limit) + ' minutes !!!'
            bot.reply_to(message, resp)
            #conn.close()
        except:
            bot.reply_to(message, "🙅‍♂️ Wrong answer! Try again")
    else:
        bot.reply_to(message, "🙅‍♂️ You're not an admin!")

@bot.message_handler(commands=['endbounty'])
def endbounty(message):
    if(message.from_user.username in admin_usernames):
        try:
            conn = sqlite3.connect('thugsDB.db')
            c = conn.cursor()

            #get the args
            args = str(message.text).split()
            bounty_name = args[1]

            #get the id
            sqlite_insert_with_param = "SELECT ID_BOUNTY FROM BOUNTY WHERE NAME_BOUNTY=?;"
            data_tuple = (bounty_name,)
            c.execute(sqlite_insert_with_param, data_tuple)
            id = c.fetchone()

            #Update the bounty
            sqlite_insert_with_param = "DELETE FROM PARTICIPATION WHERE ID_BOUNTY = ?;"
            data_tuple = id
            try:
                c.execute(sqlite_insert_with_param, data_tuple)
            except sqlite3.Error as e:
                bot.reply_to(message, e)
                exit()

            #Update the participating users
            sqlite_insert_with_param = "UPDATE BOUNTY SET ACTIVE = FALSE WHERE ID_BOUNTY = ?;"
            data_tuple = id
            try:
                c.execute(sqlite_insert_with_param, data_tuple)
            except sqlite3.Error as e:
                bot.reply_to(message, e)
                exit()
            
            #save and code
            conn.commit()
            #conn.close()
            bot.reply_to(message, "This bounty is ended!")
        except:
            bot.reply_to(message, "Wrong answer! Try again")
    else:
        bot.reply_to(message, "🙅‍♂️ You're not an admin!")

@bot.message_handler(commands=['onthejob'])
def onthejob(message):
    try:
        conn = sqlite3.connect('thugsDB.db')
        c = conn.cursor()
        #get the args
        args = str(message.text).split()
        bounty_name = args[1]
        username = message.from_user.username
        print(username)
        print(bounty_name)

        #get the id of the bounty
        sqlite_insert_with_param = "SELECT ID_BOUNTY FROM BOUNTY WHERE NAME_BOUNTY=?"
        data_tuple = (bounty_name,)
        try:
            c.execute(sqlite_insert_with_param, data_tuple)
            id_bounty = c.fetchone()
        except:
            bot.reply_to(message, "Didn't find the id of this bounty")
            exit()
            
        #Check if the bounty is open
        sqlite_insert_with_param = "SELECT ACTIVE FROM BOUNTY WHERE ID_BOUNTY=?"
        data_tuple = id_bounty
        try:
            c.execute(sqlite_insert_with_param, data_tuple)
            active = c.fetchone()
        except:
            bot.reply_to(message, "Couldn't check if the bounty is active")
            exit()
        if (not active[0]):
            bot.reply_to(message,"The bounty is not active anymore!")
            exit()

        #get the id of the user 
        sqlite_insert_with_param = "SELECT ID_USER FROM USERS WHERE NAME=?"
        data_tuple = (username,)
        c.execute(sqlite_insert_with_param, data_tuple)
        id_user = c.fetchone()

        #Get the max date of the bounty
        sqlite_insert_with_param = "SELECT TIME_LIMIT FROM BOUNTY WHERE ID_BOUNTY=?"
        data_tuple = id_bounty
        try:
            c.execute(sqlite_insert_with_param, data_tuple)
            time_limit = c.fetchone()
        except:
            bot.reply_to(message, "Didn't find the time limit of this bounty")
            exit()

        #Check the time limit
        
        #limit = datetime.datetime.strptime(time_limit,'%Y-%m-%d').date()
        present = datetime.datetime.today()
        #print(time_limit[0])
        #print(present)
        time_max = datetime.datetime.strptime(time_limit[0], '%Y-%m-%d %H:%M:%S.%f')
        #print(time_max>present)
        if (time_max>present):
            sqlite_insert_with_param = "INSERT INTO PARTICIPATION(ID_USER,ID_BOUNTY) VALUES (?, ?);"
            data_tuple = (id_user[0],id_bounty[0])
            try:
                c.execute(sqlite_insert_with_param, data_tuple)
            except sqlite3.Error as e:
                print(e)
                exit()
            print("Added")
            sqlite_insert_with_param = "UPDATE USERS SET SHARE_NB = SHARE_NB + 1 WHERE ID_USER = ?;"
            data_tuple = (id_user)
            try:
                c.execute(sqlite_insert_with_param, data_tuple)
            except sqlite3.Error as e:
                print(e)
                exit()
            print("Share Added")
            bot.reply_to(message, "Registered! You will earn 1 share!")
        else:
            print("Impossible to register to this bounty (check the date)")
        #save and code
        conn.commit()
    except:
        bot.reply_to(message, "🙅‍♂️ Wrong answer! 🤷‍♂️")

@bot.message_handler(commands=['leaderboard'])
def leaderboard(message):
    try:   
        conn = sqlite3.connect('thugsDB.db')
        c = conn.cursor()
        string = "Leaderboard \n\n"
        res = c.execute("select name,share_nb from users ORDER BY share_nb DESC;")
        #print(res.fetchall)
        for row in res:
            string = string + row[0] + " | " + str(row[1]) + "\n"
        #conn.close()
        print(string)
        bot.reply_to(message, string)
    except:
        bot.reply_to(message, "🙅‍♂️ Wrong answer! Try again")

@bot.message_handler(commands=['highfive'])
def highfive(message):
    try:
        args = str(message.text).split()
        conn = sqlite3.connect('thugsDB.db')
        c = conn.cursor()
        username_receiver = args[1].replace('@', '')
        print(username_receiver)
        #username_sender,username_receiver
        username_sender = message.from_user.username
        #get the id of the username_sender 
        sqlite_insert_with_param = "SELECT ID_USER FROM USERS WHERE NAME=?;"
        data_tuple = (username_sender,)
        c.execute(sqlite_insert_with_param, data_tuple)
        id_user_sender = c.fetchone()

        #get the id of the username_receiver
        sqlite_insert_with_param = "SELECT ID_USER FROM USERS WHERE NAME=?;"
        data_tuple = (username_receiver,)
        c.execute(sqlite_insert_with_param, data_tuple)
        id_user_receiver = c.fetchone()

        print(id_user_receiver[0])
        if(id_user_receiver[0] != id_user_sender[0]):
            sqlite_insert_with_param = "UPDATE USERS SET SHARE_NB = SHARE_NB + 1 WHERE ID_USER = ?;"
            data_tuple = (id_user_receiver)
            try:
                c.execute(sqlite_insert_with_param, data_tuple)
            except sqlite3.Error as e:
                print(e)
                exit()
            print("Share Added")
            response = username_receiver + ' received a share from '+ username_sender +'🤑'
            bot.reply_to(message, response)
            conn.commit()
        else:
            bot.reply_to(message, "Fuck you 🖕 Don't highfive yourself!")
            print("Fuck you 🖕")
    except:
        bot.reply_to(message, "🙅‍♂️ Wrong answer! Try again")

@bot.message_handler(commands=['bountylist'])
def bountylist(message):
    try:   
        conn = sqlite3.connect('thugsDB.db')
        c = conn.cursor()
        string = "Active bounties\n\n"
        res = c.execute("select NAME_BOUNTY from BOUNTY WHERE ACTIVE = TRUE;")
        #print(res.fetchall)
        for row in res:
            string = string + row[0] + "\n"
        #conn.close()
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
if __name__ == "__main__":
    while(True):
        try:
            bot.infinity_polling()
        except:
            pass