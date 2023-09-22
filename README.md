# About
"Twitter at a Glance"

- Pulls your last 24 hours of timeline tweets
- Clusters them using ChatGPT (maybe twice)
- Summarize the clusters

If the demo is still up, it's at http://twitter.mitchgordon.me

# Setup

- Copy .env.template to .env
- Fill out necessary API keys
```
pip install -r requirements.txt
sudo apt install python3-flask
flask run --host=0.0.0.0 --debug
```

## "prod"
```
sudo apt install uvicorn
uvicorn app:asgi_app --workers 4 --host 0.0.0.0 --port 5000
```

# TODOs
Redis caching
Actual DB
Speed up summaries by re-prompting something that makes GPT3.5 good
Get Elon to make the API actually affordable
