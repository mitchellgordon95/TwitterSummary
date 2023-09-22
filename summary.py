import openai
from twitter import Thread
import asyncio
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

What topic do all TWEETS have in common? Rules:

- The topic must begin with "{num_tweets} tweets are about"
- The topic must be no more than 1 sentence.
- The topic must be discussed in a majority of the tweets.
- The topic must be related to {hashtags}

Think out loud, then state the topic prefixed with the TOPIC label."""

async def generate_summary(cluster):
  if cluster.summary:
    return cluster

  tweets_text = "\n\n".join([thread.text for thread in cluster.threads])
  messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": SUMMARY_PROMPT.format(
      tweets_text=tweets_text,
      num_tweets=len(cluster.threads),
      hashtags=" ".join(cluster.hashtags)
    )}
  ]

  async def get_summary():
    print("sending request...")
    response = await openai.ChatCompletion.acreate(
      model="gpt-4",
      # model="gpt-3.5-turbo",
      messages=messages
    )
    return response.choices[0].message['content'].strip()

  response_text = await with_retries(get_summary, "API error")

  try:
    lines = response_text.split("\n")
    summary = None
    for line in lines:
      if "TOPIC" in line:
        summary = line[len("TOPIC")+1:]

    if summary:
      summary = summary.strip('"')
      _, summary = summary.split('about', 1)
  except:
    summary = f"Error parsing model output: {response_text}"

  return TweetCluster(cluster.threads, hashtags=cluster.hashtags, summary=summary)


async def summarize_clusters(clusters):
  clusters = await asyncio.gather(*[generate_summary(cluster) for cluster in clusters])
  # with open('summaries.pkl', 'wb') as file_:
  #   pickle.dump(clusters, file_)
  # with open('summaries.pkl', 'rb') as file_:
  #   clusters = pickle.load(file_)

  return clusters
