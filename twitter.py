import tweepy
from os import environ
from datetime import datetime, timedelta
import re

tweet_fields = ["text", "referenced_tweets", "author_id", "conversation_id"]
expansions = ["referenced_tweets.id"]

def expand_retweets(tweet, include_tweets, client):
    # Remove included retweet text, we'll add it later
    tweet_text = re.sub(r'\bRT\b.*', '', tweet.text)

    # TODO (mitchg) - we can't expand retweets rn because we're hitting an API limit on the get_tweet endpoint
    return tweet_text

    if not tweet.referenced_tweets:
        return tweet_text
    else:
        retweet_id = tweet.referenced_tweets[0].id
        retweet = next((retweet for retweet in include_tweets if retweet.id == retweet_id), None)
        if not retweet:
            response = client.get_tweet(retweet_id, tweet_fields=tweet_fields, expansions=expansions)
            retweet = response.data
            includ_tweets = response.includes.get('tweets')
        if retweet:
            return tweet_text + f"<RETWEET>\n{expand_retweets(retweet, include_tweets, client)}\n</RETWEET>"
        else:
            return tweet_text


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

    for tweet in response.data:

        # if this tweet is part of a conversation we've seen before, append it to the existing tweet
        if tweet.conversation_id in collapsed_tweets:
            collapsed_tweets[tweet.conversation_id] += "\n" + expand_retweets(tweet, response.includes['tweets'], client)
        else:
            collapsed_tweets[tweet.conversation_id] = expand_retweets(tweet, response.includes['tweets'], client)

    return list(collapsed_tweets.values())
