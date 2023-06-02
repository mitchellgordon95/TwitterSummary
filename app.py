from flask import session, Flask, redirect, url_for, request, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from tweepy import OAuthHandler, API
from os import environ
from dotenv import load_dotenv
from datetime import datetime, timedelta
import logging
import time
import tweepy
import openai
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import matplotlib.pyplot as plt
from concurrent.futures import ThreadPoolExecutor
import concurrent


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

def fetch_tweets(access_token, access_token_secret):
    client = tweepy.Client(bearer_token=environ.get("BEARER_TOKEN"), 
                           consumer_key=environ.get('TWITTER_API_KEY'), 
                           consumer_secret=environ.get('TWITTER_API_SECRET'), 
                           access_token=access_token, 
                           access_token_secret=access_token_secret)

    now = datetime.now()
    date_24_hours_ago = now - timedelta(hours=24)
    return client.get_home_timeline(start_time=date_24_hours_ago).data

class TweetCluster:
    def __init__(self, summary=None, example=None, tweets=None, description=None):
        self.tweets = tweets or []
        self.summary = summary
        self.description = description
        self.example = example

SUMMARY_PROMPT = """"Please produce a list of up to 10 topics that are being discussed in these tweets, and give an example of each. Please format the results as

TOPIC: first topic summary
TOPIC DESCRIPTION: 1-2 sentence description
EXAMPLE: example tweet

TOPIC: second topic summary
TOPIC DESCRIPTION: 1-2 sentence description
EXAMPLE: example tweet"""

def parse_topics(input_string):
    print(input_string)
    results = []
    current_topic = None
    current_description = None
    current_example = None

    # TODO - multiple line examples???
    lines = input_string.strip().split('\n')
    for line in lines:
        line = line.strip()
        if line.startswith('TOPIC:'):
            if current_topic:
              results.append(TweetCluster(summary=current_topic, description=current_description, example=current_example))
            current_topic = line.replace('TOPIC:', '').strip()
        if line.startswith('TOPIC DESCRIPTION:'):
            current_description = line.replace('TOPIC DESCRIPTION:', '').strip()
        elif line.startswith('EXAMPLE:'):
            current_example = line.replace('EXAMPLE:', '').strip()

    results.append(TweetCluster(summary=current_topic, description=current_description, example=current_example))

    return results

def generate_topics(tweets):
    # TODO actually count tokens, or reduce the # tweets we send using embeddings somehow...
    tweet_str = '\n'.join([tweet.text for tweet in tweets])
    tweet_str = tweet_str[:10000]
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": f"Here is a list of tweets:\n\n<TWEETS>\n\n{tweet_str}\n\n</TWEETS>\n\n{SUMMARY_PROMPT}"}
    ]

    for attempt in range(1, 4):  # 3 attempts with exponential backoff
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages
            )
            response_text = response.choices[0].message['content'].strip()
            return parse_topics(response_text)
        except Exception as e:
            wait_time = 2 ** attempt
            print(f"Error generating topics on attempt {attempt}. Retrying in {wait_time} seconds. Error: {str(e)}")
            time.sleep(wait_time)

@app.route('/tweets')
@login_required
def tweets():
    # Get Twitter API credentials
    access_token = current_user.access_token
    access_token_secret = current_user.access_token_secret

    # Fetch tweets
    tweets = fetch_tweets(access_token, access_token_secret)

    # Set up the OpenAI API client
    openai.api_key = environ.get('OPENAI_API_KEY')

    # Generate topics
    clusters = generate_topics(tweets)

    # Cluster tweets according to similarity with examples
    clusters = cluster_tweets(tweets, clusters)

    # Sort clusters
    clusters.sort(key=lambda cluster: len(cluster.tweets), reverse=True)

    return render_template('tweets.html', clusters=clusters)

def get_embedding(text):
    response = openai.Embedding.create(model="text-embedding-ada-002", input=[text])
    return response["data"][0]["embedding"]

def get_embeddings(texts):
    with ThreadPoolExecutor() as executor:
        embeddings = list(executor.map(get_embedding, texts))
    return np.array(embeddings)

def cluster_tweets(tweets, clusters):
    # Convert tweets to embeddings and cluster them
    embeddings_array = get_embeddings([tweet.text for tweet in tweets])
    example_embeddings = get_embeddings([cluster.example for cluster in clusters])

    for idx, tweet_embedding in enumerate(embeddings_array):
        similarity_scores = cosine_similarity([tweet_embedding], example_embeddings)
        most_similar_cluster_index = np.argmax(similarity_scores)
        clusters[most_similar_cluster_index].tweets.append(tweets[idx])

    return clusters

if __name__ == '__main__':
    app.run(debug=True)
