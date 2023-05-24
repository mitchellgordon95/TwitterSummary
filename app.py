from flask import session, Flask, redirect, url_for, request, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from tweepy import OAuthHandler, API
from os import environ
from dotenv import load_dotenv
from datetime import datetime, timedelta
import tweepy
import openai
import numpy as np
from sklearn.cluster import KMeans
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt

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
    new_user = User(username='test')
    new_user.set_access_token(auth.access_token)
    new_user.set_access_token_secret(auth.access_token_secret)
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)
    return redirect(url_for('tweets'))

def elbow_method(embeddings_array):
    # Perform the Elbow Method
    scores = []
    max_clusters = 10  # adjust as needed
    for k in range(2, max_clusters+1):
        kmeans = KMeans(n_clusters=k, random_state=0).fit(embeddings_array)
        score = kmeans.inertia_
        scores.append(score)

    if DEBUG:
      # Create the Elbow Method plot
      plt.figure(figsize=(10, 10))
      plt.plot(range(2, max_clusters+1), scores, marker='o')
      plt.title('The Elbow Method')
      plt.xlabel('Number of clusters')
      plt.ylabel('WCSS')  # Within-Cluster-Sum-of-Squares
      plt.savefig('elbow.png')  # save to a file

    return scores.index(min(scores)) + 2  # +2 because our range starts at 2

def tsne(embeddings_array, optimal_clusters, kmeans):
    # Perform t-SNE
    tsne = TSNE(n_components=2, random_state=0)
    embeddings_2d = tsne.fit_transform(embeddings_array)

    # Create a scatter plot
    plt.figure(figsize=(10, 10))
    for i in range(optimal_clusters):
        points = embeddings_2d[kmeans.labels_ == i]
        plt.scatter(points[:, 0], points[:, 1], label=f'Cluster {i}')
    plt.legend()
    plt.savefig('clusters.png')  # save to a file

@app.route('/tweets')
@login_required
def tweets():
    # Get Twitter API credentials
    access_token = current_user.access_token
    access_token_secret = current_user.access_token_secret
    print(f'tweets user id {current_user.id}')

    # Set up the Twitter API client
    client = tweepy.Client(bearer_token=environ.get("BEARER_TOKEN"), 
                           consumer_key=environ.get('TWITTER_API_KEY'), 
                           consumer_secret=environ.get('TWITTER_API_SECRET'), 
                           access_token=access_token, 
                           access_token_secret=access_token_secret)

    now = datetime.now()
    date_24_hours_ago = now - timedelta(hours=24)
    tweets = client.get_home_timeline(start_time=date_24_hours_ago)

    # Set up the OpenAI API client
    openai.api_key = environ.get('OPENAI_API_KEY')

    # Convert tweets to embeddings
    embeddings = []
    for tweet in tweets.data:
        response = openai.Embedding.create(
            model="text-embedding-ada-002",
            input=[tweet.text]
        )
        embeddings.append(response["data"][0]["embedding"])

    embeddings_array = np.array(embeddings)
    optimal_clusters = 10
    kmeans = KMeans(n_clusters=optimal_clusters, random_state=0).fit(embeddings_array)

    if DEBUG:
        tsne(embeddings_array, optimal_clusters, kmeans)

    # Assign each tweet to a cluster and generate a summary for each cluster
    clustered_tweets = {i: [] for i in range(optimal_clusters)}
    cluster_summaries = {i: '' for i in range(optimal_clusters)}
    for i, label in enumerate(kmeans.labels_):
        clustered_tweets[label].append(tweets.data[i].text)
    
    for i in range(optimal_clusters):
        # Join all tweets in the cluster into a single text
        tweet_str = '\n'.join(clustered_tweets[i])
        prompt = f"Here is a list of tweets:\n\n{tweet_str}\n\nPlease generate a summary topic for these tweets.\n\nAll these tweets are tweeting about"
        print(prompt)

        # Generate a summary using the OpenAI API
        response = openai.Completion.create(
            model="text-davinci-002",
            prompt=prompt,
            temperature=0.7,
            max_tokens=60,
            stop="\n",
        )

        summary = response.choices[0].text.strip()
        cluster_summaries[i] = f"{len(clustered_tweets[i])} people are talking about {summary}"

    return render_template('tweets.html', clustered_tweets=clustered_tweets, cluster_summaries=cluster_summaries)


if __name__ == '__main__':
    app.run(debug=True)
