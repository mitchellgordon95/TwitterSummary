# Setup

pip install -r requirements.txt
sudo apt install python3-flask
flask run --host=0.0.0.0 --debug

## "prod"
sudo apt install uvicorn
uvicorn app:asgi_app --workers 4 --host 0.0.0.0 --port 5000

TODOs

.env.template, rotate keys, gitignore .env
login polish

Later
Redis caching
Actual DB
Speed up summaries by re-prompting something that makes GPT3.5 good