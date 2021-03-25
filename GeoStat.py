'''
  Statiscal Analysis for Recreational Geolocation
  Tobin Feldman-Fitzthum, 2021

'''

import os
import requests
import pprint
import sqlite3
import json

from argparse import ArgumentParser
from progressbar import progressbar
from os import path
from getpass import getpass

import pandas as pd
import plotly.express as px

DB_PATH = "GeoData.db"

BASE_URL = "https://www.geoguessr.com"
API_BASE_URL = "{}/api/v3".format(BASE_URL)
USER_ID = "5ef7a86a7410d364c0f3f68e"

MODES = ['scrape','scores_over_time']
SESSION = requests.Session()

def get(url, debug=False):
  if debug:
    print(url)

  headers = {"User-Agent": "GeoStat"}

  r = SESSION.get(url, headers=headers)
  if not r.status_code == 200:
    raise Exception("Could not GET {}".format(url))

  return r

def authenticate():
  email = input("Email: ")
  password = getpass()

  signin_url = "{}/accounts/signin".format(API_BASE_URL)
  data = {"email":email, "password":password}

  SESSION.post(signin_url, data=data)


# Main purpose is to get the user id
def scrape_profile_info():
  profiles_url = "{}/profiles".format(API_BASE_URL)
  return get(profiles_url).json()['user']

# TODO: add paging in case you have a ton of friends
# NOTE: this only works for CHALLENGES (activity type 8)
def scrape_game_data(game_id, user_id):
  start_index = 0
  n_results = 26

  game_result_url = "{}/results/scores/{}/{}/{}?friends" \
      .format(API_BASE_URL, game_id, start_index, n_results)

  r = get(game_result_url)
  all_game_data = r.json()
  for user_score in all_game_data:
    if user_score['userId'] == user_id:
      return user_score

# get game data for a "map" game (activity type 3)
# sadly, there doesn't seem to be any endpoint for this
# this entire function is trash
def scrape_game_data_map(game_id):
  map_game_url = "{}/results/{}".format(BASE_URL, game_id)
  r = get(map_game_url)

  # eww
  data = "{\"game\":" + r.text.split("gamePlayedByCurrentUser\":")[1].split("},\"page\"")[0]
  data = json.loads(data)

  # this json varies slightly from what we get from the results endpoints, thus...
  for setting in data['game']['settings'].keys():
    data['game'][setting] = data['game']['settings'][setting]

  pprint.pprint(data['game'])
  return data


'''
  Gets all the games that you and your friends have played
  from the social feed endpoint.

  We don't really care about friends, but this includes them.
'''
def scrape_game_history():
  page_size = 200
  page_count = 0

  social_feed = []
  while True:
    social_feed_url = "{}/social/feed/?count={}&page={}" \
        .format(API_BASE_URL, page_size, page_count)

    r = get(social_feed_url)

    feed_page = r.json()
    social_feed.extend(feed_page)
    page_count += 1

    if len(feed_page) == 0:
      break

  return social_feed


def db_exists():
  return os.path.exists()

def init_db():
  pass

  con = sqlite3.connect(DB_PATH)
  cur = con.cursor()

  cur.execute('''CREATE TABLE games
                 (game_id text, date text, map_name text, map_slug text, score real,
                  min_lat real, min_lon real, max_lat real, max_lon real,
                  no_move, no_rotate, no_zoom, game_type, time_limit)''')


  cur.execute('''CREATE TABLE rounds
                 (game_id text, map_name text, map_slug text,
                 guess_lat real, guess_lon real, guess_time integer, guess_distance real,
                 loc_lat real, loc_lon real)''')

  con.commit()
  con.close()

