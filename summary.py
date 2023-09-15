import openai
from twitter import Thread
from concurrent.futures import ThreadPoolExecutor
from clustering import with_retries, TweetCluster
import re
import time
from collections import Counter
import pickle

SUMMARY_PROMPT = """\
TWEETS:
\"\"\"
{tweets_text}
\"\"\"

Generate a summary of TWEETS. Rules:

- The summary must begin with "{num_tweets} people are talking about"
- The summary must be no more than 1 sentence.
- The summary must only mention topics discussed in a majority of the tweets."""

def generate_summary(cluster):
  if cluster.summary:
    return cluster

  tweets_text = "\n\n".join([thread.text for thread in cluster.threads])
  messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": SUMMARY_PROMPT.format(tweets_text=tweets_text, num_tweets=len(cluster.threads))}
  ]

  def get_summary():
    response = openai.ChatCompletion.create(
      model="gpt-4",
      # model="gpt-3.5-turbo",
      messages=messages
    )
    return response.choices[0].message['content'].strip()

  summary = with_retries(get_summary, "API error")

  return TweetCluster(cluster.threads, hashtags=cluster.hashtags, summary=summary)


def summarize_clusters(clusters):
  # with ThreadPoolExecutor(max_workers=10) as executor:
  #   clusters = list(executor.map(generate_summary, clusters))
  # with open('summaries.pkl', 'wb') as file_:
  #   pickle.dump(clusters, file_)
  with open('summaries.pkl', 'rb') as file_:
    clusters = pickle.load(file_)

  return clusters
