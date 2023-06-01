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
from sklearn.cluster import KMeans
from sklearn.manifold import TSNE
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
    def __init__(self, tweets, embeddings, summary=None):
        self.tweets = tweets
        self.embeddings = embeddings
        self.summary = summary

def generate_summary(cluster):
    if cluster.summary:
        return cluster

    tweet_str = '\n'.join([tweet.text for tweet in cluster.tweets])
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": f"Here is a list of tweets:\n\n{tweet_str}\n\nCan you generate a 1-2 sentence summary topic for these tweets or say 'MULTIPLE TOPICS' if they are about different topics?"}
    ]

    for attempt in range(1, 4):  # 3 attempts with exponential backoff
        try:
            print('Summarizing')
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages
            )
            summary = response.choices[0].message['content'].strip()
            if len(cluster.tweets) == 1:
                summary = f"1 person is talking about {summary}"
            else:
                summary = f"{len(cluster.tweets)} people are talking about {summary}"
            return TweetCluster(cluster.tweets, cluster.embeddings, summary)
        except Exception as e:
            wait_time = 2 ** attempt
            print(f"Error generating summary on attempt {attempt}. Retrying in {wait_time} seconds. Error: {str(e)}")
            time.sleep(wait_time)
    return TweetCluster(cluster.tweets, cluster.embeddings, "Unable to generate summary")

def subdivide(cluster):
    # Create two new clusters
    sub_clustered_tweets = cluster_tweets(cluster.embeddings, cluster.tweets, 2)
    
    return sub_clustered_tweets

def process_clusters(clusters):
    # Generate summaries for all clusters
    with ThreadPoolExecutor() as executor:
      clusters = list(executor.map(generate_summary, clusters))

    # Identify clusters that cover multiple topics
    multiple_topics_clusters = [cluster for cluster in clusters if 'MULTIPLE TOPICS' in cluster.summary and len(cluster.tweets) > 3]

    # If there are no clusters with multiple topics, we are done
    if not multiple_topics_clusters:
        return clusters

    # Generate a list of new clusters by subdividing clusters with multiple topics
    new_clusters = [new_cluster for cluster in multiple_topics_clusters for new_cluster in subdivide(cluster)]

    # Replace clusters with multiple topics with their subdivisions
    clusters = [cluster for cluster in clusters if cluster not in multiple_topics_clusters] + new_clusters

    return process_clusters(clusters)  # Recursively process the clusters until there are no clusters with multiple topics

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

    # Convert tweets to embeddings and cluster them
    embeddings_array = get_embeddings(tweets)
    clusters = cluster_tweets(embeddings_array, tweets, 10)

    # Process clusters until there are no clusters with multiple topics
    clusters = process_clusters(clusters)

    # Sort clusters
    clusters.sort(key=lambda cluster: len(cluster.tweets), reverse=True)

    return render_template('tweets.html', clusters=clusters)

def get_embeddings(tweets):
    embeddings = []
    with ThreadPoolExecutor() as executor:
        future_to_embedding = {executor.submit(openai.Embedding.create, model="text-embedding-ada-002", input=[tweet.text]): tweet for tweet in tweets}
        for future in concurrent.futures.as_completed(future_to_embedding):
            response = future.result()
            embeddings.append(response["data"][0]["embedding"])
    return np.array(embeddings)

def cluster_tweets(embeddings_array, tweets, num_clusters):
    kmeans = KMeans(n_clusters=num_clusters, random_state=0).fit(embeddings_array)

    clusters = []
    for i in range(num_clusters):
        indices = np.where(kmeans.labels_ == i)[0]
        cluster_tweets = [tweets[j] for j in indices]
        cluster_embeddings = embeddings_array[indices]
        clusters.append(TweetCluster(cluster_tweets, cluster_embeddings))

    return clusters

if __name__ == '__main__':
    app.run(debug=True)
