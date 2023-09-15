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

from twitter import fetch_tweets
from clustering import cluster_threads, meta_cluster
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
    return render_template('login.html')

@app.route('/login')
def login():
    callback_url = url_for('authorize', _external=True)
    auth = tweepy.OAuthHandler(environ.get('TWITTER_API_KEY'), environ.get('TWITTER_API_SECRET'), callback_url)
    redirect_url = auth.get_authorization_url()
    session['request_token'] = auth.request_token  # updated line
    return redirect(redirect_url)

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
    # TODO - don't make a new user every time we auth twitter
    new_user = User(username=str(np.random.rand()))
    new_user.set_access_token(auth.access_token)
    new_user.set_access_token_secret(auth.access_token_secret)
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)
    return redirect(url_for('tweets'))

@app.route('/tweets')
@login_required
def tweets():
    # Get Twitter API credentials
    access_token = current_user.access_token
    access_token_secret = current_user.access_token_secret
    user_id = current_user.get_id()
    cache_file = f'/tmp/{user_id}.pkl'

    if os.path.exists(cache_file):
      with open(cache_file, 'rb') as file_:
        clusters = pickle.load(file_)
    else:
      # Fetch tweets
      threads = fetch_tweets(access_token, access_token_secret)
      # with open('tweets.pkl', 'wb') as file_:
      #   pickle.dump(threads, file_)
      # with open('tweets.pkl', 'rb') as file_:
      #   threads = pickle.load(file_)

      # Set up the OpenAI API client
      openai.api_key = environ.get('OPENAI_API_KEY')

      # Cluster tweets and summarize
      clusters = cluster_threads(threads)
      print('clustered')
      clusters = summarize_clusters(clusters)
      print('summarized')

      # Cluster the clusters if necessary and summarize
      clusters = meta_cluster(clusters)
      print('meta clustered')
      clusters = meta_summarize(clusters)
      print('meta summarized')

      # TODO - replace this with redis
      with open(cache_file, 'wb') as file_:
        pickle.dump(clusters, file_)

    return render_template('tweets.html', clusters=clusters)


if __name__ == '__main__':
    app.run(debug=True)
