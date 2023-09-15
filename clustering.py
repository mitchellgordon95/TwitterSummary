import openai
from twitter import Thread
from concurrent.futures import ThreadPoolExecutor
import re
import time
from collections import Counter
import pickle

class HashtagsThread:
  def __init__(self, thread, hashtags):
    self.text = thread.text
    self.conversation_id = thread.conversation_id
    self.thread_ids = thread.thread_ids
    self.hashtags = hashtags

class TweetCluster:
  def __init__(self, threads, hashtags=None, summary=None):
    self.threads = threads
    self.hashtags = hashtags
    self.summary = summary

def with_retries(func, err_return):
  for attempt in range(1, 4):  # 3 attempts with exponential backoff
    try:
      return func()
    except Exception as e:
      wait_time = 2 ** attempt
      print(f"Error generating summary on attempt {attempt}. Retrying in {wait_time} seconds. Error: {str(e)}")
      time.sleep(wait_time)
  return err_return
  
HASHTAG_PROMPT = """\
TWEET:
{tweet}

Generate 30 possible hashtags that could go with TWEET.

Rules:
If TWEET refers to a location or event, include at least one hashtag containing the name of the event.
If TWEET refers to a specific object or thing, include at least one hashtag containing the name of that thing.
"""

def add_hashtags(thread):
  # TODO - count tokens
  messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": HASHTAG_PROMPT.format(tweet=thread.text)}
  ]

  def get_hashtags():
    response = openai.ChatCompletion.create(
      # model="gpt-4",
      model="gpt-3.5-turbo",
      messages=messages
    )
    response_text = response.choices[0].message['content'].strip()
    hashtags = re.findall(r'#\w+', response_text)

    return [h.lower() for h in hashtags]

  hashtags = with_retries(get_hashtags, [])

  return HashtagsThread(thread, hashtags)


def count_hashtags(threads):
  hashtag_counter = Counter()
  for thread in threads:
    for h in thread.hashtags:
      hashtag_counter[h] += 1
  return hashtag_counter


def cluster_threads(threads):
  # with ThreadPoolExecutor(max_workers=100) as executor:
  #   threads = list(executor.map(add_hashtags, threads))
  # with open('hashtag_threads.pkl', 'wb') as file_:
  #   pickle.dump(threads, file_)
  with open('hashtag_threads.pkl', 'rb') as file_:
    threads = pickle.load(file_)

  hashtag_counter = count_hashtags(threads)

  clusters = []
  used_hashtags = set()
  threads = set(threads)
  for hashtag, _ in hashtag_counter.most_common():
    relevant_threads = set([thread for thread in threads if hashtag in thread.hashtags])
    if len(relevant_threads) < 8:
      used_hashtags.add(hashtag)
      threads = threads - relevant_threads

      # Grab more threads that seem relevant until we hit 7
      all_cluster_hashtags = count_hashtags(relevant_threads)
      used_cluster_hashtags = set([hashtag])
      while len(relevant_threads) < 7:
        found = False
        for c_hashtag, _ in all_cluster_hashtags.most_common():
          try:
            another_relevant_thread = next(iter([thread for thread in threads if c_hashtag in thread.hashtags]))
          except Exception:
            continue

          found = True
          used_cluster_hashtags.add(c_hashtag)
          used_hashtags.add(c_hashtag)
          relevant_threads.add(another_relevant_thread)
          threads.remove(another_relevant_thread)
          break

        if not found:
          break
        
      if len(relevant_threads) > 3:
        clusters.append(TweetCluster(relevant_threads, hashtags=used_cluster_hashtags))
      else:
        threads.update(relevant_threads)

  misc = []
  for thread in threads:
    found = False
    for h in used_hashtags:
      found = found or h in thread.hashtags
    if not found:
      misc.append(thread)
  clusters.append(TweetCluster(misc, summary="misc"))

  return clusters
