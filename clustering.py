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
    def __init__(self, threads, summary=None):
        self.threads = threads
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



def cluster_threads(threads):
    # with ThreadPoolExecutor(max_workers=100) as executor:
    #     threads = list(executor.map(add_hashtags, threads))
    # with open('hashtag_threads.pkl', 'wb') as file_:
    #   pickle.dump(threads, file_)
    with open('hashtag_threads.pkl', 'rb') as file_:
      threads = pickle.load(file_)

    hashtag_counter = Counter()
    for thread in threads:
        for h in thread.hashtags:
            hashtag_counter[h] += 1

    clusters = []
    used_hashtags = []
    for hashtag, count in hashtag_counter.most_common():
        if count < 8 and count > 3:
          relevant_threads = [thread for thread in threads if hashtag in thread.hashtags]
          used_hashtags.append(hashtag)
          clusters.append(TweetCluster(relevant_threads, summary=hashtag))

    misc = []
    for thread in threads:
        found = False
        for h in used_hashtags:
            found = found or h in thread.hashtags
        if not found:
            misc.append(thread)
    clusters.append(TweetCluster(misc, "misc"))

    return clusters
