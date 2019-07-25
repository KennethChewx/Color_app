web: gunicorn main:app
heroku ps:scale web=1 --app color-appx
worker: python main.py
