from flask import session, Flask, redirect, url_for, request, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import tweepy
import os
from os import environ
from dotenv import load_dotenv
import logging
import numpy as np
import openai
import pickle
import time
from datetime import datetime
from asgiref.wsgi import WsgiToAsgi

from twitter import fetch_tweets
from clustering import cluster_threads, meta_cluster, TweetCluster
from summary import summarize_clusters
from meta_summary import meta_summarize

DEBUG = False

load_dotenv()

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/test.db'  # Use SQLite for simplicity
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # TODO - rename this to twitter ID
    username = db.Column(db.String(64), index=True, unique=True)
    access_token = db.Column(db.String(200))
    access_token_secret = db.Column(db.String(200))

    def set_access_token(self, token):
        self.access_token = token

    def set_access_token_secret(self, secret):
        self.access_token_secret = secret

@login_manager.user_loader
def user_loader(user_id):
    print(f'user loader id {user_id}')
    print(f'user {db.session.query(User).get(user_id)}')
    return db.session.query(User).get(user_id)

@app.route('/')
def home():
    if current_user.is_authenticated:
      return redirect(url_for('tweets'))
    return render_template('login.html')

@app.route('/login')
def login():
    callback_url = url_for('authorize', _external=True)
    auth = tweepy.OAuthHandler(environ.get('TWITTER_API_KEY'), environ.get('TWITTER_API_SECRET'), callback_url)
    redirect_url = auth.get_authorization_url()
    session['request_token'] = auth.request_token  # updated line
    return redirect(redirect_url)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/authorize')
def authorize():
    verifier = request.args.get('oauth_verifier')
    auth = tweepy.OAuthHandler(environ.get('TWITTER_API_KEY'), environ.get('TWITTER_API_SECRET'))
    token = session.pop('request_token')
    auth.request_token = token
    try:
        auth.get_access_token(verifier)
    except tweepy.TweepError:
        print('Error! Failed to get access token.')

    api = tweepy.API(auth)
    user_info = api.verify_credentials()
    user_id = user_info._json['id_str']
    user = db.session.query(User).filter_by(username=user_id).first()
    if not user:
      user = User(username=user_id)
      db.session.add(user)

    user.set_access_token(auth.access_token)
    user.set_access_token_secret(auth.access_token_secret)
    db.session.commit()
    login_user(user)

    return redirect(url_for('tweets'))

OPENAI_ERROR_MSG = 'Oops, we probably hit the OpenAI API limit. I\'m not made of money!'

def load_cache(cache_file, last_cache_time):
  with open(cache_file, 'rb') as file_:
    clusters = pickle.load(file_)
    if clusters and clusters[0].summary.startswith('You might have refreshed the page') and (time.time() - last_cache_time) > 180:
      raise Exception()
    return clusters
  

@app.route('/tweets')
@login_required
async def tweets():
    # Get Twitter API credentials
    access_token = current_user.access_token
    access_token_secret = current_user.access_token_secret
    user_id = current_user.get_id()
    cache_file = f'/tmp/{user_id}.pkl'

    if os.path.exists(cache_file) and (time.time() - os.path.getmtime(cache_file)) / 60 / 60 < 24:
      try:
        last_cache_time = os.path.getmtime(cache_file)
        clusters = load_cache(cache_file, last_cache_time)
      except:
        os.remove(cache_file)
        return render_template('error.html', message="Oops, something went wrong. Try refreshing the page?")
    else:
      last_cache_time = time.time()
      with open(cache_file, 'wb') as file_:
        pickle.dump([TweetCluster(threads=[], summary="You might have refreshed the page while it was still loading. Please check back in a minute or two.")], file_)
      # Fetch tweets
      try:
        threads = fetch_tweets(access_token, access_token_secret)
      except Exception as e:
        print(e)
        os.remove(cache_file)
        return render_template('twitter_error.html')
      # with open('tweets.pkl', 'wb') as file_:
      #   pickle.dump(threads, file_)
      # with open('tweets.pkl', 'rb') as file_:
      #   threads = pickle.load(file_)

      # Set up the OpenAI API client
      openai.api_key = environ.get('OPENAI_API_KEY')

      try:
        print('starting')
        # Cluster tweets and summarize
        clusters = await cluster_threads(threads)
        print('clustered')
        clusters = await summarize_clusters(clusters)
        print('summarized')

        # Cluster the clusters if necessary and summarize
        clusters = meta_cluster(clusters)
        print('meta clustered')
        clusters = await meta_summarize(clusters)
        print('meta summarized')
      except Exception as e:
        os.remove(cache_file)
        return render_template('error.html', message=OPENAI_ERROR_MSG)

      # TODO - replace this with redis
      with open(cache_file, 'wb') as file_:
        pickle.dump(clusters, file_)

    next_refresh = last_cache_time + 24 * 60 * 60
    return render_template('tweets.html', clusters=clusters, next_refresh=next_refresh)

asgi_app = WsgiToAsgi(app)
