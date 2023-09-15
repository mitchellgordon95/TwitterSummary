import openai
from twitter import Thread
from concurrent.futures import ThreadPoolExecutor
from clustering import with_retries, TweetCluster
import re
import time
from collections import Counter
import pickle

META_SUMMARY_PROMPT="""\
TWEET_SUMMARIES
\"\"\"
{summaries}
\"\"\"

What common theme unites all these tweets? Rules:

- The theme must begin with "{num_tweets} tweets are about"
- The theme must be no more than 1 sentence.
- The theme must be discussed in a majority of the tweets.

Think out loud, then state the topic prefixed with the TOPIC label."""

RESUMMARY_PROMPT = """\
TWEETS:
\"\"\"
{tweets_text}
\"\"\"

What topic do all TWEETS have in common? Rules:

- The topic must be no more than 1 sentence.
- The topic must be discussed in a majority of the tweets.
- The topic must be related to {hashtags}
- The topic must begin with "{num_cluster_tweets} tweets are about the advancements, challenges, and applications of AI and machine learning. More specifically, {num_tweets} are about"

Do not think. Just say the topic and only the topic."""


def resummarize(cluster):
  """Given a meta-cluster, resummarize the subclusters to be more specific."""
  def resummarize_subcluster(subcluster):
    tweets_text = "\n\n".join([thread.text for thread in subcluster.threads])
    messages = [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": RESUMMARY_PROMPT.format(
        tweets_text=tweets_text,
        num_tweets=subcluster.num_tweets,
        num_cluster_tweets=cluster.num_tweets,
        hashtags=" ".join(subcluster.hashtags)
      )}
    ]

    def get_summary():
      response = openai.ChatCompletion.create(
        model="gpt-4",
        # model="gpt-3.5-turbo",
        messages=messages
      )
      return response.choices[0].message['content'].strip()

    summary = with_retries(get_summary, "API error")
    summary = summary.strip('"')
    _, summary = summary.split('More specifically,', 1)
    _, summary = summary.split('about', 1)
    return TweetCluster(subcluster.threads, hashtags=subcluster.hashtags, summary=summary, subclusters=subcluster.subclusters) 

  with ThreadPoolExecutor(max_workers=7) as executor:
    subclusters = list(executor.map(resummarize_subcluster, cluster.subclusters))
  return TweetCluster(cluster.threads, hashtags=cluster.hashtags, summary=cluster.summary, subclusters=subclusters)



def generate_meta_summary(cluster):
  if cluster.summary:
    return cluster

  summaries = "\n\n".join([c.summary for c in cluster.subclusters])
  messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": META_SUMMARY_PROMPT.format(
      summaries=summaries,
      num_tweets=cluster.num_tweets,
    )}
  ]

  def get_summary():
    response = openai.ChatCompletion.create(
      model="gpt-4",
      # model="gpt-3.5-turbo",
      messages=messages
    )
    return response.choices[0].message['content'].strip()

  response_text = with_retries(get_summary, "API error")
  lines = response_text.split("\n")
  summary = None
  for line in lines:
    if "TOPIC" in line:
      summary = line[len("TOPIC")+1:]

  summary = summary.strip('"')
  _, summary = summary.split('about', 1)

  out = TweetCluster(cluster.threads, hashtags=cluster.hashtags, summary=summary, subclusters=cluster.subclusters)
  return resummarize(out)


def meta_summarize(clusters):
  # with ThreadPoolExecutor(max_workers=10) as executor:
  #   clusters = list(executor.map(generate_meta_summary, clusters))
  # with open('meta_summaries.pkl', 'wb') as file_:
  #   pickle.dump(clusters, file_)
  with open('meta_summaries.pkl', 'rb') as file_:
    clusters = pickle.load(file_)

  return clusters
