import tweepy
from os import environ
from datetime import datetime, timedelta
import re

tweet_fields = ["text", "referenced_tweets", "author_id", "conversation_id"]
expansions = ["referenced_tweets.id"]

class Thread():
    def __init__(self, text, conversation_id, thread_ids):
        self.text = text
        self.conversation_id = conversation_id
        self.thread_ids = thread_ids

def expand_retweets(tweet, include_tweets, client):
    # Remove included retweet text, we'll add it later
    tweet_text = re.sub(r'\bRT\b.*', '', tweet.text)

    if not tweet.referenced_tweets:
        return tweet_text, [tweet.id]
    else:
        retweet_id = tweet.referenced_tweets[0].id
        retweet = next((retweet for retweet in include_tweets if retweet.id == retweet_id), None)
        # TODO (mitchg) - we can't expand retweets rn because we're hitting an API limit on the get_tweet endpoint
        # if not retweet:
        #     response = client.get_tweet(retweet_id, tweet_fields=tweet_fields, expansions=expansions)
        #     retweet = response.data
        #     include_tweets = response.includes.get('tweets')
        if retweet:
            expanded_text, expanded_ids = expand_retweets(retweet, include_tweets, client)
            return tweet_text + f"<RETWEET>\n{expanded_text}\n</RETWEET>", [tweet.id, *expanded_ids]
        else:
            return tweet_text, [tweet.id]


def fetch_tweets(access_token, access_token_secret):
    client = tweepy.Client(bearer_token=environ.get("BEARER_TOKEN"), 
                           consumer_key=environ.get('TWITTER_API_KEY'), 
                           consumer_secret=environ.get('TWITTER_API_SECRET'), 
                           access_token=access_token, 
                           access_token_secret=access_token_secret)

    now = datetime.now()
    date_24_hours_ago = now - timedelta(hours=24)

    # fetch the tweets
    response = client.get_home_timeline(start_time=date_24_hours_ago, tweet_fields=tweet_fields, expansions=expansions)

    # create a dictionary to store the collapsed tweets
    collapsed_tweets = {}
    convo_thread_ids = {}

    for tweet in response.data:

        expanded_text, thread_ids = expand_retweets(tweet, response.includes['tweets'], client)
        # if this tweet is part of a conversation we've seen before, append it to the existing tweet
        if tweet.conversation_id in collapsed_tweets:
            collapsed_tweets[tweet.conversation_id] += "\n" + expanded_text
            convo_thread_ids[tweet.conversation_id].extend(thread_ids)
        else:
            collapsed_tweets[tweet.conversation_id] = expanded_text
            convo_thread_ids[tweet.conversation_id] = thread_ids

    return [Thread(text, convo_id, convo_thread_ids[convo_id]) for convo_id, text in collapsed_tweets.items()]