def populate_db():
  profile_data = scrape_profile_info()
  user_id = profile_data['id']

  game_feed = scrape_game_history()

  con = sqlite3.connect(DB_PATH)
  cur = con.cursor()

  n = 0
  print('Populating Database')
  for game in progressbar(game_feed):
    if n > 4:
      con.commit()
      con.close()

      return

    # only support "challenges" and "maps" at the moment
    activity_type = game['activityType']
    if not (activity_type == 3 or activity_type == 8):
      continue

    game_id = get_game_id(game)
    game_date = game['dateTime']
    map_name = game['payload']['map']['name']
    map_slug = game['payload']['map']['slug']
    score = get_game_score(game)

    n += 1
    if activity_type == 8:
      game_data = scrape_game_data(game_id, user_id)['game']
    elif activity_type == 3:
      game_data = scrape_game_data_map(game_id)['game']

    min_lat = game_data['bounds']['min']['lat']
    min_lon = game_data['bounds']['min']['lng']
    max_lat = game_data['bounds']['max']['lat']
    max_lon = game_data['bounds']['max']['lng']

    no_move = game_data['forbidMoving']
    no_rotate = game_data['forbidRotating']
    no_zoom = game_data['forbidZooming']
    game_type = game_data['type']
    time_limit = game_data['timeLimit']

    cur.execute('''INSERT INTO games VALUES (?, ?, ?, ?, ?,
                                             ?, ?, ?, ?,
                                             ?, ?, ?, ?, ?)''', \
            (game_id, game_date, map_name, map_slug, score, \
             min_lat, min_lon, max_lat, max_lon, \
             no_move, no_rotate, no_zoom, game_type, time_limit))

    for i in range(5):
      guess = game_data['player']['guesses'][i]
      guess_lat = guess['lat']
      guess_lon = guess['lng']
      guess_time = guess['time']
      guess_distance = guess['distanceInMeters']

      loc = game_data['rounds'][i]
      loc_lat = loc['lat']
      loc_lon = loc['lng']

      cur.execute('''INSERT INTO rounds VALUES (?, ?, ?,
                                                ?, ?, ?, ?,
                                                ?, ?)''', \
                      (game_id, map_name, map_slug, \
                       guess_lat, guess_lon, guess_time, guess_distance, \
                       loc_lat, loc_lon))



  con.commit()
  con.close()


def get_game_id(game):
  if 'challenge' in game['payload']:
    game_id = game['payload']['challenge']['token']
  elif 'map' in game['payload']:
    # this isn't right for some reason
    game_id = game['payload']['map']['gameToken']

  return game_id

def get_game_score(game):
  if 'challenge' in game['payload']:
    game_score = game['payload']['challenge']['score']
  elif 'map' in game['payload']:
    game_score = game['payload']['map']['score']

  return game_score


'''
  Display plot of scores over time.
'''
def scores_over_time(map_slug=None):
  con = sqlite3.connect(DB_PATH)

  if map_slug:
    scores = pd.read_sql_query("SELECT * FROM games WHERE map_slug=?", con, params=[map_slug])
  else:
    scores = pd.read_sql_query("SELECT * FROM games", con)

  labels = {"x":"Date", "y":"Score", "color":"Map Name"}
  fig = px.scatter(x=scores.date, y=scores.score, color=scores.map_name, \
            title="Scores Over Time", labels=labels)
  fig.show()

def main(args):
  if args.mode == "scrape":
    # loading database
    if path.exists(DB_PATH):
      if args.force:
        os.remove(DB_PATH)
      else:
        print("Database already exists. Use -f to replace.")
        return

    authenticate()
    init_db()
    populate_db()

  elif args.mode == "scores_over_time":
    scores_over_time(args.map)

if __name__ == "__main__":
  parser = ArgumentParser(prog="GeoStat.py", description="Statistics Engine for GeoGuessr")
  parser.add_argument("mode",choices=MODES)
  parser.add_argument("-f","--force", action="store_true")
  parser.add_argument("-m","--map", help="Map Slug (find this in the url of the map page)")

  args = parser.parse_args()
  main(args)
