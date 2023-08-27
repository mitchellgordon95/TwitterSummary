import openai
from concurrent.futures import ThreadPoolExecutor

class TweetCluster:
    def __init__(self, tweets, summary=None):
        self.tweets = tweets
        self.summary = summary

def generate_summary(cluster):
    if cluster.summary:
        return cluster

    tweet_str = '\n'.join([f'<TWEET>{tweet}</TWEET>' for tweet in cluster.tweets])
    # TODO - count tokens
    tweet_str = tweet_str[:10000]
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": f"Here is a list of tweets:\n\n<TWEETS>\n\n{tweet_str}\n\n</TWEETS>\n\nPlease generate a short summary of what these tweets are talking about."}
    ]

    for attempt in range(1, 4):  # 3 attempts with exponential backoff
        try:
            print('Summarizing')
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages
            )
            summary = response.choices[0].message['content'].strip()
            if summary.count('.') > 2 and len(cluster.tweets) > 3:
                summary = "MULTIPLE TOPICS"
            return TweetCluster(cluster.tweets, summary)
        except Exception as e:
            wait_time = 2 ** attempt
            print(f"Error generating summary on attempt {attempt}. Retrying in {wait_time} seconds. Error: {str(e)}")
            time.sleep(wait_time)
    return TweetCluster(cluster.tweets, "Unable to generate summary")

def cluster_tweets(tweets):
    clusters = []
    clusters.append(TweetCluster(tweets, summary="One big cluster"))

    return clusters
